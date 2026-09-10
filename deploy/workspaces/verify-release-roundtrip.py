"""Exercise a real compatible preview rollback and return with new data retained.

Uses dedicated synthetic records created after the fallback checkpoint. This
checks HTTP versions, native messages, account denial and actual file-card UI.
No model is called, and no production container/database is changed.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')
MANIFEST = ROOT / 'workspace-release-roundtrip-probe.json'
TITLE = '发布回退数据验收'
FILENAME = 'rollback-preserve.md'
V1 = '# ROLLBACK_PRESERVE_V1\nSynthetic first version.\n'
V2 = '# ROLLBACK_PRESERVE_V2\nSynthetic edit created after the fallback checkpoint.\n'
USER = 'Synthetic message created after the fallback checkpoint.'
ANSWER = 'Synthetic persisted result. Open the attached file.'
control_path = Path(__file__).with_name('release-control.py')
spec = importlib.util.spec_from_file_location('release_control', control_path)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


@contextmanager
def client_for(fixture):
    with httpx.Client(base_url='http://127.0.0.1:9120', timeout=30, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: fixture[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        yield client


def call(client, method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response


def verify_data(manifest, fixtures):
    prefix = '/api/workstation'
    with client_for(fixtures[0]) as client:
        file_url = prefix + '/files/' + manifest['file']
        versions = call(client, 'GET', file_url + '/versions').json()
        assert {(item['revision'], item['size']) for item in versions} == {(1, len(V1.encode())), (2, len(V2.encode()))}
        for revision, expected in ((1, V1), (2, V2)):
            response = call(client, 'GET', file_url + '/content', params={'revision': revision})
            assert response.text == expected
        assert call(client, 'GET', file_url + '/content').text == V2
        files = call(client, 'GET', prefix + '/projects/' + manifest['project'] + '/files').json()
        assert len(files) == 1 and files[0]['id'] == manifest['file'] and files[0]['version'] == 2
        chat = call(client, 'GET', '/api/v1/chats/' + manifest['thread']).json()['chat']
        messages = chat['history']['messages']
        assert messages[manifest['user_message']]['content'] == USER
        answer = messages[manifest['assistant_message']]
        assert answer['content'] == ANSWER and answer['files'][0]['workstation']['node'] == manifest['file']
    with client_for(fixtures[1]) as client:
        for path in (file_url + '/content', file_url + '/versions', prefix + '/projects/' + manifest['project'] + '/files'):
            assert client.get(path).status_code == 404


def verify_browser():
    spec = importlib.util.spec_from_file_location('ui', Path(__file__).with_name('verify-browser.py'))
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)

    def browser(*args):
        # The established browser daemon belongs to ubuntu; root has a separate
        # context. Never switch to an unrelated root browser or inject a token.
        return subprocess.check_output(['sudo', '-u', 'ubuntu', '-H', 'env',
            'XDG_RUNTIME_DIR=/run/user/1000',
            'PATH=' + str(ROOT / 'runtime/bin') + ':' + str(ROOT / 'runtime/node/bin') + ':/usr/bin:/bin',
            'agent-browser', '--session', 'haudi-workspace-preview', *args],
            text=True, stderr=subprocess.DEVNULL)
    ui.browser = browser
    ui.browser('reload')
    ui.wait_for('button "' + TITLE + '"')
    ui.click('button "' + TITLE + '"')
    ui.wait_for('button "' + FILENAME + ' 打开文件')
    ui.click('button "' + FILENAME + ' 打开文件')
    ui.wait_for('heading "ROLLBACK_PRESERVE_V2"')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fallback-checkpoint', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute-verified', action='store_true')
    mode.add_argument('--verify-prepared', action='store_true', help='Recheck existing synthetic data without creating or switching anything')
    args = parser.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    config = control.configuration('preview')
    fixtures = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())
    if args.verify_prepared:
        assert args.fallback_checkpoint is None
        manifest = json.loads(MANIFEST.read_text())
        assert manifest['phase'] in ('preparing', 'prepared') and manifest['owner'] == fixtures[0]['id']
        assert control.validate(config)['ui']['image'] == manifest['current_image']
        verify_data(manifest, fixtures)
        verify_browser()
        manifest.update(phase='prepared', preflight_verified=True)
        MANIFEST.write_text(json.dumps(manifest, indent=2))
        print(json.dumps({'preflight': 'passed', 'existing_records_only': True, 'browser_card_rendered': True}), flush=True)
        return
    if not args.execute_verified:
        assert not MANIFEST.exists() and args.fallback_checkpoint is not None
        target = args.fallback_checkpoint.resolve()
        assert target.parent == ROOT / 'workspace-release-checkpoints'
        fallback = json.loads(target.read_text())
        current = control.validate(config)
        assert current['ui']['image'] != fallback['ui']['image'], 'Wait for the new preview before preparing'
        assert current['broker'] == fallback['broker'] and current['schemas'] == fallback['schemas']
        fresh = ROOT / 'workspace-release-checkpoints' / ('preview-roundtrip-' + uuid.uuid4().hex + '.json')
        fresh.write_text(json.dumps(current, indent=2))
        with client_for(fixtures[0]) as client:
            created = call(client, 'POST', '/api/workstation/projects', json={'title': TITLE}).json()
            project, thread = created['project']['id'], created['thread']
            file = call(client, 'POST', '/api/workstation/projects/' + project + '/upload',
                        files={'file': (FILENAME, V1.encode(), 'text/markdown')}).json()
            updated = call(client, 'PUT', '/api/workstation/files/' + file['id'] + '/content',
                           json={'content': V2, 'version': 1}).json()
            assert updated['version'] == 2
            user_id, assistant_id = str(uuid.uuid4()), str(uuid.uuid4())
            receipt = {'type': 'file', 'id': file['id'], 'name': FILENAME,
                       'url': '/api/workstation/files/' + file['id'] + '/content',
                       'size': len(V2.encode()), 'content_type': 'text/markdown',
                       'workstation': {'project': project, 'node': file['id'], 'version': 2}}
            messages = {
                user_id: {'id': user_id, 'role': 'user', 'content': USER, 'parentId': None,
                          'childrenIds': [assistant_id], 'timestamp': int(time.time())},
                assistant_id: {'id': assistant_id, 'role': 'assistant', 'content': ANSWER,
                               'parentId': user_id, 'childrenIds': [], 'done': True,
                               'model': 'ws-deepseek-v4-pro', 'timestamp': int(time.time()), 'files': [receipt]}}
            call(client, 'POST', '/api/v1/chats/' + thread, json={'chat': {'title': TITLE,
                 'models': ['ws-deepseek-v4-pro'], 'history': {'messages': messages, 'currentId': assistant_id},
                 'messages': list(messages.values())}})
        manifest = {'phase': 'preparing', 'project': project, 'thread': thread, 'file': file['id'],
                    'owner': fixtures[0]['id'], 'user_message': user_id, 'assistant_message': assistant_id,
                    'fallback_checkpoint': str(target), 'current_checkpoint': str(fresh),
                    'fallback_image': fallback['ui']['image'], 'current_image': current['ui']['image'],
                    'created_after_checkpoint': True, 'model_called': False}
        MANIFEST.write_text(json.dumps(manifest, indent=2))
        verify_data(manifest, fixtures)
        verify_browser()
        manifest.update(phase='prepared', preflight_verified=True)
        MANIFEST.write_text(json.dumps(manifest, indent=2))
        print(json.dumps({'preflight': 'passed', 'two_file_versions': True, 'native_messages_and_card': True,
                          'new_data_created_after_fallback': True, 'production_changed': False}), flush=True)
        return
    assert args.fallback_checkpoint is None
    manifest = json.loads(MANIFEST.read_text())
    assert manifest['phase'] == 'prepared' and manifest.get('preflight_verified') is True and manifest['owner'] == fixtures[0]['id']
    events = []
    for phase, key, expected in (('fallback', 'fallback_checkpoint', manifest['current_image']),
                                 ('restored', 'current_checkpoint', manifest['fallback_image'])):
        manifest['phase'] = 'switching_' + phase
        MANIFEST.write_text(json.dumps(manifest, indent=2))
        print(json.dumps({'phase': manifest['phase']}), flush=True)
        result = subprocess.run([str(ROOT / 'venv/bin/python'), str(control_path), 'switch', '--scope', 'preview',
                                 '--checkpoint', manifest[key], '--expect-image', expected],
                                capture_output=True, text=True, timeout=420)
        if result.returncode:
            raise RuntimeError('Release switch failed; inspect its private release-event record before resuming')
        event = json.loads(result.stdout)
        assert event['phase'] == 'complete' and event['data_restore_performed'] is False
        verify_data(manifest, fixtures)
        verify_browser()
        events.append(event)
        print(json.dumps({'phase': phase + '_verified', 'data_and_browser': True}), flush=True)
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'preview_only': True,
              'from_image': manifest['current_image'], 'fallback_image': manifest['fallback_image'],
              'real_rollback_and_return': True, 'new_file_and_both_versions_retained': True,
              'native_messages_and_card_retained': True, 'foreign_account_denied_after_both_switches': True,
              'browser_file_card_rendered_after_both_switches': True, 'old_database_never_restored': True,
              'production_changed': False, 'model_called': False,
              'release_events': [event['backup'] for event in events]}
    (ROOT / 'workspace-release-roundtrip-verification.json').write_text(json.dumps(report, indent=2))
    manifest['phase'] = 'completed'
    MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
