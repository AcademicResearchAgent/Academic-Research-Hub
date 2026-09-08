set -euo pipefail
deploy_root=/home/ubuntu/haudi-hermes
cd "$deploy_root/source"
export HERMES_HOME="$deploy_root/state"
../venv/bin/python - <<'PY'
import os, secrets
from pathlib import Path
import yaml
from dotenv import dotenv_values
os.umask(0o077)
state=Path('/home/ubuntu/haudi-hermes/state')
envfile=state/'.env'
env=dotenv_values(envfile) if envfile.exists() else {}
if not env.get('API_SERVER_KEY'):
    with envfile.open('a') as stream:
        stream.write('\nAPI_SERVER_KEY='+secrets.token_urlsafe(36)+'\n')
    envfile.chmod(0o600)
path=state/'config.yaml'
config=yaml.safe_load(path.read_text())
platform=config.setdefault('platforms',{}).setdefault('api_server',{})
platform['enabled']=True
platform.setdefault('extra',{}).update(host='127.0.0.1',port=8642,model_name='hermes-agent')
config.setdefault('gateway',{}).setdefault('api_server',{})['max_concurrent_runs']=2
config.setdefault('platform_toolsets',{})['api_server']=['hermes-cli']
path.write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False))
print('Hermes API connection key generated locally on server; no model credentials transferred.')
PY
if [ ! -f /etc/systemd/system/haudi-hermes-api.service ]; then
sudo tee /etc/systemd/system/haudi-hermes-api.service >/dev/null <<'UNIT'
[Unit]
Description=Hermes Agent API for Open WebUI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/haudi-hermes/workspace
Environment=HERMES_HOME=/home/ubuntu/haudi-hermes/state
Environment=PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/uv-bin:/home/ubuntu/haudi-hermes/runtime/node/bin:/home/ubuntu/haudi-hermes/venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
Environment=PYTHONUNBUFFERED=1
Environment=LANG=C.UTF-8
ExecStart=/home/ubuntu/haudi-hermes/venv/bin/python -m hermes_cli.main gateway run
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillMode=control-group
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT
fi
sudo systemctl daemon-reload
sudo systemctl enable --now haudi-hermes-api.service
systemctl is-active haudi-hermes-api.service
