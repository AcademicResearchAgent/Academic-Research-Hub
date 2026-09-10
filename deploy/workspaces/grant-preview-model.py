"""Grant/remove only synthetic preview users' read access to the tested model.

The existing installation explicitly grants models to named research accounts;
new test accounts must follow that same ACL path. Never target production.
"""
import argparse
import json
from pathlib import Path

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    fixtures = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())
    ids = {f['id'] for f in fixtures}
    account = json.loads((ROOT / 'openwebui/access.json').read_text())
    with httpx.Client(base_url='http://127.0.0.1:9120', timeout=30, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: account[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        for model in ('hermes-agent', 'ws-deepseek-v4-pro'):
            response = client.get('/api/v1/models/model', params={'id': model})
            response.raise_for_status()
            grants = [{k: g[k] for k in ('principal_type', 'principal_id', 'permission')}
                      for g in response.json().get('access_grants', [])]
            grants = [g for g in grants if not (g['principal_type'] == 'user' and g['principal_id'] in ids)]
            if not args.remove:
                grants += [{'principal_type': 'user', 'principal_id': user_id, 'permission': 'read'} for user_id in sorted(ids)]
            response = client.post('/api/v1/models/model/access/update', json={'id': model, 'access_grants': grants})
            response.raise_for_status()
        print(json.dumps({'scope': 'preview_only', 'synthetic_accounts': len(ids), 'model_access': 'removed' if args.remove else 'read', 'existing_grants_preserved': True}))


if __name__ == '__main__':
    main()
