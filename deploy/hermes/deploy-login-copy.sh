set -euo pipefail
root=/home/ubuntu/haudi-hermes/openwebui
image_ref=$(cat "$root/login-image.txt")
previous=$(sudo docker inspect haudi-openwebui --format '{{.Image}}')
if [ "$previous" = "$image_ref" ]; then echo 'Login copy image already deployed.'; exit 0; fi
if sudo docker inspect haudi-openwebui-before-login-v1 >/dev/null 2>&1; then
  echo 'A previous rollback container exists; review it before replacing.' >&2
  exit 1
fi
printf '%s\n' "$previous" > "$root/image-before-login.txt"
sudo docker stop haudi-openwebui >/dev/null
sudo docker rename haudi-openwebui haudi-openwebui-before-login-v1
rollback() {
  sudo docker rm -f haudi-openwebui >/dev/null 2>&1 || true
  sudo docker rename haudi-openwebui-before-login-v1 haudi-openwebui
  sudo docker start haudi-openwebui >/dev/null
  echo 'Restored the previous UI container.' >&2
}
trap rollback ERR
sudo docker run -d --name haudi-openwebui --network host --restart unless-stopped \
  --env-file "$root/container.env" -e PORT=9119 \
  --mount type=bind,src="$root/data",dst=/app/backend/data \
  "$image_ref"
ready=0
for attempt in $(seq 1 120); do
  if curl --silent --fail http://127.0.0.1:9119/health >/dev/null; then ready=1; break; fi
  sleep 1
done
test "$ready" = 1
printf '%s\n' "$image_ref" > "$root/image.txt"
trap - ERR
echo 'Updated login UI deployed on 127.0.0.1:9119.'
