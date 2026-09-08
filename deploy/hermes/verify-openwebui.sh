set -euo pipefail
/home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import json
from pathlib import Path
import httpx
root=Path('/home/ubuntu/haudi-hermes/openwebui')
account=json.loads((root/'access.json').read_text())
with httpx.Client(base_url='http://127.0.0.1:9119',timeout=30) as client:
    r=client.get('/health')
    r.raise_for_status()
    assert r.json()['status'] is True
    print('Primary Open WebUI health: OK')
    r=client.get('/')
    r.raise_for_status()
    assert 'Open WebUI' in r.text
    print('Primary Open WebUI frontend: OK')
    r=client.post('/api/v1/auths/signin',json={k:account[k] for k in ['email','password']})
    r.raise_for_status()
    auth=r.json()
    assert auth['role']=='admin'
    client.headers['Authorization']='Bearer '+auth['token']
    r=client.get('/api/models')
    r.raise_for_status()
    ids=[m['id'] for m in r.json()['data']]
    assert 'hermes-agent' in ids
    print('Administrator login and Hermes connection: OK')
    config=client.get('/api/config').json()
    print('Open WebUI version:',config.get('version','unknown'))
    print('Public signup enabled:',config.get('features',{}).get('enable_signup'))
PY
sudo docker ps --filter name=haudi-openwebui --format '{{.Names}} {{.Status}}'
sudo docker stats --no-stream --format '{{.Name}}: {{.MemUsage}}' haudi-openwebui
systemctl is-active haudi-hermes-api.service
ss -ltn | grep -E ':9119|:8642'
free -h
df -h /
