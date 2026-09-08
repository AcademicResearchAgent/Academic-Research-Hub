set -euo pipefail
deploy_root=/home/ubuntu/haudi-hermes
"$deploy_root/runtime/uv-bin/uv" pip install --python "$deploy_root/venv/bin/python" --index-url https://pypi.tuna.tsinghua.edu.cn/simple 'aiohttp==3.14.3'
sudo sed -i 's/PYTHONUNBUFFEREDED/PYTHONUNBUFFERED/' /etc/systemd/system/haudi-hermes-api.service
sudo systemctl daemon-reload
sudo systemctl restart haudi-hermes-api.service
for attempt in $(seq 1 30); do
  if curl --silent --fail http://127.0.0.1:8642/health; then break; fi
  sleep 1
done
