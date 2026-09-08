set -euo pipefail
echo 'Hermes service:'
sudo systemctl is-active haudi-hermes-api.service
/home/ubuntu/haudi-hermes/venv/bin/python - <<'PY'
import json, subprocess, urllib.request
from pathlib import Path
import yaml
from dotenv import dotenv_values
root=Path('/home/ubuntu/haudi-hermes')
config=yaml.safe_load((root/'state/config.yaml').read_text())
model=config.get('model',{})
print('Model:',json.dumps({k:model.get(k) for k in ('default','provider','base_url')}))
env=dotenv_values(root/'state/.env')
print('DeepSeek key in state config:',bool(env.get('DEEPSEEK_API_KEY')))
pid=subprocess.check_output(['systemctl','show','haudi-hermes-api.service','--property=MainPID','--value'],text=True).strip()
procenv=Path('/proc/'+pid+'/environ').read_bytes().split(b'\0')
print('DeepSeek key in process environment:',any(x.startswith(b'DEEPSEEK_API_KEY=') and x.split(b'=',1)[1] for x in procenv))
for port in (9119,8642):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=10) as r:
        print(f'Port {port} health HTTP:',r.status)
logs=subprocess.check_output(['sudo','journalctl','-u','haudi-hermes-api.service','-n','500','--no-pager','-o','cat'],text=True)
patterns=['DEEPSEEK_API_KEY','No API key','API key not','Missing API','AuthenticationError','Unauthorized','401','insufficient','RateLimitError','ConnectionError','timed out']
print('Recent log diagnostic markers:',json.dumps({s:logs.lower().count(s.lower()) for s in patterns if s.lower() in logs.lower()}))
PY
