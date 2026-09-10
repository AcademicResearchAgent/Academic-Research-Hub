"""Real HTTP acceptance on the loopback preview, using two synthetic accounts.

Credentials stay on the server. This script refuses to target production; it
never reads another account's chats or prints tokens/passwords.
"""
import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import secrets
import zipfile

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')
BASE = 'http://127.0.0.1:9120'


def call(client, method, path, expected=200, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.status_code != expected:
        raise AssertionError(f'{method} {path}: expected {expected}, received {response.status_code}')
    return response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--keep-fixtures', action='store_true', help='Retain synthetic preview accounts for subsequent browser acceptance')
    args = parser.parse_args()
    fixture_path = ROOT / 'workspace-preview-fixtures.json'
    if args.keep_fixtures and fixture_path.exists():
        raise RuntimeError('Existing fixtures must be inspected before creating another set')
    account = json.loads((ROOT / 'openwebui/access.json').read_text())
    fixtures, clients, checks = [], [], []
    with httpx.Client(base_url=BASE, timeout=60, trust_env=False) as admin:
        auth = call(admin, 'POST', '/api/v1/auths/signin', json={k: account[k] for k in ('email', 'password')}).json()
        admin.headers['Authorization'] = 'Bearer ' + auth['token']
        try:
            for label in ('A', 'B'):
                form = {'name': '工作区验收 ' + label, 'role': 'user',
                        'email': 'workspace-' + secrets.token_hex(8) + '@example.com',
                        'password': secrets.token_urlsafe(32) + '!Aa1'}
                auth = call(admin, 'POST', '/api/v1/auths/add', json=form).json()
                fixtures.append({**form, 'id': auth['id']})
                clients.append(httpx.Client(base_url=BASE, timeout=60, trust_env=False,
                                            headers={'Authorization': 'Bearer ' + auth['token']}))
            a, b = clients
            prefix = '/api/workstation'
            make = lambda c, title, project=None: call(c, 'POST', prefix + '/projects', json={'title': title, 'project': project}).json()
            first = make(a, '科研文件验收')
            project, thread = first['project']['id'], first['thread']
            second = make(a, '论文写作', project)
            other = make(a, '独立项目')
            foreign = make(b, '另一个账号的项目')
            # Empty provisioning records are intentionally hidden after the
            # draft UX update. Give list/ACL fixtures actual file content.
            for target in (project, other['project']['id']):
                call(a, 'POST', prefix + '/projects/' + target + '/files',
                     json={'name': 'navigation-fixture.txt', 'content': 'Synthetic navigation fixture'})
            listing = call(a, 'GET', prefix + '/projects').json()
            assert len(listing) == 2
            assert len(next(p for p in listing if p['id'] == project)['threads']) == 2
            assert call(a, 'GET', prefix + '/threads/' + second['thread'] + '/workspace').json()['id'] == project
            checks.append('one_workspace_multiple_threads')
            file = call(a, 'POST', prefix + '/projects/' + project + '/upload',
                        files={'file': ('综述.md', '# 科研综述\n\n合成验收材料。'.encode(), 'text/markdown')}).json()
            file_url = prefix + '/files/' + file['id']
            content = call(a, 'GET', file_url + '/content')
            assert '科研综述' in content.text
            assert content.headers['x-content-type-options'] == 'nosniff'
            assert 'sandbox' in content.headers['content-security-policy']
            assert 'filename*=' in content.headers['content-disposition']
            for method, path, body in (
                ('GET', '/projects/' + project + '/files', None),
                ('GET', '/threads/' + thread + '/workspace', None),
                ('GET', '/files/' + file['id'] + '/content', None),
                ('GET', '/files/' + file['id'] + '/versions', None),
                ('PUT', '/files/' + file['id'] + '/content', {'content': 'unauthorized', 'version': 1}),
                ('PATCH', '/files/' + file['id'], {'name': 'stolen.md'}),
                ('DELETE', '/files/' + file['id'], None),
            ):
                call(b, method, prefix + path, expected=404, **({'json': body} if body is not None else {}))
            assert file['id'] not in {n['id'] for n in call(a, 'GET', prefix + '/projects/' + other['project']['id'] + '/files').json()}
            checks.append('authenticated_file_acl_and_thread_ownership')
            updated = call(a, 'PUT', file_url + '/content', json={'content': '# 已编辑\n保留第一版', 'version': 1}).json()
            assert updated['version'] == 2
            call(a, 'PUT', file_url + '/content', expected=409, json={'content': 'stale', 'version': 1})
            assert '科研综述' in call(a, 'GET', file_url + '/content?revision=1').text
            folder = call(a, 'POST', prefix + '/projects/' + project + '/files', json={'name': '论文', 'directory': True}).json()
            call(a, 'PATCH', file_url, json={'name': 'main.md', 'parent': folder['id']})
            assert '已编辑' in call(a, 'GET', file_url + '/content').text
            assert '论文/main.md' in [n['path'] for n in call(a, 'GET', prefix + '/projects/' + project + '/files').json()]
            foreign_folder = call(b, 'POST', prefix + '/projects/' + foreign['project']['id'] + '/files', json={'name': '私有', 'directory': True}).json()
            call(a, 'PATCH', file_url, expected=404, json={'name': 'escape', 'parent': foreign_folder['id']})
            checks.append('version_conflict_history_and_stable_file_reference')
            native = call(a, 'POST', '/api/v1/files/?process=false', files={'file': ('原始附件.txt', b'Original uploaded source', 'text/plain')}).json()
            imported = call(a, 'POST', prefix + '/projects/' + project + '/import', json={'file_id': native['id'], 'thread': thread}).json()
            repeated = call(a, 'POST', prefix + '/projects/' + project + '/import', json={'file_id': native['id'], 'thread': thread}).json()
            assert repeated['id'] == imported['id']
            assert call(a, 'GET', prefix + '/files/' + imported['id'] + '/content').content == b'Original uploaded source'
            call(b, 'POST', prefix + '/projects/' + foreign['project']['id'] + '/import', expected=404, json={'file_id': native['id']})
            checks.append('native_upload_import_is_owned_and_idempotent')
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('main.tex', '\\documentclass{article}\n\\begin{document}Synthetic test\\end{document}')
                z.writestr('references.bib', '@article{synthetic,title={Synthetic fixture}}')
            package = call(a, 'POST', prefix + '/projects/' + project + '/upload', files={'file': ('paper.zip', archive.getvalue(), 'application/zip')}).json()
            call(a, 'POST', prefix + '/files/' + package['id'] + '/extract')
            assert 'paper/main.tex' in [n['path'] for n in call(a, 'GET', prefix + '/projects/' + project + '/files').json()]
            checks.append('latex_archive_import_and_explicit_extraction')
            call(a, 'PATCH', prefix + '/projects/' + project, json={'title': '固定课题名'})
            call(a, 'PATCH', prefix + '/threads/' + thread, json={'title': '首条对话新标题'})
            assert next(p for p in call(a, 'GET', prefix + '/projects').json() if p['id'] == project)['title'] == '固定课题名'
            call(a, 'DELETE', prefix + '/threads/' + thread)
            assert call(a, 'GET', file_url + '/content').status_code == 200
            call(a, 'DELETE', prefix + '/projects/' + project)
            call(a, 'GET', file_url + '/content', expected=404)
            call(a, 'POST', prefix + '/projects/' + project + '/restore')
            assert '已编辑' in call(a, 'GET', file_url + '/content').text
            checks.append('manual_title_thread_deletion_and_project_recovery')
            fixtures[0].update({'project': project, 'thread': second['thread'], 'file': file['id']})
            if args.keep_fixtures:
                fd = os.open(fixture_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as output:
                    json.dump(fixtures, output)
            report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'target': BASE, 'checks': checks,
                      'scope': 'Real HTTP and native user/file storage; execution isolation and browser rendering require separate checks.'}
            (ROOT / 'workspace-api-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False), flush=True)
        finally:
            for client in clients:
                client.close()
            if not args.keep_fixtures or not fixture_path.exists():
                for fixture in fixtures:
                    call(admin, 'DELETE', '/api/v1/users/' + fixture['id'])


if __name__ == '__main__':
    main()
