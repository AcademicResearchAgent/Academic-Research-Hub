"""Make workspace model discovery independent of the stopped legacy gateway.

The upstream supports explicit model_ids without a live /models request. Keep
the hidden base ID for existing preset ACLs; chat execution remains intercepted
by the isolated workspace bridge. This never starts a shared execution service.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    record = json.loads((ROOT / 'workspace-production.json').read_text())
    assert record['phase'] == 'active'
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', 8642)) != 0
    account = json.loads((ROOT / 'openwebui/access.json').read_text())
    with httpx.Client(base_url='https://42.193.15.167', timeout=60, trust_env=False) as client:
        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            assert response.status_code == 200, 'Model discovery API failed (HTTP ' + str(response.status_code) + ')'
            return response.json()
        auth = call('POST', '/api/v1/auths/signin', json={k: account[k] for k in ('email', 'password')})
        client.headers['Authorization'] = 'Bearer ' + auth['token']
        config = call('GET', '/openai/config')
        urls = config['OPENAI_API_BASE_URLS']
        matches = [i for i, url in enumerate(urls) if url.rstrip('/') == 'http://127.0.0.1:8642/v1']
        assert len(matches) == 1 and config['ENABLE_OPENAI_API']
        index = str(matches[0])
        settings = config.get('OPENAI_API_CONFIGS') or {}
        current = settings.get(index, settings.get(urls[matches[0]], {}))
        assert not current.get('prefix_id') and current.get('enable', True)
        ids = current.get('model_ids') or []
        assert set(ids) <= {'hermes-agent'}, 'Unexpected connection models; inspect before changing'
        backup = ROOT / 'workspace-model-discovery-config-before.json'
        changed = ids != ['hermes-agent']
        if changed:
            assert not backup.exists(), 'Inspect prior configuration backup before repeating a change'
            backup.write_text(json.dumps(config, indent=2))
            config['OPENAI_API_CONFIGS'] = {**settings, index: {**current, 'model_ids': ['hermes-agent']}}
            call('POST', '/openai/config/update', json=config)
        models = call('GET', '/api/models', params={'refresh': 'true'})['data']
        catalog = call('GET', '/api/workstation/catalog')
        visible = {m['id'] for m in models if not m.get('info', {}).get('meta', {}).get('hidden')}
        assert {m['id'] for m in catalog['models']} <= visible
        assert 'hermes-agent' not in visible
        result = {'passed': True, 'static_discovery_configured': True, 'configuration_changed': changed,
                  'legacy_gateway_still_stopped': True, 'visible_catalog_models': len(catalog['models']),
                  'legacy_base_hidden': True, 'existing_acl_preserved': True,
                  'verified_at': datetime.now(timezone.utc).isoformat()}
        (ROOT / 'workspace-model-discovery-verification.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
