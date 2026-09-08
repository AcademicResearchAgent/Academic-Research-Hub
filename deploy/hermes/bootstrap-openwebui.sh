set -euo pipefail
/home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import json, os, secrets, time
from pathlib import Path
import httpx
os.umask(0o077)
root=Path('/home/ubuntu/haudi-hermes/openwebui')
base='http://127.0.0.1:18119'
with httpx.Client(base_url=base,timeout=30) as client:
    for attempt in range(120):
        try:
            if client.get('/health',timeout=3).status_code==200: break
        except httpx.HTTPError:
            pass
        time.sleep(2)
    else: raise SystemExit('Open WebUI health check timed out')
    print('Open WebUI health: OK')
    path=root/'access.json'
    if path.exists():
        account=json.loads(path.read_text())
    else:
        account={'email':'admin@haudi.local','password':secrets.token_urlsafe(24)+'aA1!','name':'Haudi'}
        path.write_text(json.dumps(account,indent=2)+'\n')
        path.chmod(0o600)
    r=client.post('/api/v1/auths/signin',json={k:account[k] for k in ['email','password']})
    if r.status_code!=200:
        r=client.post('/api/v1/auths/signup',json=account)
    if r.status_code!=200:
        print('Account initialization failed:',r.status_code,r.text[:300])
        r.raise_for_status()
    auth=r.json()
    assert auth['role']=='admin', 'Expected deployment administrator role'
    print('Open WebUI administrator login: OK; credentials saved privately on server.')
    client.headers['Authorization']='Bearer '+auth['token']
    r=client.get('/api/models')
    r.raise_for_status()
    models=[m['id'] for m in r.json()['data']]
    print('Open WebUI available models:',models)
    assert 'hermes-agent' in models
    r=client.get('/api/v1/auths/admin/config')
    r.raise_for_status()
    assert not r.json()['ENABLE_SIGNUP'], 'Public signup should be disabled'
    print('Additional account registration disabled: OK')
    (root/'staging-verified').write_text('health, administrator login, Hermes model discovery, signup disabled\n')
PY
