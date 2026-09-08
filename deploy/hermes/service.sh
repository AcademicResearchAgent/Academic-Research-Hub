set -euo pipefail
deploy_root=/home/ubuntu/haudi-hermes
export PATH="$deploy_root/runtime/node/bin:$deploy_root/venv/bin:$PATH"
export HERMES_HOME="$deploy_root/state"
cd "$deploy_root/source"
python - <<'PY'
from pathlib import Path
from hermes_cli.main_web_build import _write_web_ui_build_stamp
root=Path.cwd()
_write_web_ui_build_stamp(root,root/'web')
print('Dashboard build stamp recorded')
PY
if systemctl cat haudi-hermes.service >/dev/null 2>&1; then
  echo 'Service already exists; refusing to overwrite.' >&2
  exit 1
fi
sudo tee /etc/systemd/system/haudi-hermes.service >/dev/null <<'UNIT'
[Unit]
Description=Hermes Agent Web Dashboard (haudi trial)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/haudi-hermes/workspace
Environment=HERMES_HOME=/home/ubuntu/haudi-hermes/state
Environment=PATH=/home/ubuntu/haudi-hermes/runtime/uv-bin:/home/ubuntu/haudi-hermes/runtime/node/bin:/home/ubuntu/haudi-hermes/venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
Environment=LANG=C.UTF-8
ExecStart=/home/ubuntu/haudi-hermes/venv/bin/python -m hermes_cli.main dashboard --host 127.0.0.1 --port 9119 --no-open
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillMode=control-group
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now haudi-hermes.service
systemctl is-active haudi-hermes.service
