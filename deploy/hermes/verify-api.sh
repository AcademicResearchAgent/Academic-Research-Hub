set -euo pipefail
/home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
from dotenv import dotenv_values
import httpx
key=dotenv_values('/home/ubuntu/haudi-hermes/state/.env')['API_SERVER_KEY']
with httpx.Client(timeout=20) as client:
    r=client.get('http://127.0.0.1:8642/health')
    print('Hermes API health:',r.status_code)
    r.raise_for_status()
    r=client.get('http://127.0.0.1:8642/v1/models',headers={'Authorization':'Bearer '+key})
    print('Hermes model list:',r.status_code)
    r.raise_for_status()
    print('Models:',[model['id'] for model in r.json()['data']])
    assert client.get('http://127.0.0.1:8642/v1/models').status_code==401
    print('Unauthenticated model access rejected: OK')
PY
