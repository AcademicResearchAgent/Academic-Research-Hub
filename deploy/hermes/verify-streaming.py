"""Measure real HTTPS reasoning/status streams without printing provider reasoning or keys."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

import httpx
from dotenv import dotenv_values

ROOT = Path('/home/ubuntu/haudi-hermes')


def verify_chat(client, model):
    prompt = 'stream-check-' + uuid.uuid4().hex + ' 请先调用 research_citation 工具，为题名 Cultivating CRISPR、DOI 10.1089/crispr.2018.29011.rba 排版引用，再用一句话说明排版与真实性核验的区别。不要使用终端。'
    start = time.monotonic()
    first_status = first_reasoning = first_content = None
    reasoning_chunks = content_chunks = 0
    tool_status = False
    with client.stream('POST', '/api/chat/completions', json={'model': model, 'stream': True,
                       'messages': [{'role': 'user', 'content': prompt}]}) as response:
        assert response.status_code == 200, 'Chat HTTP ' + str(response.status_code)
        for line in response.iter_lines():
            if not line.startswith('data:'):
                continue
            raw = line[5:].strip()
            if raw == '[DONE]':
                break
            event = json.loads(raw)
            assert not event.get('error'), 'Chat stream reported an error'
            status = event.get('event', {})
            if status.get('type') == 'status':
                if first_status is None:
                    first_status = time.monotonic() - start
                tool_status |= '工具' in status.get('data', {}).get('description', '')
            for choice in event.get('choices', []):
                delta = choice.get('delta', {})
                if delta.get('reasoning_content'):
                    reasoning_chunks += 1
                    if first_reasoning is None:
                        first_reasoning = time.monotonic() - start
                if delta.get('content'):
                    content_chunks += 1
                    if first_content is None:
                        first_content = time.monotonic() - start
    assert reasoning_chunks and content_chunks, 'Missing live reasoning or answer deltas'
    assert first_status is not None and first_status <= first_reasoning, 'Initial status must precede reasoning'
    assert first_reasoning <= first_content, 'Expected reasoning before answer'
    assert tool_status, 'Missing tool execution status'
    return {'model': model, 'first_status_seconds': round(first_status, 3),
            'first_reasoning_seconds': round(first_reasoning, 3), 'first_content_seconds': round(first_content, 3),
            'reasoning_chunks': reasoning_chunks, 'content_chunks': content_chunks, 'tool_status': tool_status}


def verify_browser(input_ref):
    env = {**os.environ, 'PATH': str(ROOT / 'runtime/bin') + ':' + str(ROOT / 'runtime/node/bin') + ':' + os.environ.get('PATH', '')}
    command = ['agent-browser', '--session', 'haudi-streaming']
    def browser(*args):
        return subprocess.check_output([*command, *args], env=env, text=True, stderr=subprocess.DEVNULL)
    initial = browser('eval', 'document.body.innerText')
    assert not any(x in initial for x in ('思考用时', 'Rodolphe Barrangou')), 'Start a new empty task before browser verification'
    browser('fill', input_ref, '请调用 research_citation 工具，为论文 Cultivating CRISPR（DOI 10.1089/crispr.2018.29011.rba）排版引用，然后简短说明如何核验引用。不要使用终端。')
    browser('press', 'Enter')
    seen = {'waiting_status': False, 'reasoning_visible': False, 'tool_status': False, 'answer_visible': False}
    for _ in range(60):
        text = browser('eval', 'document.body.innerText')
        seen['waiting_status'] |= any(x in text for x in ('正在连接科研助手', '正在处理研究任务', '正在思考', '正在生成回答', '已用时'))
        seen['reasoning_visible'] |= any(x in text for x in ('思考用时', '思考了', 'Thinking', 'Thought for'))
        seen['tool_status'] |= '正在执行工具任务' in text or '工具执行结束' in text
        seen['answer_visible'] |= 'https://doi.org/10.1089/crispr.2018.29011.rba' in text
        if all(seen.values()):
            break
        time.sleep(1)
    assert all(seen.values()), seen
    return seen


def main(browser_ref=None, browser_only=False):
    account = json.loads((ROOT / 'openwebui/access.json').read_text())
    added = False
    with httpx.Client(base_url='https://42.193.15.167', timeout=600, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: account[k] for k in ('email', 'password')})
        assert response.status_code == 200, 'Test administrator sign-in failed'
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        catalog = client.get('/api/workstation/catalog').json()
        try:
            if not catalog['credentials']['deepseek']['configured']:
                env = dotenv_values(ROOT / 'state/.env')
                key = env.get('DEEPSEEK_API_KEY') or env.get('OPENAI_API_KEY')
                assert key, 'No existing test key'
                result = client.post('/api/workstation/credentials', json={'model_id': 'ws-deepseek-v4-flash', 'endpoint_id': 'official', 'api_key': key})
                assert result.status_code == 200, 'Test credential validation failed'
                added = True
            report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'models': []}
            report_path = ROOT / 'openwebui/streaming-verification.json'
            for model in (() if browser_only else ('ws-deepseek-v4-flash', 'ws-deepseek-v4-pro')):
                entry = verify_chat(client, model)
                report['models'].append(entry)
                report_path.write_text(json.dumps(report, indent=2))
                print(json.dumps(entry), flush=True)
            if browser_ref:
                report['browser'] = verify_browser(browser_ref)
                print(json.dumps(report['browser']), flush=True)
            if browser_only:
                report_path = ROOT / 'openwebui/streaming-browser-verification.json'
            report_path.write_text(json.dumps(report, indent=2))
        finally:
            if added:
                result = client.delete('/api/workstation/credentials/deepseek')
                assert result.status_code == 200, 'Temporary key cleanup failed'
                print('Temporary test key removed.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser-input-ref', help='Optional observed editable input ref in the signed-in haudi-streaming test browser')
    parser.add_argument('--browser-only', action='store_true', help='Only repeat browser acceptance, without repeating model API probes')
    args = parser.parse_args()
    if args.browser_only and not args.browser_input_ref:
        parser.error('--browser-only requires --browser-input-ref')
    main(args.browser_input_ref, args.browser_only)
