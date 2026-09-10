"""Live HTTPS receipts and browser persistence; server-local temporary test key."""
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
import httpx
from dotenv import dotenv_values

ROOT = Path('/home/ubuntu/haudi-hermes')
ENV = {**os.environ, 'PATH': str(ROOT / 'runtime/bin') + ':' + str(ROOT / 'runtime/node/bin') + ':' + os.environ.get('PATH', '')}


def browser(*args):
    return subprocess.check_output(['agent-browser', '--session', 'haudi-activity', *args], env=ENV, text=True, stderr=subprocess.DEVNULL)


def control(label, action='click', value=None):
    for _ in range(30):
        snapshot = browser('snapshot', '-i')
        lines = [line for line in snapshot.splitlines() if label in line and 'ref=' in line]
        if len(lines) == 1:
            ref = '@' + re.search(r'ref=(e\d+)', lines[0])[1]
            return browser(action, ref, *([value] if value is not None else []))
        time.sleep(.5)
    raise AssertionError('Missing unique visible control: ' + label)


def verify_api(client):
    prompt = 'activity-check-' + uuid.uuid4().hex + ' 请通过 Europe PMC 工具检索 EXT_ID:PMC10172116 OR PMCID:PMC10172116，最多返回2篇；再用 europepmc_fulltext 读取 PMC10172116 的前1000字符。仅根据实际结果用中文回答一句话。'
    receipts = []
    started = time.monotonic()
    with client.stream('POST', '/api/chat/completions', json={'model': 'ws-deepseek-v4-pro', 'stream': True, 'messages': [{'role': 'user', 'content': prompt}]}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if time.monotonic() - started > 300:
                raise TimeoutError('Research receipt check exceeded five minutes')
            if not line.startswith('data:'):
                continue
            raw = line[5:].strip()
            if raw == '[DONE]':
                break
            event = json.loads(raw)
            assert not event.get('error'), 'Stream error'
            entry = event.get('event', {}).get('data', {})
            if entry.get('activity'):
                receipts.append(entry)
                a = entry['activity']
                print(json.dumps({'seconds': round(time.monotonic() - started, 1), 'title': a['title'], 'state': a['state'], 'detail': a.get('detail'), 'summary': a.get('summary'), 'items': a.get('items')}, ensure_ascii=False), flush=True)
    completed = [r['activity'] for r in receipts if r['activity']['state'] == 'completed']
    assert any(a.get('items') and any('含摘要' in i.get('note', '') or '题录' in i.get('note', '') for i in a['items']) for a in completed), 'No actual literature titles'
    assert any('已读取正文' in a.get('summary', '') for a in completed), 'No fulltext receipt'
    for end in [r for r in receipts if r['activity']['state'] == 'completed']:
        assert any(r['toolCallId'] == end['toolCallId'] and r['activity']['state'] == 'running' for r in receipts[:receipts.index(end)])
    return {'elapsed_seconds': round(time.monotonic() - started, 1), 'receipts': receipts}


def verify_browser(client):
    browser('open', 'https://42.193.15.167/')
    control('link "新科研任务"')
    for _ in range(70):
        snapshot = browser('snapshot', '-i')
        if '已选择：DeepSeek V4 Pro' in snapshot:
            break
        time.sleep(1)
    else:
        raise AssertionError('New-chat model was not selected')
    # Grounded in the page's observed contenteditable input label.
    marker = 'activity-browser-' + uuid.uuid4().hex
    control('generic "描述你的研究主题、科学问题或写作任务"', 'fill', marker + ' 请用 web_search 检索 Articraft LLM articulated asset generation，最多2条；然后用 web_extract 读取最相关的一条来源页面。简短给出实际找到的题名和来源链接。请用中文，不使用终端。')
    browser('press', 'Enter')
    seen = {'running_detail': False, 'result_before_end': False, 'completed': False, 'persisted': False}
    url = None
    try:
        for _ in range(180):
            page = browser('eval', 'document.body.innerText')
            seen['running_detail'] |= '执行中' in page and '检索式：' in page
            seen['result_before_end'] |= '返回 ' in page and '条结果' in page and '本轮已结束' not in page
            if '本轮已结束' in page and '读取 ' in page and '个页面' in page:
                seen['completed'] = True
                break
            time.sleep(1)
        assert all(seen[k] for k in ('running_detail', 'result_before_end', 'completed')), seen
        url = browser('get', 'url').strip()
        assert re.fullmatch(r'https://42\.193\.15\.167/c/[\w-]+', url), 'Expected test chat URL'
        browser('open', url)
        for _ in range(30):
            page = browser('eval', 'document.body.innerText')
            if '研究过程' in page and '检索式：' in page and '条结果' in page and '个页面' in page:
                seen['persisted'] = True
                break
            time.sleep(1)
        assert seen['persisted'], 'Receipts missing after reload'
        chat = client.get('/api/v1/chats/' + url.rsplit('/', 1)[-1]).json()
        histories = [m.get('statusHistory', []) for m in chat['chat']['history']['messages'].values() if m.get('role') == 'assistant']
        activities = [entry['activity'] for history in histories for entry in history if entry.get('activity')]
        assert any(a.get('items') for a in activities), 'No persisted result links'
        seen['activities'] = activities
        print(json.dumps({k: v for k, v in seen.items() if k != 'activities'}), flush=True)
        return seen
    finally:
        current = url or browser('get', 'url').strip()
        if re.fullmatch(r'https://42\.193\.15\.167/c/[\w-]+', current):
            chat_id = current.rsplit('/', 1)[-1]
            chat = client.get('/api/v1/chats/' + chat_id).json()
            if marker in json.dumps(chat):
                client.delete('/api/v1/chats/' + chat_id).raise_for_status()


def main(browser_only=False):
    account = json.loads((ROOT / 'openwebui/access.json').read_text())
    added = False
    with httpx.Client(base_url='https://42.193.15.167', timeout=300, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: account[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        try:
            catalog = client.get('/api/workstation/catalog').json()
            if not catalog['credentials']['deepseek']['configured']:
                env = dotenv_values(ROOT / 'state/.env')
                key = env.get('DEEPSEEK_API_KEY') or env.get('OPENAI_API_KEY')
                assert key
                response = client.post('/api/workstation/credentials', json={'model_id': 'ws-deepseek-v4-pro', 'endpoint_id': 'official', 'api_key': key})
                response.raise_for_status()
                added = True
            path = ROOT / 'openwebui/activity-verification.json'
            report = json.loads(path.read_text()) if browser_only else {'verified_at': datetime.now(timezone.utc).isoformat(), 'api': verify_api(client)}
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            report['browser'] = verify_browser(client)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            if added:
                client.delete('/api/workstation/credentials/deepseek').raise_for_status()
            browser('close')
            print('Temporary verification credentials cleared; browser closed.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser-only', action='store_true')
    main(parser.parse_args().browser_only)
