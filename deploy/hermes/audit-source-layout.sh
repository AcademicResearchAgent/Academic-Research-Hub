set -euo pipefail
root=/home/ubuntu/haudi-hermes
printf 'Agent checkout: '
if [ -d "$root/source/.git" ]; then
  git -C "$root/source" rev-parse HEAD
  git -C "$root/source" status --short
else
  echo 'source files present, no Git checkout'
  test -f "$root/source/run_agent.py"
fi
printf '\nUI image revision metadata:\n'
sudo docker inspect haudi-openwebui --format '{{.Config.Image}}'
sudo docker image inspect ghcr.io/open-webui/open-webui:haudi-pinned --format '{{json .Config.Labels}}'
printf '\nDeployment directories (names only):\n'
find "$root" -maxdepth 2 -type d -name .git -o -maxdepth 2 -type d -name '*customization*'
sudo docker exec -i haudi-openwebui python - <<'PY'
from pathlib import Path
for name in ['/app/src','/app/package.json','/app/backend/open_webui','/app/build','/app/.git']:
 print(name,Path(name).exists())
PY
