set -euo pipefail
root=/home/ubuntu/haudi-hermes/openwebui
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="$root/container.env.before-public-$stamp"
previous="haudi-openwebui-before-public-$stamp"
image_ref=$(sudo docker inspect haudi-openwebui --format '{{.Image}}')
cp -p "$root/container.env" "$backup"
/home/ubuntu/haudi-hermes/venv/bin/python - <<'PY'
from pathlib import Path
p=Path('/home/ubuntu/haudi-hermes/openwebui/container.env')
lines=p.read_text().splitlines()
updates={'HOST':'0.0.0.0','WEBUI_URL':'http://42.193.15.167:9119'}
assert 'WEBUI_AUTH=true' in lines
assert 'ENABLE_SIGNUP=false' in lines
lines=[line for line in lines if line.split('=',1)[0] not in updates]
p.write_text('\n'.join(lines+[k+'='+v for k,v in updates.items()])+'\n')
p.chmod(0o600)
PY
sudo docker stop haudi-openwebui >/dev/null
if ! sudo docker rename haudi-openwebui "$previous"; then
  cp -p "$backup" "$root/container.env"
  sudo docker start haudi-openwebui >/dev/null
  exit 1
fi
rollback() {
  trap - ERR
  sudo docker rm -f haudi-openwebui >/dev/null 2>&1 || true
  cp -p "$backup" "$root/container.env"
  sudo docker rename "$previous" haudi-openwebui
  sudo docker start haudi-openwebui >/dev/null
  echo 'Previous web service restored.' >&2
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
sudo ss -lnt '( sport = :9119 )' | grep -F '0.0.0.0:9119'
trap - ERR
echo 'Public WebUI ready at http://42.193.15.167:9119'
echo "Rollback container: $previous"
