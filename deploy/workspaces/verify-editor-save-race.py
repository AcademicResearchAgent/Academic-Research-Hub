"""Actual UI save race, with a bounded SQLite lock in the preview only.

No fetch interception, token injection or application state mutation in browser.
An external database transaction delays the real HTTP save; the user then types
more and opens another file before the save commits.
"""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import time

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')
spec = importlib.util.spec_from_file_location('ui', Path(__file__).with_name('verify-browser.py'))
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


def main():
    fixture = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    ui.click('button "▤main.md"')
    ui.wait_for('heading "main.md"')
    if 'textbox "文件源码编辑器"' not in ui.snapshot():
        ui.click('button "源码／编辑"')
    submitted = '# 保存延迟验收\n\n首次提交。\n' + datetime.now(timezone.utc).isoformat() + '\n'
    continued = submitted + '\n保存期间继续输入的内容必须保留。\n'
    ui.browser('fill', ui.control('textbox "文件源码编辑器"'), submitted)
    # The lock process always exits after at most 20 seconds even if the parent
    # dies. The ordinary path releases it immediately after the UI actions.
    code = '''import sqlite3,sys,select
from pathlib import Path
db=sqlite3.connect('/home/ubuntu/haudi-hermes/workspace-preview-store/workspaces.db',timeout=10)
db.execute('BEGIN IMMEDIATE')
print('LOCKED',flush=True)
select.select([sys.stdin],[],[],20)
db.rollback();db.close()
'''
    lock = subprocess.Popen(['sudo', str(ROOT / 'venv/bin/python'), '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert lock.stdout.readline().strip() == 'LOCKED'
        ui.click('button "保存"')
        ui.wait_for('button "保存中…"')
        ui.browser('fill', ui.control('textbox "文件源码编辑器"'), continued)
        ui.click('button "▤原始附件.txt"')
        ui.wait_for('heading "原始附件.txt"')
        assert lock.poll() is None, 'Lock expired before the file switch; retry with faster browser actions'
    finally:
        if lock.poll() is None:
            lock.communicate('\n', timeout=25)
    assert lock.returncode == 0
    with httpx.Client(base_url='http://127.0.0.1:9120', timeout=30, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: fixture[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        for _ in range(30):
            response = client.get('/api/workstation/files/' + fixture['file'] + '/content')
            response.raise_for_status()
            if response.text == submitted:
                break
            time.sleep(.5)
        assert response.text == submitted, 'First HTTP save did not commit the captured input'
        first_version = int(response.headers['X-File-Version'])
        ui.click('button "▤main.md"')
        ui.wait_for('heading "main.md"')
        if 'textbox "文件源码编辑器"' not in ui.snapshot():
            ui.click('button "源码／编辑"')
        ui.wait_for('textbox "文件源码编辑器"')
        assert '保存期间继续输入的内容必须保留。' in ui.snapshot(), 'Late save discarded newer edits to the inactive file'
        ui.click('button "保存"')
        ui.wait_for('button "保存" [disabled,')
        response = client.get('/api/workstation/files/' + fixture['file'] + '/content')
        response.raise_for_status()
        assert response.text == continued and int(response.headers['X-File-Version']) == first_version + 1
        old = client.get('/api/workstation/files/' + fixture['file'] + '/content', params={'revision': first_version})
        assert old.status_code == 200 and old.text == submitted
        report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'actual_http_save_delayed': True,
                  'typed_during_pending_save': True, 'switched_file_before_response': True,
                  'newer_draft_preserved': True, 'second_save_used_new_revision': True,
                  'both_versions_match_inputs': True, 'preview_only': True}
        (ROOT / 'workspace-save-race-verification.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
