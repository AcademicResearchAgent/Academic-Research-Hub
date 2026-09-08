set -euo pipefail
cd /home/ubuntu/haudi-hermes/source
export HERMES_HOME=/home/ubuntu/haudi-hermes/state
../venv/bin/python - <<'PY'
import os
from pathlib import Path
import yaml
from copy import deepcopy
from hermes_cli.config_defaults import DEFAULT_CONFIG
os.umask(0o077)
path=Path('/home/ubuntu/haudi-hermes/state/config.yaml')
config=yaml.safe_load(path.read_text()) if path.exists() else deepcopy(DEFAULT_CONFIG)
config['model']={'default':'deepseek-v4-flash','provider':'deepseek','base_url':'https://api.deepseek.com/v1'}
config.setdefault('terminal',{}).update(backend='local',cwd='/home/ubuntu/haudi-hermes/workspace')
config.setdefault('stt',{})['enabled']=False
path.write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False))
print('Non-secret runtime settings saved; voice input disabled for text trial.')
PY
sudo mkdir -p /etc/systemd/system/haudi-hermes.service.d
sudo tee /etc/systemd/system/haudi-hermes.service.d/runtime.conf >/dev/null <<'UNIT'
[Service]
Environment=UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
Environment=HERMES_TUI_DIR=/home/ubuntu/haudi-hermes/source/ui-tui
UNIT
sudo systemctl daemon-reload
sudo systemctl restart haudi-hermes.service
systemctl is-active haudi-hermes.service
