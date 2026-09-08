set -euo pipefail
deploy_root=/home/ubuntu/haudi-hermes
chrome_root=/opt/haudi-hermes-chrome-152.0.7977.82
if [ ! -d "$chrome_root" ]; then
  sudo cp -a /home/ubuntu/.agent-browser/browsers/chrome-152.0.7977.82 "$chrome_root"
  sudo chown -R root:root "$chrome_root"
  sudo chmod -R go-w "$chrome_root"
fi
if [ ! -f /etc/apparmor.d/haudi-hermes-chrome ]; then
  sudo tee /etc/apparmor.d/haudi-hermes-chrome >/dev/null <<'PROFILE'
abi <abi/4.0>,
include <tunables/global>
profile haudi-hermes-chrome /opt/haudi-hermes-chrome-152.0.7977.82/chrome flags=(unconfined) {
  userns,
}
PROFILE
  sudo apparmor_parser -r /etc/apparmor.d/haudi-hermes-chrome
fi
cat > "$deploy_root/runtime/bin/agent-browser" <<'WRAPPER'
#!/bin/sh
export LD_LIBRARY_PATH=/home/ubuntu/haudi-hermes/runtime/chrome-libs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
exec /home/ubuntu/haudi-hermes/runtime/browser/node_modules/.bin/agent-browser --executable-path /opt/haudi-hermes-chrome-152.0.7977.82/chrome "$@"
WRAPPER
chmod 755 "$deploy_root/runtime/bin/agent-browser"
export PATH="$deploy_root/runtime/bin:$deploy_root/runtime/node/bin:$PATH"
agent-browser --session haudi-deploy-smoke close || true
agent-browser --session haudi-deploy-smoke open https://example.com
agent-browser --session haudi-deploy-smoke get title
agent-browser --session haudi-deploy-smoke close
sudo tee /etc/systemd/system/haudi-hermes.service.d/browser.conf >/dev/null <<'UNIT'
[Service]
Environment=PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/uv-bin:/home/ubuntu/haudi-hermes/runtime/node/bin:/home/ubuntu/haudi-hermes/venv/bin:/usr/local/bin:/usr/bin:/bin
UNIT
sudo systemctl daemon-reload
sudo systemctl restart haudi-hermes.service
