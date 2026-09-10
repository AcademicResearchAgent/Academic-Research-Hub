"""Real model/tool/isolated-container/file-receipt test on the preview only."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import time

import httpx
from dotenv import dotenv_values

ROOT = Path('/home/ubuntu/haudi-hermes')
PROBE = b'Synthetic workspace test input. Contains no personal or research data.'
ENDPOINT = 'https://api.deepseek.com/v1'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute-verified', action='store_true', help='Run only after the synthetic-only input/endpoint preflight is reviewed')
    args = parser.parse_args()
    fixture = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    started = time.monotonic()
    added = False
    receipts, text, progress = [], [], []
    with httpx.Client(base_url='http://127.0.0.1:9120', timeout=900, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: fixture[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        response = client.get('/api/models')
        response.raise_for_status()
        assert any(m['id'] == 'ws-deepseek-v4-pro' for m in response.json()['data']), 'Configured workstation model is missing from native model registry'
        catalog = client.get('/api/workstation/catalog').json()
        # The only external target is the already configured official provider.
        # A new empty project avoids sending any pre-existing workspace data.
        endpoint = next(e for e in catalog['providers']['deepseek']['endpoints'] if e['id'] == 'official')
        assert endpoint['url'].rstrip('/') == ENDPOINT
        manifest_path = ROOT / 'workspace-runtime-probe.json'
        if not args.execute_verified:
            response = client.post('/api/workstation/projects', json={'title': '隔离运行合成验收'})
            response.raise_for_status()
            created = response.json()
            response = client.post('/api/workstation/projects/' + created['project']['id'] + '/upload',
                                   files={'file': ('probe-input.txt', PROBE, 'text/plain')})
            response.raise_for_status()
            manifest = {'project': created['project']['id'], 'thread': created['thread'],
                        'input': response.json()['id'], 'sha256': hashlib.sha256(PROBE).hexdigest(),
                        'endpoint': ENDPOINT, 'model': 'ws-deepseek-v4-pro', 'owner': fixture['id']}
            manifest_path.write_text(json.dumps(manifest, indent=2))
        else:
            manifest = json.loads(manifest_path.read_text())
        assert manifest['owner'] == fixture['id'] and manifest['endpoint'] == ENDPOINT
        files = client.get('/api/workstation/projects/' + manifest['project'] + '/files').json()
        assert len(files) == 1 and files[0]['id'] == manifest['input']
        response = client.get('/api/workstation/files/' + manifest['input'] + '/content')
        response.raise_for_status()
        assert response.content == PROBE and hashlib.sha256(response.content).hexdigest() == manifest['sha256']
        assert client.get('/api/workstation/threads/' + manifest['thread'] + '/workspace').json()['id'] == manifest['project']
        if not args.execute_verified:
            print(json.dumps({'preflight': 'passed', 'project_files': 1, 'exact_input': PROBE.decode(),
                              'input_sha256': manifest['sha256'], 'external_endpoint': ENDPOINT,
                              'api_key_read': False, 'external_model_called': False}), flush=True)
            return
        assert not catalog['credentials']['deepseek']['configured'], 'Fixture already has a credential; inspect before running'
        try:
            if not catalog['credentials']['deepseek']['configured']:
                env = dotenv_values(ROOT / 'state/.env')
                key = env.get('DEEPSEEK_API_KEY')
                assert key, 'No existing authorized server test credential'
                added = True
                response = client.post('/api/workstation/credentials', json={
                    'model_id': 'ws-deepseek-v4-pro', 'endpoint_id': 'official', 'api_key': key})
                response.raise_for_status()
            prompt = ('这是合成数据的工作区验收，请实际使用工具完成：先读取当前工作区中的 probe-input.txt，'
                      '再使用 write_file 在工作区根目录创建 runtime_probe.md，内容为“# 隔离运行验收”，'
                      '空一行后原样写入该附件的文本。不要进行额外联网调研。完成后用一句中文说明并交付文件。')
            with client.stream('POST', '/api/chat/completions', json={
                'model': 'ws-deepseek-v4-pro', 'stream': True, 'chat_id': manifest['thread'],
                'messages': [{'role': 'user', 'content': prompt}],
            }) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == '[DONE]':
                        break
                    data = json.loads(raw)
                    if data.get('error'):
                        raise AssertionError('Agent stream returned an error: ' + str(data['error'].get('message', 'unknown')))
                    event = data.get('event', {})
                    if event.get('type') == 'files':
                        receipts.extend(event.get('data', {}).get('files', []))
                    if event.get('type') == 'status':
                        description = event.get('data', {}).get('description', '')
                        if description and description not in progress:
                            progress.append(description)
                            print(json.dumps({'progress': description}, ensure_ascii=False), flush=True)
                    for choice in data.get('choices', []):
                        delta = choice.get('delta', {})
                        if delta.get('content'):
                            text.append(delta['content'])
            artifacts = [r for r in receipts if r.get('name', '').startswith('runtime_probe')]
            assert artifacts, 'No native file receipt for the actual generated artifact'
            receipt = artifacts[-1]
            response = client.get(receipt['url'])
            response.raise_for_status()
            assert '# 隔离运行验收' in response.text and PROBE.decode() in response.text
            assert '/home/ubuntu/' not in ''.join(text)
            report = {'verified_at': datetime.now(timezone.utc).isoformat(),
                      'seconds': round(time.monotonic() - started, 1),
                      'real_model': 'ws-deepseek-v4-pro', 'file_receipt': receipt,
                      'owned_original_read': True, 'generated_file_download_matches': True,
                      'public_answer_hides_host_path': True, 'progress_events': len(progress)}
            (ROOT / 'workspace-runtime-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False), flush=True)
        finally:
            if added:
                response = client.delete('/api/workstation/credentials/deepseek')
                response.raise_for_status()
                print('Temporary fixture credential removed.', flush=True)


if __name__ == '__main__':
    main()
