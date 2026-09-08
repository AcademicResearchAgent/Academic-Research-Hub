set -euo pipefail
deploy_root=/home/ubuntu/haudi-hermes
test -f "$deploy_root/openwebui/staging-verified"
curl --silent --fail http://127.0.0.1:18119/health >/dev/null
image_ref=$(cat "$deploy_root/openwebui/image.txt")
rollback() {
  echo 'Open WebUI cutover failed; restoring previous dashboard.' >&2
  sudo docker stop haudi-openwebui >/dev/null 2>&1 || true
  sudo systemctl enable --now haudi-hermes.service
}
trap rollback ERR
sudo systemctl stop haudi-hermes.service
sudo docker stop haudi-openwebui >/dev/null
sudo docker rm haudi-openwebui >/dev/null
sudo docker run -d --name haudi-openwebui --network host --restart unless-stopped \
  --env-file "$deploy_root/openwebui/container.env" -e PORT=9119 \
  --mount type=bind,src="$deploy_root/openwebui/data",dst=/app/backend/data \
  "$image_ref"
ready=0
for attempt in $(seq 1 120); do
  if curl --silent --fail http://127.0.0.1:9119/health >/dev/null; then ready=1; break; fi
  sleep 2
done
test "$ready" = 1
sudo systemctl disable haudi-hermes.service
trap - ERR
echo 'Primary UI switched to Open WebUI on 127.0.0.1:9119.'
sudo docker ps --filter name=haudi-openwebui --format '{{.Names}} {{.Status}}'
systemctl is-active haudi-hermes-api.service
