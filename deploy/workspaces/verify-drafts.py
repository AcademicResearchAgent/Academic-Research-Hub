"""API and browser acceptance for lazy project creation, using synthetic users."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import secrets
import time
import uuid

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')
BASE = ''
FIXTURES = None
REPORT = None
MODEL = 'ws-deepseek-v4-pro'
PROBE = b'Synthetic draft upload. DRAFT_FILE_MARKER.'


def call(client, method, path, status=200, **kwargs):
    result = client.request(method, path, **kwargs)
    assert result.status_code == status, 'Draft API HTTP ' + str(result.status_code) + ' (expected ' + str(status) + ')'
    return result


@contextmanager
def client_for(account):
    with httpx.Client(base_url=BASE, timeout=60, trust_env=False) as client:
        auth = call(client, 'POST', '/api/v1/auths/signin', json={k: account[k] for k in ('email', 'password')}).json()
        client.headers['Authorization'] = 'Bearer ' + auth['token']
        yield client


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


history = module('draft_browser', 'verify-history-browser.py')
ui = history.ui


def record(**values):
    report = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    report.update(values, verified_at=datetime.now(timezone.utc).isoformat(), target=BASE)
    REPORT.write_text(json.dumps(report, indent=2))
    print(json.dumps(values), flush=True)


def setup():
    assert not FIXTURES.exists()
    accounts = []
    with client_for(json.loads((ROOT / 'openwebui/access.json').read_text())) as admin:
        for label in ('A', 'B'):
            form = {'name': '草稿合成验收 ' + label, 'role': 'user', 'email': 'draft-' + secrets.token_hex(8) + '@example.com',
                    'password': secrets.token_urlsafe(32) + '!Aa1'}
            auth = call(admin, 'POST', '/api/v1/auths/add', json=form).json()
            accounts.append({**form, 'id': auth['id'], 'synthetic_draft_acceptance': True})
            FIXTURES.write_text(json.dumps(accounts))
        production = module('draft_grants', 'verify-production.py')
        production.grants(admin, {a['id'] for a in accounts}, True)
        config = call(admin, 'GET', '/openai/config').json()
        matches = [i for i, url in enumerate(config['OPENAI_API_BASE_URLS']) if url.rstrip('/') == 'http://127.0.0.1:8642/v1']
        assert len(matches) == 1
        index = str(matches[0])
        settings = config.get('OPENAI_API_CONFIGS') or {}
        entry = settings.get(index, {})
        if entry.get('model_ids') != ['hermes-agent']:
            assert BASE.startswith('http://127.0.0.1:9120'), 'Production static discovery must already be configured'
            (ROOT / 'workspace-draft-preview-model-config-before.json').write_text(json.dumps(config))
            config['OPENAI_API_CONFIGS'] = {**settings, index: {**entry, 'model_ids': ['hermes-agent']}}
            call(admin, 'POST', '/openai/config/update', json=config)
    with client_for(accounts[0]) as a, client_for(accounts[1]) as b:
        empty = '/api/workstation/drafts/' + str(uuid.uuid4()) + '/commit'
        call(a, 'POST', empty, status=400, json={})
        assert call(a, 'GET', '/api/workstation/projects').json() == []
        blank = call(a, 'POST', '/api/workstation/projects', json={'title': '旧的空白项目'}).json()
        assert call(a, 'GET', '/api/workstation/projects').json() == []
        upload = call(a, 'POST', '/api/v1/files/?process=false', files={'file': ('draft-api.txt', PROBE, 'text/plain')}).json()
        foreign = '/api/workstation/drafts/' + str(uuid.uuid4()) + '/commit'
        call(b, 'POST', foreign, status=404, json={'file_ids': [upload['id']]})
        target = '/api/workstation/drafts/' + str(uuid.uuid4()) + '/commit'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: call(a, 'POST', target, json={'file_ids': [upload['id']]}).json(), range(2)))
        assert results[0]['thread'] == results[1]['thread'] and results[0]['project']['id'] == results[1]['project']['id']
        project = results[0]['project']['id']
        files = call(a, 'GET', '/api/workstation/projects/' + project + '/files').json()
        assert len(files) == 1 and call(a, 'GET', '/api/workstation/files/' + files[0]['id'] + '/content').content == PROBE
        call(b, 'POST', foreign, status=404, json={'project': project, 'file_ids': [upload['id']]})
        message_id = str(uuid.uuid4())
        document = {'history': {'messages': {message_id: {'id': message_id, 'role': 'user', 'content': '合成首次输入', 'childrenIds': [], 'parentId': None}}, 'currentId': message_id}}
        second = call(a, 'POST', '/api/workstation/drafts/' + str(uuid.uuid4()) + '/commit', json={'project': project, 'chat': document}).json()
        assert second['project']['id'] == project
        native = call(a, 'GET', '/api/v1/chats/' + second['thread']).json()
        assert native['chat']['history'] == document['history']
        assert len(call(a, 'GET', '/api/workstation/projects').json()) == 1
        assert call(b, 'GET', '/api/workstation/projects').json() == []
    record(api_passed=True, empty_commit_rejected=True, old_empty_project_hidden=True,
           concurrent_commit_idempotent=True, foreign_files_and_projects_denied=True,
           upload_original_preserved=True, first_message_persisted=True, existing_project_shared=True)


def open_browser():
    accounts = json.loads(FIXTURES.read_text())
    if not history.browser('get', 'url').strip().startswith(BASE):
        history.browser('open', BASE)
    # This is the existing agent-owned test browser, not a user's tab.
    for _ in range(40):
        snapshot = ui.snapshot()
        if 'button "登录"' in snapshot or 'button "用户菜单"' in snapshot:
            break
        time.sleep(.5)
    if 'button "登录"' not in ui.snapshot():
        history.logout()
    for label, key in (('textbox "本站科研账号', 'email'), ('textbox "密码', 'password')):
        history.browser('fill', ui.control(label), accounts[1][key])
    ui.click('button "登录"')
    ui.wait_for('button "用户菜单"')
    if 'region "项目列表"' not in ui.snapshot():
        ui.click('button "展开侧边栏"')
    ui.wait_for('region "项目列表"')
    print(ui.snapshot(), flush=True)
    print(history.browser('eval', 'JSON.stringify(Array.from(document.querySelectorAll("input[type=file]")).map(e=>({id:e.id,multiple:e.multiple,accept:e.accept})))'), flush=True)


def blank_browser():
    b = json.loads(FIXTURES.read_text())[1]
    with client_for(b) as client:
        for _ in range(4):
            ui.click('button "新建项目"')
            ui.wait_for('generic "描述你的研究主题、科学问题或写作任务"')
        history.browser('fill', ui.control('generic "描述你的研究主题、科学问题或写作任务"'), '这是一份尚未发送的合成草稿')
        assert call(client, 'GET', '/api/workstation/projects').json() == []
        history.browser('reload')
        ui.wait_for('generic "描述你的研究主题、科学问题或写作任务"')
        assert call(client, 'GET', '/api/workstation/projects').json() == []
        history.browser('fill', ui.control('generic "描述你的研究主题、科学问题或写作任务"'), '')
    record(repeated_new_clicks_create_nothing=True, unsent_text_creates_nothing=True, blank_reload_creates_nothing=True)
    print(history.browser('eval', 'JSON.stringify(Array.from(document.querySelectorAll("input[type=file]")).map(e=>({id:e.id,multiple:e.multiple,accept:e.accept})))'), flush=True)


def upload_browser():
    b = json.loads(FIXTURES.read_text())[1]
    # Selector must match the actual file input observed by open/blank actions.
    selector = 'input[type="file"][hidden][multiple]'
    assert history.browser('get', 'count', selector).strip() == '1'
    source = ROOT / 'workspace-draft-browser-input.txt'
    source.write_bytes(PROBE)
    os.chown(source, 1000, 1000)
    history.browser('upload', selector, str(source))
    with client_for(b) as client:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            projects = call(client, 'GET', '/api/workstation/projects').json()
            if projects:
                break
            time.sleep(1)
        assert len(projects) == 1 and len(projects[0]['threads']) == 1
        project = projects[0]
        files = call(client, 'GET', '/api/workstation/projects/' + project['id'] + '/files').json()
        assert len(files) == 1
        assert call(client, 'GET', '/api/workstation/files/' + files[0]['id'] + '/content').content == PROBE
        ui.wait_for('tab "资源管理器"')
        assert ('link "' + project['title'] + '"') not in ui.snapshot()
        ui.click('tab "资源管理器"')
        ui.wait_for('button "▤' + source.name + '"')
        ui.click('button "▤' + source.name + '"')
        ui.wait_for('region "文件预览与编辑"')
        assert '上传研究资料，或让科研助手生成文件。' not in history.browser('snapshot')
        ui.click('button "新建项目"')
        ui.wait_for('generic "描述你的研究主题、科学问题或写作任务"')
        time.sleep(2)
        assert len(call(client, 'GET', '/api/workstation/projects').json()) == 1
        assert 'region "文件预览与编辑"' not in ui.snapshot()
        native = call(client, 'GET', '/api/v1/chats/' + project['threads'][0]['id']).json()
        assert not native['chat']['history']['messages']
        report = {'browser_upload_without_message_creates_one_project': True, 'single_thread_title_not_duplicated': True,
                  'empty_file_hint_removed': True, 'new_draft_does_not_reimport_previous_attachment': True,
                  'file_only_project_preserved': True}
        record(**report)


def messages_browser():
    b = json.loads(FIXTURES.read_text())[1]
    assert not json.loads(REPORT.read_text()).get('message_started'), 'Inspect an already-started browser message; do not resend'
    with client_for(b) as client:
        catalog = call(client, 'GET', '/api/workstation/catalog').json()
        assert not catalog['credentials']['deepseek']['configured']
        official = next(e for e in catalog['providers']['deepseek']['endpoints'] if e['id'] == 'official')
        assert official['url'].rstrip('/') == 'https://api.deepseek.com/v1'
        assert len(call(client, 'GET', '/api/workstation/projects').json()) == 1
        from dotenv import dotenv_values
        key = dotenv_values(ROOT / 'state/.env')['DEEPSEEK_API_KEY']
        try:
            call(client, 'POST', '/api/workstation/credentials', json={'model_id': MODEL, 'endpoint_id': 'official', 'api_key': key})
            key = None
            history.browser('reload')
            ui.wait_for('已选择：DeepSeek V4 Pro')

            def send(prompt):
                history.browser('fill', ui.control('generic "描述你的研究主题、科学问题或写作任务"'), prompt)
                assert history.browser('get', 'count', '#send-message-button').strip() == '1'
                history.browser('click', '#send-message-button')

            def completed(thread_count, marker):
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    projects = call(client, 'GET', '/api/workstation/projects').json()
                    if len(projects) == 2:
                        project = next(p for p in projects if p['title'] != 'workspace-draft-browser-input.txt')
                        if len(project['threads']) == thread_count:
                            thread = project['threads'][-1]['id']
                            for entry in project['threads']:
                                native = call(client, 'GET', '/api/v1/chats/' + entry['id']).json()
                                messages = native['chat']['history']['messages'].values()
                                if any(m.get('role') == 'assistant' and m.get('done') and marker in m.get('content', '') for m in messages):
                                    assert not native['chat'].get('files')
                                    return project, entry['id']
                    time.sleep(1)
                raise AssertionError('No completed reply from the newly promoted draft')

            record(message_started=True)
            send('这是纯合成界面验收，不调用工具，不读文件。只回复 DRAFT_TEXT_REPLY_OK。')
            project, first = completed(1, 'DRAFT_TEXT_REPLY_OK')
            record(first_sent_message_creates_exactly_one_project=True, actual_model_reply=True,
                   prior_attachment_not_in_new_chat=True)
            ui.click('tab "对话列表"')
            ui.click('button "＋ 新增对话"')
            ui.wait_for('generic "描述你的研究主题、科学问题或写作任务"')
            assert len(next(p for p in call(client, 'GET', '/api/workstation/projects').json() if p['id'] == project['id'])['threads']) == 1
            ui.wait_for('已选择：DeepSeek V4 Pro')
            send('这是另一条纯合成对话，不调用工具，不读文件。只回复 DRAFT_SECOND_REPLY_OK。')
            second_project, second = completed(2, 'DRAFT_SECOND_REPLY_OK')
            assert second_project['id'] == project['id'] and second != first
            record(add_thread_stays_draft_until_send=True, second_message_keeps_same_project=True)
        finally:
            call(client, 'DELETE', '/api/workstation/credentials/deepseek')
            record(temporary_model_key_removed=True)


def cleanup():
    import sqlite3
    from contextlib import closing
    accounts = json.loads(FIXTURES.read_text())
    assert all(a.get('synthetic_draft_acceptance') for a in accounts)
    history.logout()
    with client_for(json.loads((ROOT / 'openwebui/access.json').read_text())) as admin:
        module('draft_cleanup_grants', 'verify-production.py').grants(admin, {a['id'] for a in accounts}, False)
        database = ROOT / ('workspace-preview-store' if ':9120' in BASE else 'workspace-production-store') / 'workspaces.db'
        for account in accounts:
            with client_for(account) as client:
                assert not call(client, 'GET', '/api/workstation/catalog').json()['credentials']['deepseek']['configured']
                with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
                    ids = [row[0] for row in db.execute('SELECT id FROM projects WHERE owner=? AND deleted=0', (account['id'],))]
                for project in ids:
                    call(client, 'DELETE', '/api/workstation/projects/' + project)
            call(admin, 'DELETE', '/api/v1/users/' + account['id'])
    FIXTURES.unlink()
    record(synthetic_accounts_and_grants_removed=True, browser_logged_out=True)
    report = json.loads(REPORT.read_text())
    required = ['api_passed', 'repeated_new_clicks_create_nothing', 'unsent_text_creates_nothing',
                'browser_upload_without_message_creates_one_project', 'single_thread_title_not_duplicated',
                'empty_file_hint_removed', 'new_draft_does_not_reimport_previous_attachment',
                'first_sent_message_creates_exactly_one_project', 'actual_model_reply',
                'add_thread_stays_draft_until_send', 'second_message_keeps_same_project', 'temporary_model_key_removed']
    assert all(report.get(k) is True for k in required)
    ui_record = json.loads((ROOT / ('workspace-preview.json' if ':9120' in BASE else 'workspace-production.json')).read_text())
    record(passed=True, image=ui_record['image'])


def main():
    global BASE, FIXTURES, REPORT
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('api', 'open', 'blank', 'upload', 'messages', 'cleanup'))
    parser.add_argument('--scope', choices=('preview', 'production'), default='preview')
    args = parser.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    BASE = 'http://127.0.0.1:9120' if args.scope == 'preview' else 'https://42.193.15.167'
    FIXTURES = ROOT / ('workspace-draft-' + args.scope + '-fixtures.json')
    REPORT = ROOT / ('workspace-draft-' + args.scope + '-verification.json')
    {'api': setup, 'open': open_browser, 'blank': blank_browser, 'upload': upload_browser,
     'messages': messages_browser, 'cleanup': cleanup}[args.action]()


if __name__ == '__main__':
    main()
