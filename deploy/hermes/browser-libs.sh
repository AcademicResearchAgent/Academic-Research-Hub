set -euo pipefail
deploy_root=/home/ubuntu/haudi-hermes
mkdir -p "$deploy_root/runtime/chrome-debs" "$deploy_root/runtime/chrome-libs" "$deploy_root/runtime/bin"
cd "$deploy_root/runtime/chrome-debs"
apt-get download libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 libasound2t64 libcups2t64 libcairo2 libpango-1.0-0 libxdamage1 libpixman-1-0 libxcb-render0 libxcb-shm0 libthai0 libthai-data libdatrie1 libavahi-common3 libavahi-client3 libharfbuzz0b libgraphite2-3 libfribidi0
for package in ./*.deb; do dpkg-deb -x "$package" "$deploy_root/runtime/chrome-libs"; done
cat > "$deploy_root/runtime/bin/agent-browser" <<'WRAPPER'
#!/bin/sh
export LD_LIBRARY_PATH=/home/ubuntu/haudi-hermes/runtime/chrome-libs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
exec /home/ubuntu/haudi-hermes/runtime/browser/node_modules/.bin/agent-browser "$@"
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
