"""Boot a single-run gateway from a non-secret, reviewed profile seed."""
import os
from pathlib import Path
import shutil
import sys
import yaml

home = Path('/state')
home.mkdir(exist_ok=True)
seed = Path('/opt/profile')
for name in ('skills', 'plugins'):
    shutil.copytree(seed / name, home / name, dirs_exist_ok=True)
shutil.copy2(seed / 'SOUL.md', home / 'SOUL.md')
config = yaml.safe_load((seed / 'config.yaml').read_text())
config['terminal'] = {'backend': 'local', 'cwd': '/workspace', 'timeout': 180,
                      'auto_source_bashrc': False, 'env_passthrough': []}
config['platforms'] = {'api_server': {'enabled': True, 'extra': {
    'host': '0.0.0.0', 'port': 8642, 'key': os.environ['WORKSTATION_RUN_KEY']}}}
config['gateway'] = {'api_server': {'max_concurrent_runs': 1}}
config['memory'] = {'memory_enabled': False, 'user_profile_enabled': False}
config['updates'] = {'auto_update': False}
config['skills']['project_discovery'] = False
config['skills']['external_dirs'] = []
config['skills']['trusted_project_dirs'] = []
config['skills']['inline_shell'] = False
config['plugins']['auto_discover'] = False
(home / 'config.yaml').write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
(home / 'config.yaml').chmod(0o600)
os.environ['API_SERVER_KEY'] = os.environ.pop('WORKSTATION_RUN_KEY')
os.environ['API_SERVER_HOST'] = '0.0.0.0'
os.environ['API_SERVER_PORT'] = '8642'
os.execv(sys.executable, [sys.executable, '-m', 'hermes_cli.main', 'gateway', 'run'])
