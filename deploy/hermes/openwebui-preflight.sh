set -euo pipefail
sudo docker version --format '{{.Server.Version}}'
sudo docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
ss -ltn
df -h /
free -h
sudo docker pull ghcr.io/open-webui/open-webui:main-slim
sudo docker image inspect ghcr.io/open-webui/open-webui:main-slim --format '{{json .RepoDigests}}'
