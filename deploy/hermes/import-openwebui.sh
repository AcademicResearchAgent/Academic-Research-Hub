set -euo pipefail
sudo docker load -i /home/ubuntu/haudi-hermes/openwebui-image.tar
sudo docker tag ghcr.io/open-webui/open-webui:haudi-pinned ghcr.io/open-webui/open-webui:main-slim
sudo docker image inspect ghcr.io/open-webui/open-webui:main-slim --format 'Imported image: {{.Id}}'
