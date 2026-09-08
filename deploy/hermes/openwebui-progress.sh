set -euo pipefail
if [ -f /home/ubuntu/haudi-hermes/openwebui-image.tar ]; then
  du -h /home/ubuntu/haudi-hermes/openwebui-image.tar
fi
sudo docker ps --filter name=haudi-openwebui --format '{{.Names}} {{.Status}}'
if sudo docker container inspect haudi-openwebui >/dev/null 2>&1; then
  sudo docker logs --tail 12 haudi-openwebui
fi
