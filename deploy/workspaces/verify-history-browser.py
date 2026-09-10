"""Verify a proven real historical attachment in the private preview browser.

Credentials and downloaded research remain server-local. Browser actions use
fresh visible controls. Reports contain booleans and release identifiers only.
Run `open`, inspect the visible export menu, then `export` and `finish`.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')
ACCESS = ROOT / 'workspace-history-access.json'
REPORT = ROOT / 'workspace-history-browser-verification.json'
EXPORT = ROOT / 'workspace-history-browser-export.json'
PROBE = ROOT / 'workspace-history-browser-probe.json'
spec = importlib.util.spec_from_file_location('history_ui', Path(__file__).with_name('verify-browser.py'))
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


def browser(*args):
    try:
        return subprocess.check_output(['sudo', '-u', 'ubuntu', '-H', 'env',
            'XDG_RUNTIME_DIR=/run/user/1000',
            'PATH=' + str(ROOT / 'runtime/bin') + ':' + str(ROOT / 'runtime/node/bin') + ':/usr/bin:/bin',
            'agent-browser', '--session', 'haudi-workspace-preview', *args],
            text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        raise RuntimeError('Private history browser action failed; no credential or content logged') from None


ui.browser = browser


def logout():
    if 'button "登录"' in ui.snapshot():
        return
    ui.click('button "用户菜单" [ref=')
    ui.wait_for('button "登出"')
    ui.click('button "登出"')
    ui.wait_for('button "登录"')


def login(account):
    for label, key in (('textbox "本站科研账号', 'email'), ('textbox "密码', 'password')):
        browser('fill', ui.control(label), account[key])
    ui.click('button "登录"')
    ui.wait_for('region "项目列表"')


@contextmanager
def client_for(account):
    with httpx.Client(base_url='http://127.0.0.1:9120', timeout=30, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: account[k] for k in ('email', 'password')})
        response.raise_for_status()
        assert response.json()['id'] == account['id']
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        yield client


def get(client, path):
    response = client.get(path)
    response.raise_for_status()
    return response


def context(release):
    migration = json.loads((ROOT / 'workspace-preview-history-migration.json').read_text())
    assert migration['phase'] == 'complete'
    proofs = json.loads((Path(migration['backup']) / 'migration/legacy-report.json').read_text())['eligible']
    assert len(proofs) == 1 and proofs[0]['owner'] == json.loads(ACCESS.read_text())['id']
    # The historical migration remains valid across later backend releases;
    # verify the current image against the selected immutable source instead
    # of rewriting or replaying the migration record.
    preview = json.loads((ROOT / 'workspace-preview.json').read_text())
    source = ROOT / 'workspace-source-releases' / release
    spec = importlib.util.spec_from_file_location('history_cutover_source', source / 'deploy/workspaces/production-cutover.py')
    cutover = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutover)
    assert cutover.source_directory(release) == source
    cutover.verify_preview_source(source, preview)
    return {**migration, 'migration_source_release': migration['source_release'],
            'source_release': release, 'preview_image': preview['image']}, proofs[0], json.loads(ACCESS.read_text())


def clean_public(document):
    # User-authored content is deliberately excluded; attachment metadata and
    # system/assistant public payloads must not reveal physical storage.
    def walk(value):
        if isinstance(value, dict):
            assert not {'storage_path', 'resolved_path', 'absolute_path'} & value.keys()
            if 'path' in value:
                assert not str(value['path']).startswith(('/app/', '/home/', '/workspace/'))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            assert '/home/ubuntu/' not in value and '/app/backend/' not in value
    walk(document.get('files', []))
    for message in list(document.get('history', {}).get('messages', {}).values()) + document.get('messages', []):
        walk(message.get('files', []))
        if message.get('role') == 'assistant':
            walk(message)


def check_data(proof, account):
    with client_for(account) as client:
        chat = get(client, '/api/v1/chats/' + proof['thread']).json()
        project = get(client, '/api/workstation/threads/' + proof['thread'] + '/workspace').json()
        files = get(client, '/api/workstation/projects/' + project['id'] + '/files').json()
        file = next(item for item in files if item['id'] == proof['node'])
        content = get(client, '/api/workstation/files/' + proof['node'] + '/content?revision=1').content
        assert hashlib.sha256(content).hexdigest() == proof['sha256']
        clean_public(chat['chat'])
        cards = [f for m in chat['chat']['history']['messages'].values() if m.get('role') == 'assistant'
                 for f in m.get('files', []) if f.get('workstation', {}).get('node') == proof['node']]
        assert cards and all(f['workstation']['project'] == project['id'] for f in cards)
        return chat, project, file, content


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('open', 'export', 'finish', 'cleanup'))
    parser.add_argument('--source-release')
    args = parser.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    if args.action == 'cleanup':
        logout()
        login(json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0])
        ACCESS.unlink(missing_ok=True)
        EXPORT.unlink(missing_ok=True)
        print(json.dumps({'private_browser_logged_out': True, 'temporary_credentials_removed': True}))
        return
    assert args.source_release
    migration, proof, account = context(args.source_release)
    chat, project, file, content = check_data(proof, account)
    if args.action == 'open':
        if PROBE.exists():
            previous = json.loads(PROBE.read_text())
            completed = json.loads(REPORT.read_text())
            assert completed['passed'] and previous['preview_image'] == completed['preview_image']
            assert (previous['preview_image'], previous['source_release']) != (migration['preview_image'], migration['source_release']), 'Do not repeat a completed same-release verification'
            retained = PROBE.with_name(PROBE.stem + '-' + previous['preview_image'][7:19] + '-' + previous['source_release'] + '.json')
            assert not retained.exists()
            PROBE.rename(retained)
        browser('reload')
        ui.wait_for('region "项目列表"')
        logout()
        login(account)
        label = 'button "' + project['title'] + '"'
        ui.wait_for(label)
        ui.click(label)
        card = 'button "' + file['name'] + ' 打开文件'
        ui.wait_for(card)
        ui.click(card)
        ui.wait_for('region "文件预览与编辑"')
        # Inspect only DOM-backed rendered text; never read app state or tokens.
        rendered = json.loads(browser('eval', 'JSON.stringify(document.querySelector(\'[aria-label="文件预览与编辑"]\').innerText)'))
        rendered = json.loads(rendered)
        heading = next(line.lstrip('# ').strip() for line in content.decode().splitlines() if line.startswith('# '))
        assert heading in rendered
        assert '/home/ubuntu/' not in rendered and '/app/backend/' not in rendered
        PROBE.write_text(json.dumps({'source_release': migration['source_release'], 'preview_image': migration['preview_image'],
                                   'actual_owner_login': True, 'actual_history_card_rendered': True}, indent=2))
        # This control has been observed in the established preview browser.
        ui.click('button "对话操作" [ref=')
        print(json.dumps({'history_card_rendered': True, 'original_hash_verified': True,
                          'menu_controls': [line.strip() for line in ui.snapshot().splitlines()
                                            if any(word in line for word in ('下载', '导出', '.json', 'menuitem'))]}, ensure_ascii=False))
    elif args.action == 'export':
        probe = json.loads(PROBE.read_text())
        assert probe['actual_history_card_rendered']
        # Observed DOM: preview header also has a Download button. The chat
        # export submenu is the trigger within the open app dropdown.
        trigger = '.app-dropdown-menu button[slot="trigger"]'
        assert browser('get', 'count', trigger).strip() == '1'
        browser('click', trigger)
        print(json.dumps({'export_controls': [line.strip() for line in ui.snapshot().splitlines()
                                             if any(word in line for word in ('.json', '.txt', '.pdf'))]}, ensure_ascii=False))
    else:
        probe = json.loads(PROBE.read_text())
        assert probe['source_release'] == migration['source_release'] and probe['preview_image'] == migration['preview_image']
        assert not EXPORT.exists(), 'Inspect prior export before replacing it'
        # Create a private target writable by the browser's dedicated OS user.
        EXPORT.touch(mode=0o600)
        os.chown(EXPORT, 1000, 1000)
        export_control = ui.control('button "JSON 文件 (.json)"')
        browser('download', export_control, str(EXPORT))
        os.chown(EXPORT, 0, 0)
        os.chmod(EXPORT, 0o600)
        exported = json.loads(EXPORT.read_text())
        assert len(exported) == 1 and exported[0]['id'] == proof['thread']
        clean_public(exported[0]['chat'])
        assert exported[0]['chat']['history'] == chat['chat']['history']
        probe.update(passed=True, verified_at=datetime.now(timezone.utc).isoformat(),
                     actual_browser_json_export=True, original_file_hash_verified=True,
                     assistant_and_attachment_storage_paths_hidden=True,
                     original_user_text_preserved=migration['migration']['original_user_text_preserved'],
                     production_changed=False, model_called=False)
        REPORT.write_text(json.dumps(probe, indent=2))
        logout()
        login(json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0])
        ACCESS.unlink()
        EXPORT.unlink()
        print(json.dumps(probe))


if __name__ == '__main__':
    main()
