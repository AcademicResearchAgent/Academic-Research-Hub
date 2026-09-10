"""Check public native file metadata using a disposable synthetic preview upload."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import uuid

ROOT = Path('/home/ubuntu/haudi-hermes')
spec = importlib.util.spec_from_file_location('history_verifier', Path(__file__).with_name('verify-history-browser.py'))
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


def public(value):
    if isinstance(value, list):
        for item in value:
            public(item)
    elif isinstance(value, dict):
        assert 'path' not in value, 'Native metadata returned a physical path'
        for item in value.values():
            public(item)
    elif isinstance(value, str):
        assert '/app/backend/' not in value and '/home/ubuntu/' not in value


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    account = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    name = 'synthetic-metadata-' + uuid.uuid4().hex + '.txt'
    content = b'Synthetic metadata disclosure test only.\n'
    node = None
    with history.client_for(account) as client:
        try:
            response = client.post('/api/v1/files/', params={'process': 'false'},
                                   files={'file': (name, content, 'text/plain')})
            response.raise_for_status()
            uploaded = response.json()
            node = uploaded['id']
            assert uploaded['user_id'] == account['id']
            public(uploaded)
            public(history.get(client, '/api/v1/files/' + node).json())
            listing = history.get(client, '/api/v1/files/').json()
            assert any(item['id'] == node for item in listing['items'])
            public(listing)
            searched = client.get('/api/v1/files/search', params={'filename': name})
            searched.raise_for_status()
            assert any(item['id'] == node for item in searched.json())
            public(searched.json())
            renamed = client.post('/api/v1/files/' + node + '/rename', json={'filename': name.replace('.txt', '-renamed.txt')})
            renamed.raise_for_status()
            public(renamed.json())
            assert history.get(client, '/api/v1/files/' + node + '/content').content == content
        finally:
            if node:
                client.delete('/api/v1/files/' + node).raise_for_status()
    preview = json.loads((ROOT / 'workspace-preview.json').read_text())
    report = {'passed': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
              'preview_image': preview['image'], 'upload_list_search_detail_rename_hide_path': True,
              'original_content_preserved': True, 'synthetic_upload_removed': True,
              'production_changed': False, 'model_called': False}
    (ROOT / 'workspace-native-file-api-verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
