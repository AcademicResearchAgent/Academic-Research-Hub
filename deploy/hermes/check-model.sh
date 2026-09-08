set -euo pipefail
cd /home/ubuntu/haudi-hermes/source
export HERMES_HOME=/home/ubuntu/haudi-hermes/state
export PATH=/home/ubuntu/haudi-hermes/runtime/uv-bin:/home/ubuntu/haudi-hermes/runtime/node/bin:/home/ubuntu/haudi-hermes/venv/bin:$PATH
python -u - <<'PY'
from pathlib import Path
from dotenv import dotenv_values
import httpx, yaml
state=Path('/home/ubuntu/haudi-hermes/state')
key=dotenv_values(state/'.env')['DEEPSEEK_API_KEY']
model=yaml.safe_load((state/'config.yaml').read_text())['model']['default']
with httpx.Client(timeout=45) as client:
    result=client.get('https://api.deepseek.com/v1/models',headers={'Authorization':'Bearer '+key})
    print('Model endpoint status:',result.status_code)
    result.raise_for_status()
    models=[entry['id'] for entry in result.json()['data']]
    print('Configured model available:',model in models)
    if model not in models: raise SystemExit('Configured model not available')
PY
hermes chat --help
