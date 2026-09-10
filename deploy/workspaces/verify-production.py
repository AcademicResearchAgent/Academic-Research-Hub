"""Post-cutover checks on the trusted production HTTPS origin.

Research content and credentials stay on the deployment host. Model acceptance
uses a separately marked synthetic account; cleanup removes its credential and
model grant and deletes only that account's synthetic projects and account.
"""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')
BASE = 'https://42.193.15.167'
FIXTURES = ROOT / 'workspace-production-fixtures.json'
REPORT = ROOT / 'workspace-production-verification.json'
MODEL = 'ws-deepseek-v4-pro'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


history = load('production_history_browser', Path(__file__).with_name('verify-history-browser.py'))
ui = history.ui


def call(client, method, path, expected=200, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == expected, 'Production API check failed: ' + method + ' (HTTP ' + str(response.status_code) + ')'
    return response


@contextmanager
def client_for(account):
    with httpx.Client(base_url=BASE, timeout=60, trust_env=False) as client:
        auth = call(client, 'POST', '/api/v1/auths/signin', json={k: account[k] for k in ('email', 'password')}).json()
        if 'id' in account:
            assert auth['id'] == account['id']
        client.headers['Authorization'] = 'Bearer ' + auth['token']
        yield client


def save(**values):
    report = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    report.update(values, updated_at=datetime.now(timezone.utc).isoformat())
    REPORT.write_text(json.dumps(report, indent=2))
    print(json.dumps(values), flush=True)


def login(account):
    for label, key in (('textbox "本站科研账号', 'email'), ('textbox "密码', 'password')):
        history.browser('fill', ui.control(label), account[key])
    ui.click('button "登录"')
    ui.wait_for('button "用户菜单"')
    if 'region "项目列表"' not in ui.snapshot():
        ui.click('button "展开侧边栏"')
    ui.wait_for('region "项目列表"')


def identity_rows(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        return (set(db.execute('SELECT id,email FROM user')), set(db.execute('SELECT id,user_id FROM chat')))


def structural(record, control):
    config = control.configuration('production')
    control.validate(config)
    event = json.loads(Path(record['cutover_event']).read_text())
    assert event['phase'] == 'active' and not event['preview_data_imported']
    backup = Path(event['backup'])
    old_users, old_chats = identity_rows(backup / 'data/webui.db')
    users, chats = identity_rows(config['data'] / 'webui.db')
    assert old_users <= users and old_chats <= chats
    preview_ids = {f['id'] for f in json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())}
    assert not preview_ids.intersection(u[0] for u in users)
    runtime = json.loads(config['broker_record'].read_text())
    cutover = load('production_check_cutover', ROOT / 'workspace-source-releases' / runtime['source_release'] / 'deploy/workspaces/production-cutover.py')
    cutover.assert_legacy_stopped()
    assert control.command('systemctl', 'show', cutover.LEGACY_SERVICE, '--property=UnitFileState', '--value') == 'disabled'
    guard = Path('/etc/systemd/system/haudi-hermes-api.service.d/workstation-workspace-cutover.conf').read_text()
    assert 'ConditionPathExists=!' + str(config['ui_record']) in guard
    assert not control.inspect(record['legacy_container'])['State']['Running']
    with httpx.Client(base_url=BASE, timeout=30, trust_env=False) as client:
        call(client, 'GET', '/health')
        assert call(client, 'GET', '/').headers['content-type'].startswith('text/html')
    with closing(sqlite3.connect((config['workspace'] / 'workspaces.db').as_uri() + '?mode=ro', uri=True)) as db:
        mapping = dict(db.execute('SELECT threads.id,projects.owner FROM threads JOIN projects ON projects.id=threads.project'))
        assert all(mapping.get(thread) == owner for thread, owner in old_chats)
    save(structural_passed=True, target=BASE, production_image=record['image'],
         source_release=runtime['source_release'], original_accounts=len(old_users), original_chats=len(old_chats),
         identities_and_thread_ownership_preserved=True, preview_accounts_not_imported=True,
         trusted_https=True, private_production_mounts=True, legacy_shared_agent_disabled=True,
         migration=event['migration'])


def historical(record):
    account = json.loads(history.ACCESS.read_text())
    event = json.loads(Path(record['cutover_event']).read_text())
    proofs = json.loads((Path(event['backup']) / 'migration/legacy-report.json').read_text())['eligible']
    owned = [p for p in proofs if p['owner'] == account['id']]
    assert owned
    # Reuse the original preview-verified document where possible, with actual
    # production IDs read from production's migration evidence.
    preview_event = json.loads((ROOT / 'workspace-preview-history-migration.json').read_text())
    previous = json.loads((Path(preview_event['backup']) / 'migration/legacy-report.json').read_text())['eligible'][0]
    proof = next(p for p in owned if p['sha256'] == previous['sha256'])
    history.client_for = client_for
    chat, project, file, content = history.check_data(proof, account)
    with client_for(account) as owner, client_for(json.loads((ROOT / 'openwebui/access.json').read_text())) as other:
        for p in owned:
            data = call(owner, 'GET', '/api/workstation/files/' + p['node'] + '/content?revision=1').content
            assert hashlib.sha256(data).hexdigest() == p['sha256']
            call(other, 'GET', '/api/workstation/files/' + p['node'] + '/content', expected=404)
        call(other, 'GET', '/api/workstation/projects/' + project['id'] + '/files', expected=404)
    if history.browser('get', 'url').strip().rstrip('/') != BASE:
        history.browser('open', BASE)
    if 'button "登录"' not in ui.snapshot():
        history.logout()
    # The dedicated preview browser has no production credentials injected.
    ui.wait_for('button "登录"')
    login(account)
    ui.wait_for('button "' + project['title'] + '"')
    ui.click('button "' + project['title'] + '"')
    ui.wait_for(file['name'] + ' 打开文件')
    ui.click(file['name'] + ' 打开文件')
    ui.wait_for('region "文件预览与编辑"')
    rendered = json.loads(json.loads(history.browser('eval', 'JSON.stringify(document.querySelector(\'[aria-label="文件预览与编辑"]\').innerText)')))
    heading = next(line.lstrip('# ').strip() for line in content.decode().splitlines() if line.startswith('# '))
    assert heading in rendered and '/home/ubuntu/' not in rendered
    ui.click('button "对话操作" [ref=')
    trigger = '.app-dropdown-menu button[slot="trigger"]'
    assert history.browser('get', 'count', trigger).strip() == '1'
    history.browser('click', trigger)
    ui.wait_for('button "JSON 文件 (.json)"')
    export = ROOT / 'workspace-production-history-export.json'
    assert not export.exists()
    export.touch(mode=0o600)
    os.chown(export, 1000, 1000)
    try:
        history.browser('download', ui.control('button "JSON 文件 (.json)"'), str(export))
        exported = json.loads(export.read_text())
        assert len(exported) == 1 and exported[0]['id'] == proof['thread']
        history.clean_public(exported[0]['chat'])
        assert exported[0]['chat']['history'] == chat['chat']['history']
    finally:
        export.unlink(missing_ok=True)
        history.logout()
        history.ACCESS.unlink(missing_ok=True)
    save(actual_production_owner_login=True, historical_card_and_right_preview=True,
         historical_hashes_over_https=len(owned), other_account_denied=True,
         actual_production_json_export=True, public_history_paths_hidden=True,
         temporary_history_credentials_removed=True)


def grants(admin, ids, add):
    # Custom models inherit the existing gateway base model's ACL. Both grants
    # are needed by a new synthetic account, as in the preview acceptance setup.
    for model_id in ('hermes-agent', MODEL):
        model = call(admin, 'GET', '/api/v1/models/model', params={'id': model_id}).json()
        entries = [{k: g[k] for k in ('principal_type', 'principal_id', 'permission')}
                   for g in model.get('access_grants', [])
                   if not (g['principal_type'] == 'user' and g['principal_id'] in ids)]
        if add:
            entries.extend({'principal_type': 'user', 'principal_id': i, 'permission': 'read'} for i in ids)
        call(admin, 'POST', '/api/v1/models/model/access/update', json={'id': model_id, 'access_grants': entries})


def fixture():
    assert not FIXTURES.exists(), 'Inspect existing synthetic account before repeating setup'
    with client_for(json.loads((ROOT / 'openwebui/access.json').read_text())) as admin:
        form = {'name': '上线合成验收', 'role': 'user', 'email': 'workspace-production-' + secrets.token_hex(8) + '@example.com',
                'password': secrets.token_urlsafe(32) + '!Aa1'}
        result = call(admin, 'POST', '/api/v1/auths/add', json=form).json()
        account = {**form, 'id': result['id'], 'synthetic_production_acceptance': True}
        FIXTURES.write_text(json.dumps([account]))
        os.chmod(FIXTURES, 0o600)
        grants(admin, {account['id']}, True)
    ui.wait_for('button "登录"')
    login(account)
    save(synthetic_production_account_prepared=True)


def cleanup():
    fixtures = json.loads(FIXTURES.read_text())
    assert all(f.get('synthetic_production_acceptance') is True for f in fixtures)
    history.logout()
    with client_for(json.loads((ROOT / 'openwebui/access.json').read_text())) as admin:
        grants(admin, {f['id'] for f in fixtures}, False)
        for account in fixtures:
            with client_for(account) as client:
                catalog = call(client, 'GET', '/api/workstation/catalog').json()
                assert not catalog['credentials']['deepseek']['configured']
                for project in call(client, 'GET', '/api/workstation/projects').json():
                    call(client, 'DELETE', '/api/workstation/projects/' + project['id'])
            call(admin, 'DELETE', '/api/v1/users/' + account['id'])
    FIXTURES.unlink()
    save(synthetic_account_and_grant_removed=True, temporary_model_key_removed=True,
         browser_logged_out=True, synthetic_projects_soft_deleted=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('structural', 'history', 'fixture', 'cleanup', 'finish'))
    args = parser.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    record = json.loads((ROOT / 'workspace-production.json').read_text())
    assert record['phase'] == 'active'
    runtime = json.loads((ROOT / 'workspace-broker-production.json').read_text())
    control = load('production_verify_control', ROOT / 'workspace-source-releases' / runtime['source_release'] / 'deploy/workspaces/release-control.py')
    if args.action == 'structural':
        structural(record, control)
    elif args.action == 'history':
        historical(record)
    elif args.action == 'fixture':
        fixture()
    elif args.action == 'cleanup':
        cleanup()
    else:
        report = json.loads(REPORT.read_text())
        workflow = json.loads((ROOT / 'workspace-production-browser-workflow-verification.json').read_text())
        assert all(report.get(k) is True for k in ('structural_passed', 'historical_card_and_right_preview',
                   'actual_production_json_export', 'other_account_denied', 'synthetic_account_and_grant_removed',
                   'temporary_model_key_removed', 'browser_logged_out'))
        assert workflow['scope'] == 'production' and workflow['ui_image'] == record['image']
        assert workflow['second_preview_survives_reload'] and workflow['same_project_files_shared']
        control.validate(control.configuration('production'))
        control.assert_no_workers(control.configuration('production'))
        save(passed=True, actual_production_browser_workflow=True, two_real_model_threads=True,
             no_synthetic_worker_left_running=True, preview_data_imported=False)


if __name__ == '__main__':
    main()
