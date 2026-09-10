"""Synthetic-only browser upload and real-model project/thread acceptance.

Prepare first; execution verifies the exact upload and official endpoint before
temporarily configuring the existing authorized DeepSeek key on the test user.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import httpx
from dotenv import dotenv_values

ROOT = Path('/home/ubuntu/haudi-hermes')
PROBE = b'Synthetic workspace test input. Contains no personal or research data.'
ENDPOINT = 'https://api.deepseek.com/v1'
TITLE = '网页科研工作流验收'
MODEL = 'ws-deepseek-v4-pro'
MANIFEST = ROOT / 'workspace-browser-workflow-probe.json'


def main():
    global MANIFEST
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute-verified', action='store_true')
    parser.add_argument('--scope', choices=('preview', 'production'), default='preview')
    args = parser.parse_args()
    production = args.scope == 'production'
    base = 'https://42.193.15.167' if production else 'http://127.0.0.1:9120'
    prefix = 'workspace-production-browser-workflow' if production else 'workspace-browser-workflow'
    MANIFEST = ROOT / (prefix + '-probe.json')
    fixture = json.loads((ROOT / ('workspace-' + args.scope + '-fixtures.json')).read_text())[0]
    spec = importlib.util.spec_from_file_location('workflow_browser', Path(__file__).with_name('verify-browser.py'))
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    # The dedicated browser runs as ubuntu even when the verification is root.
    helper_spec = importlib.util.spec_from_file_location('workflow_browser_auth', Path(__file__).with_name('verify-history-browser.py'))
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    ui.browser = helper.browser
    if production:
        record = json.loads((ROOT / 'workspace-production.json').read_text())
        assert record['phase'] == 'active' and fixture.get('synthetic_production_acceptance') is True
    with httpx.Client(base_url=base, timeout=60, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: fixture[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']

        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

        catalog = call('GET', '/api/workstation/catalog').json()
        endpoint = next(item for item in catalog['providers']['deepseek']['endpoints'] if item['id'] == 'official')
        assert endpoint['url'].rstrip('/') == ENDPOINT
        assert not catalog['credentials']['deepseek']['configured'], 'Inspect an existing fixture credential before running'
        if not args.execute_verified:
            if MANIFEST.exists():
                manifest = json.loads(MANIFEST.read_text())
                assert manifest['phase'] in {'created', 'prepared'}, 'Existing workflow must be inspected before rerunning'
            else:
                created = call('POST', '/api/workstation/projects', json={'title': TITLE}).json()
                manifest = {'project': created['project']['id'], 'thread': created['thread'],
                            'owner': fixture['id'], 'endpoint': ENDPOINT, 'model': MODEL, 'phase': 'created'}
                MANIFEST.write_text(json.dumps(manifest, indent=2))
            assert manifest['owner'] == fixture['id']
            assert call('GET', '/api/workstation/threads/' + manifest['thread'] + '/workspace').json()['id'] == manifest['project']
            target = base + '/c/' + manifest['thread']
            if ui.browser('get', 'url').strip() != target:
                ui.browser('open', target)
            ui.wait_for('link "' + TITLE + '"')
            files = call('GET', '/api/workstation/projects/' + manifest['project'] + '/files').json()
            if not files:
                ui.click('tab "资源管理器"')
                ui.wait_for('button "上传"')
                selector = '[aria-label="项目列表"] input[type="file"]'
                count = ui.browser('get', 'count', selector).strip()
                assert count == '1', 'Expected the actual workspace file input'
                directory = ROOT / (prefix + '-input')
                directory.mkdir(exist_ok=True)
                source = directory / 'probe-input.txt'
                source.write_bytes(PROBE)
                ui.click('button "上传"')
                ui.browser('upload', selector, str(source))
                ui.wait_for('button "▤probe-input.txt"')
                files = call('GET', '/api/workstation/projects/' + manifest['project'] + '/files').json()
            assert len(files) == 1 and files[0]['name'] == 'probe-input.txt'
            content = call('GET', '/api/workstation/files/' + files[0]['id'] + '/content').content
            assert content == PROBE
            manifest.update(input=files[0]['id'], sha256=hashlib.sha256(content).hexdigest(), phase='prepared', browser_upload=True)
            MANIFEST.write_text(json.dumps(manifest, indent=2))
            print(json.dumps({'preflight': 'passed', 'browser_upload': True, 'project_files': 1,
                              'exact_input': PROBE.decode(), 'sha256': manifest['sha256'],
                              'external_endpoint': ENDPOINT, 'api_key_read': False, 'external_model_called': False}), flush=True)
            return

        manifest = json.loads(MANIFEST.read_text())
        assert manifest['phase'] in {'prepared', 'executing'} and manifest['owner'] == fixture['id'] and manifest['endpoint'] == ENDPOINT
        files = call('GET', '/api/workstation/projects/' + manifest['project'] + '/files').json()
        assert len(files) == 1 and files[0]['id'] == manifest['input']
        content = call('GET', '/api/workstation/files/' + manifest['input'] + '/content').content
        assert content == PROBE and hashlib.sha256(content).hexdigest() == manifest['sha256']
        assert not call('GET', '/api/v1/chats/' + manifest['thread']).json()['chat']['history']['messages'], 'Do not resend an already-started workflow'
        added = False
        manifest['phase'] = 'executing'
        MANIFEST.write_text(json.dumps(manifest, indent=2))
        report = {'browser_upload': manifest['browser_upload'], 'synthetic_only': True,
                  'model': MODEL, 'endpoint': ENDPOINT,
                  'scope': args.scope,
                  'ui_image': json.loads((ROOT / ('workspace-production.json' if production else 'workspace-preview.json')).read_text())['image']}
        if not production:
            report['preview_image'] = report['ui_image']

        def progress(phase):
            print(json.dumps({'phase': phase}, ensure_ascii=False), flush=True)

        def wait_model():
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                snap = ui.snapshot()
                if '已选择：DeepSeek V4 Pro' in snap:
                    return
                time.sleep(0.5)
            raise AssertionError('Available DeepSeek was not selected automatically')

        def send(prompt):
            wait_model()
            ui.browser('fill', ui.control('generic "描述你的研究主题、科学问题或写作任务"'), prompt)
            # Upstream currently exposes this icon-only submit button without
            # an accessible name. Observe its actual DOM before selecting it.
            controls = json.loads(json.loads(ui.browser('eval', 'JSON.stringify(Array.from(document.querySelectorAll("button[type=submit]")).filter(e=>e.getBoundingClientRect().height>0).map(e=>({id:e.id,disabled:e.disabled})))')))
            assert controls == [{'id': 'send-message-button', 'disabled': False}]
            ui.browser('click', '#' + controls[0]['id'])

        def saved_artifact(thread, filename):
            deadline, last_notice = time.monotonic() + 240, 0
            while time.monotonic() < deadline:
                saved = call('GET', '/api/v1/chats/' + thread).json()
                messages = list(saved['chat']['history']['messages'].values())
                for message in messages:
                    if message.get('role') != 'assistant':
                        continue
                    if message.get('error'):
                        raise AssertionError('Synthetic browser chat recorded a generation error')
                    for file in message.get('files', []):
                        if file.get('name') == filename and file.get('workstation', {}).get('project') == manifest['project']:
                            if message.get('done'):
                                return saved, message, file
                if time.monotonic() - last_notice > 20:
                    progress('等待真实回复及文件卡片写入聊天记录')
                    last_notice = time.monotonic()
                time.sleep(1)
            raise AssertionError('No completed, persisted native file card: ' + filename)

        try:
            # Credential never enters shell arguments, browser storage injection,
            # logs or the manifest. Only the reviewed official endpoint is used.
            key = dotenv_values(ROOT / 'state/.env').get('DEEPSEEK_API_KEY')
            assert key, 'Authorized server DeepSeek credential unavailable'
            added = True
            call('POST', '/api/workstation/credentials', json={'model_id': MODEL, 'endpoint_id': 'official', 'api_key': key})
            key = None
            call('PATCH', '/api/workstation/projects/' + manifest['project'], json={'title': TITLE})
            target = base + '/c/' + manifest['thread']
            if ui.browser('get', 'url').strip() != target:
                ui.browser('open', target)
            else:
                ui.browser('reload')
            wait_model()
            report['first_available_model_selected'] = True
            prompt = ('这是仅使用合成文本的网页验收，不进行联网检索。本对话标记 THREAD_A_ONLY_SYNTHETIC，'
                      '标记不要写入任何文件。请实际读取项目中的 probe-input.txt，然后使用文件工具创建 '
                      'browser_probe.md：第一行为“# 网页工作流验收”，空一行，随后原样写入附件的全部文本。'
                      '不要创建其他文件。完成后用一句中文交付该文件。')
            send(prompt)
            first, first_message, first_file = saved_artifact(manifest['thread'], 'browser_probe.md')
            first_data = call('GET', first_file['url']).content
            assert '# 网页工作流验收' in first_data.decode() and PROBE in first_data
            assert b'THREAD_A_ONLY_SYNTHETIC' not in first_data
            assert '/home/ubuntu/' not in first_message.get('content', '')
            ui.wait_for('browser_probe.md 打开文件')
            ui.click('browser_probe.md 打开文件')
            ui.wait_for('heading "网页工作流验收"')
            ui.browser('reload')
            ui.wait_for('heading "网页工作流验收"')
            ui.wait_for('browser_probe.md 打开文件')
            report.update(first_file_card_persisted=True, first_generated_file_rendered=True,
                          first_chat_and_file_survive_reload=True)
            progress('第一条真实对话已交付文件，刷新后聊天卡片与文件仍可打开')
            ui.click('tab "对话列表"')
            ui.click('button "＋ 新增对话"')
            deadline = time.monotonic() + 30
            second_thread = None
            while time.monotonic() < deadline:
                current_url = ui.browser('get', 'url').strip()
                projects = call('GET', '/api/workstation/projects').json()
                project = next(item for item in projects if item['id'] == manifest['project'])
                matches = [thread['id'] for thread in project['threads'] if thread['id'] != manifest['thread']
                           and current_url.endswith('/c/' + thread['id'])]
                if len(matches) == 1:
                    second_thread = matches[0]
                    break
                time.sleep(0.5)
            assert second_thread and len(project['threads']) == 2 and project['title'] == TITLE
            assert call('GET', '/api/workstation/threads/' + second_thread + '/workspace').json()['id'] == manifest['project']
            second_before = call('GET', '/api/v1/chats/' + second_thread).json()
            assert not second_before['chat']['history']['messages']
            manifest['second_thread'] = second_thread
            MANIFEST.write_text(json.dumps(manifest, indent=2))
            second_prompt = ('这是同一项目另一条对话的合成验收，不进行联网检索。请实际读取项目中已有的 '
                             'browser_probe.md，再创建 browser_followup.md：第一行为“# 后续对话验收”，'
                             '空一行后原样写入所读文件中的英文合成文本。不要修改其他文件。用一句中文交付新文件。')
            send(second_prompt)
            second, second_message, second_file = saved_artifact(second_thread, 'browser_followup.md')
            second_data = call('GET', second_file['url']).content
            assert '# 后续对话验收' in second_data.decode() and PROBE in second_data
            assert 'THREAD_A_ONLY_SYNTHETIC' not in json.dumps(second['chat']['history'], ensure_ascii=False)
            assert call('GET', first_file['url']).content == first_data
            ui.wait_for('browser_followup.md 打开文件')
            ui.click('browser_followup.md 打开文件')
            ui.wait_for('heading "后续对话验收"')
            ui.browser('reload')
            ui.wait_for('heading "后续对话验收"')
            ui.wait_for('browser_followup.md 打开文件')
            first_after = call('GET', '/api/v1/chats/' + manifest['thread']).json()
            assert 'THREAD_A_ONLY_SYNTHETIC' in json.dumps(first_after['chat']['history'], ensure_ascii=False)
            assert second_prompt not in json.dumps(first_after['chat']['history'], ensure_ascii=False)
            report.update(second_thread_created_from_ui=True, same_project_files_shared=True,
                          native_message_histories_independent=True, first_file_unchanged=True,
                          second_file_card_persisted_and_rendered=True, second_preview_survives_reload=True,
                          manual_project_name_preserved=True, verified_at=datetime.now(timezone.utc).isoformat())
            manifest['phase'] = 'completed'
            MANIFEST.write_text(json.dumps(manifest, indent=2))
            (ROOT / (prefix + '-verification.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False), flush=True)
        finally:
            if added:
                call('DELETE', '/api/workstation/credentials/deepseek')
                progress('测试账号临时凭据已移除')


if __name__ == '__main__':
    main()
