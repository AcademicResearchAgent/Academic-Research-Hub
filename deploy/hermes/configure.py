"""Send model settings over SSH stdin without exposing the API key in logs."""
import json
from pathlib import Path
import re
import subprocess
from remote import SSH, OPTIONS

root = Path(__file__).resolve().parents[2]
settings = (root / 'LLM_API.md').read_text(encoding='utf-8-sig')
key = re.search(r'sk-[A-Za-z0-9_-]+', settings).group(0)
model = re.search(r'(?im)^\s*mode[l]?\s*[:=\uff1a]\s*(\S+)', settings).group(1)
payload = {'key': key, 'model': model}
script = '''
import json, os
from pathlib import Path
import yaml
from dotenv import dotenv_values
from hermes_cli.config_defaults import DEFAULT_CONFIG
from copy import deepcopy
p = json.loads(PAYLOAD_LITERAL)
state = Path('/home/ubuntu/haudi-hermes/state')
os.umask(0o077)
state.mkdir(exist_ok=True)
env_file = state / '.env'
existing = dotenv_values(env_file) if env_file.exists() else {}
if existing.get('DEEPSEEK_API_KEY') and existing['DEEPSEEK_API_KEY'] != p['key']:
    raise SystemExit('A different model credential already exists; refusing to overwrite.')
if not existing.get('DEEPSEEK_API_KEY'):
    with env_file.open('a', encoding='utf-8') as stream:
        stream.write('\\nDEEPSEEK_API_KEY=' + p['key'] + '\\n')
env_file.chmod(0o600)
config_path = state/'config.yaml'
config = yaml.safe_load(config_path.read_text()) if config_path.exists() else deepcopy(DEFAULT_CONFIG)
config['model'] = {'default':p['model'], 'provider':'deepseek', 'base_url':'https://api.deepseek.com/v1'}
config.setdefault('terminal', {}).update({'backend':'local','cwd':'/home/ubuntu/haudi-hermes/workspace'})
(state/'config.yaml').write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False),encoding='utf-8')
print('Configured provider=deepseek model=' + p['model'])
'''.replace('PAYLOAD_LITERAL', repr(json.dumps(payload)))
result = subprocess.run(
    [SSH, *OPTIONS, 'haudi-hermes-server',
     'cd /home/ubuntu/haudi-hermes/source && HERMES_HOME=/home/ubuntu/haudi-hermes/state ../venv/bin/python -'],
    input=script.encode('utf-8'),
)
raise SystemExit(result.returncode)
