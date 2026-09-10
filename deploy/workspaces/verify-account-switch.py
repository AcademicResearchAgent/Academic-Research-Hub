"""Real logout/login while a synthetic workspace upload waits on a bounded lock.

Only the loopback preview and retained synthetic accounts are used. Credentials
remain on the server; browser interaction uses visible controls without token,
application-state or request interception. Preparation creates dedicated files.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import time

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')
BASE = 'http://127.0.0.1:9120'
MANIFEST = ROOT / 'workspace-account-switch-probe.json'
LABELS = ('账号切换验收 A', '账号切换验收 B')
CONTENTS = ('# ACCOUNT_A_PRIVATE_SYNTHETIC\n', '# ACCOUNT_B_PRIVATE_SYNTHETIC\n')
UPLOAD_NAME = 'account-a-pending-only.txt'
UPLOAD = b'ACCOUNT_A_PENDING_UPLOAD_SYNTHETIC_ONLY\n'
spec = importlib.util.spec_from_file_location('ui', Path(__file__).with_name('verify-browser.py'))
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


def login(fixture):
    ui.wait_for('button "登录"')
    for label, key in (('textbox "本站科研账号', 'email'), ('textbox "密码', 'password')):
        try:
            ui.browser('fill', ui.control(label), fixture[key])
        except subprocess.CalledProcessError:
            raise RuntimeError('Synthetic browser sign-in field could not be filled') from None
    ui.browser('click', ui.control('button "登录"'))
    ui.wait_for('region "项目列表"')


def logout():
    ui.browser('click', ui.control('button "用户菜单" [ref='))
    ui.wait_for('button "登出"')
    ui.browser('click', ui.control('button "登出"'))
    ui.wait_for('button "登录"')
    state = ui.snapshot()
    assert 'region "文件预览与编辑"' not in state
    assert all(label not in state for label in LABELS)


def authenticate(client, fixture):
    response = client.post('/api/v1/auths/signin', json={k: fixture[k] for k in ('email', 'password')})
    response.raise_for_status()
    client.headers['Authorization'] = 'Bearer ' + response.json()['token']


def call(client, method, path, **kwargs):
    response = client.request(method, '/api/workstation' + path, **kwargs)
    response.raise_for_status()
    return response


def open_fixture(index):
    ui.click('button "' + LABELS[index] + '"')
    ui.click('tab "资源管理器"')
    ui.click('button "▤account-' + ('a' if index == 0 else 'b') + '-only.md"')
    ui.wait_for('heading "' + CONTENTS[index].strip('# \n') + '"')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute-verified', action='store_true')
    args = parser.parse_args()
    fixtures = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())
    if not args.execute_verified:
        assert not MANIFEST.exists(), 'Inspect the existing account-switch probe before preparing again'
        entries = []
        with httpx.Client(base_url=BASE, timeout=30, trust_env=False) as client:
            for index, fixture in enumerate(fixtures):
                authenticate(client, fixture)
                project = call(client, 'POST', '/projects', json={'title': LABELS[index]}).json()
                file = call(client, 'POST', '/projects/' + project['project']['id'] + '/upload',
                            files={'file': ('account-' + ('a' if index == 0 else 'b') + '-only.md',
                                            CONTENTS[index].encode(), 'text/markdown')}).json()
                entries.append({'owner': fixture['id'], 'project': project['project']['id'],
                                'thread': project['thread'], 'file': file['id']})
        directory = ROOT / 'workspace-account-switch-input'
        directory.mkdir(exist_ok=True)
        (directory / UPLOAD_NAME).write_bytes(UPLOAD)
        MANIFEST.write_text(json.dumps({'phase': 'prepared', 'entries': entries}, indent=2))
        login(fixtures[1])
        ui.wait_for('button "' + LABELS[1] + '"')
        open_fixture(1)
        logout()
        login(fixtures[0])
        ui.wait_for('button "' + LABELS[0] + '"')
        open_fixture(0)
        print(json.dumps({'preflight': 'passed', 'accounts': 2, 'synthetic_only': True,
                          'b_preview_verified': True, 'a_preview_ready': True}), flush=True)
        return

    manifest = json.loads(MANIFEST.read_text())
    assert manifest['phase'] == 'prepared', 'Do not replay a completed or uncertain upload test'
    a, b = manifest['entries']
    assert [entry['owner'] for entry in (a, b)] == [fixture['id'] for fixture in fixtures]
    upload_name = manifest.get('upload_name', UPLOAD_NAME)
    assert Path(upload_name).name == upload_name
    path = ROOT / 'workspace-account-switch-input' / upload_name
    assert path.read_bytes() == UPLOAD
    ui.wait_for('heading "ACCOUNT_A_PRIVATE_SYNTHETIC"')
    assert 'button "' + LABELS[1] + '"' not in ui.snapshot()
    # Upload is initialized by the real visible button. Its input is inspected
    # before the lock, so a browser failure cannot strand a database transaction.
    ui.click('button "上传"')
    assert ui.browser('get', 'count', '[aria-label="项目列表"] input[type="file"]').strip() == '1'
    lock_code = '''import sqlite3,sys,select
db=sqlite3.connect('/home/ubuntu/haudi-hermes/workspace-preview-store/workspaces.db',timeout=10)
db.execute('BEGIN IMMEDIATE')
print('LOCKED',flush=True)
select.select([sys.stdin],[],[],28)
db.rollback();db.close()
'''
    manifest['phase'] = 'executing'
    MANIFEST.write_text(json.dumps(manifest, indent=2))
    lock = subprocess.Popen(['sudo', str(ROOT / 'venv/bin/python'), '-c', lock_code],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert lock.stdout.readline().strip() == 'LOCKED'
        started = time.monotonic()
        ui.browser('upload', '[aria-label="项目列表"] input[type="file"]', str(path))
        for _ in range(8):
            # The interactive-only snapshot omits static status text.
            state = ui.browser('snapshot')
            if '正在上传：' + upload_name in state:
                break
            time.sleep(.25)
        assert '正在上传：' + upload_name in state
        print(json.dumps({'phase': 'upload_pending', 'seconds': round(time.monotonic() - started, 2)}), flush=True)
        # A blocked SQLite transaction must not block the ASGI event loop.
        with httpx.Client(base_url=BASE, timeout=2, trust_env=False) as health_client:
            health_client.get('/health').raise_for_status()
        assert lock.poll() is None
        logout()
        print(json.dumps({'phase': 'logged_out', 'seconds': round(time.monotonic() - started, 2)}), flush=True)
        login(fixtures[1])
        print(json.dumps({'phase': 'b_logged_in', 'seconds': round(time.monotonic() - started, 2)}), flush=True)
        state = ui.browser('snapshot')
        assert 'ACCOUNT_A_PRIVATE_SYNTHETIC' not in state and upload_name not in state
        assert LABELS[0] not in state and 'region "文件预览与编辑"' not in state
        ui.browser('click', ui.control('button "用户菜单" [ref='))
        ui.wait_for('button "工作区验收 B ')
        assert lock.poll() is None, 'Lock expired before B login; no pending-request claim is valid'
        ui.browser('click', ui.control('button "用户菜单" [ref='))
    finally:
        if lock.poll() is None:
            lock.communicate('\n', timeout=30)
    assert lock.returncode == 0
    ui.wait_for('button "' + LABELS[1] + '"')
    open_fixture(1)
    state = ui.browser('snapshot')
    assert LABELS[0] not in state and 'ACCOUNT_A_PRIVATE_SYNTHETIC' not in state and upload_name not in state

    with httpx.Client(base_url=BASE, timeout=30, trust_env=False) as client:
        authenticate(client, fixtures[0])
        uploaded = []
        for _ in range(20):
            uploaded = [n for n in call(client, 'GET', '/projects/' + a['project'] + '/files').json() if n['name'] == upload_name]
            if uploaded:
                break
            time.sleep(.5)
        assert len(uploaded) == 1
        file = uploaded[0]
        assert call(client, 'GET', '/files/' + file['id'] + '/content').content == UPLOAD
        authenticate(client, fixtures[1])
        for suffix in ('/content', '/versions'):
            assert client.get('/api/workstation/files/' + file['id'] + suffix).status_code == 404
        assert client.get('/api/workstation/projects/' + a['project'] + '/files').status_code == 404
        assert call(client, 'GET', '/files/' + b['file'] + '/content').text == CONTENTS[1]
    ui.browser('reload')
    ui.wait_for('heading "ACCOUNT_B_PRIVATE_SYNTHETIC"')
    state = ui.snapshot()
    assert LABELS[0] not in state and upload_name not in state
    logout()
    login(fixtures[0])
    ui.wait_for('button "' + LABELS[0] + '"')
    open_fixture(0)
    ui.click('button "▤' + upload_name + '"')
    ui.wait_for('textbox "文件源码编辑器"')
    assert UPLOAD.decode().strip() in ui.snapshot()
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'preview_only': True,
              'preview_image': json.loads((ROOT / 'workspace-preview.json').read_text())['image'],
              'real_ui_logout_login': True, 'real_upload_pending_across_account_switch': True,
              'health_responded_while_upload_waited': True,
              'login_page_clears_preview': True, 'b_page_does_not_show_a_files_or_status': True,
              'late_upload_owned_by_a': True, 'foreign_content_versions_project_denied': True,
              'b_preview_survives_reload': True, 'a_can_reopen_completed_upload_after_login': True,
              'scope': 'Real full-page sign-out/login with a delayed upload; not an in-place store-reset simulation.'}
    (ROOT / 'workspace-account-switch-verification.json').write_text(json.dumps(report, indent=2))
    manifest['phase'] = 'completed'
    MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
