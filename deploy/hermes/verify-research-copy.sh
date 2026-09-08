set -euo pipefail
export HERMES_HOME=/home/ubuntu/haudi-hermes/state
cd /home/ubuntu/haudi-hermes/source
../venv/bin/python -u - <<'PY'
import json
from pathlib import Path
from types import SimpleNamespace
import httpx
from agent.system_prompt import _identity_parts
root=Path('/home/ubuntu/haudi-hermes')
copy=json.loads((root/'research-copy.json').read_text())
account=json.loads((root/'openwebui/access.json').read_text())
agent=SimpleNamespace(skip_context_files=False,load_soul_identity=True,_session_db=SimpleNamespace(db_path=str(root/'state/state.db')))
parts,loaded=_identity_parts(agent,None)
assert loaded and '科研智能体工作站' in '\n'.join(parts)
assert '实验方案' in '\n'.join(parts) and '不编造' in '\n'.join(parts)
print('Hermes system-prompt identity loader: research identity loaded.')
with httpx.Client(base_url='http://127.0.0.1:9119',timeout=30) as client:
    response=client.get('/health')
    response.raise_for_status()
    response=client.get('/api/config')
    response.raise_for_status()
    config=response.json()
    assert config['name']==copy['app_name']
    assert '<title>'+copy['app_name']+'</title>' in client.get('/').text
    manifest=client.get('/manifest.json').json()
    assert manifest['name']==manifest['short_name']==copy['app_name']
    assert 'Open WebUI' not in client.get('/opensearch.xml').text
    response=client.post('/api/v1/auths/signin',json={key:account[key] for key in ['email','password']})
    response.raise_for_status()
    client.headers['Authorization']='Bearer '+response.json()['token']
    response=client.get('/api/config')
    response.raise_for_status()
    config=response.json()
    assert config['default_prompt_suggestions']==copy['suggestions']
    response=client.get('/api/models')
    response.raise_for_status()
    model=next(m for m in response.json()['data'] if m['id']=='hermes-agent')
    assert model['name']==copy['assistant_name']
    print('Workstation name:',config['name'])
    print('Research task suggestions:',len(config['default_prompt_suggestions']))
    print('Research assistant name and existing account login: OK')
PY
systemctl is-active haudi-hermes-api.service
