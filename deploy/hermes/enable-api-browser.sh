set -euo pipefail
sudo mkdir -p /etc/systemd/system/haudi-hermes-api.service.d
sudo tee /etc/systemd/system/haudi-hermes-api.service.d/browser.conf >/dev/null <<'UNIT'
[Service]
Environment=AGENT_BROWSER_EXECUTABLE_PATH=/opt/haudi-hermes-chrome-152.0.7977.82/chrome
UNIT
sudo systemctl daemon-reload
sudo systemctl restart haudi-hermes-api.service
cd /home/ubuntu/haudi-hermes/source
export HERMES_HOME=/home/ubuntu/haudi-hermes/state
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
export AGENT_BROWSER_EXECUTABLE_PATH=/opt/haudi-hermes-chrome-152.0.7977.82/chrome
../venv/bin/python - <<'PY'
from tools.browser_tool import check_browser_requirements
assert check_browser_requirements()
print('Hermes browser tool dependency check: OK')
PY
