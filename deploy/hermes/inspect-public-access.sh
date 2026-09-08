set -euo pipefail
echo 'Listeners:'
sudo ss -lntp '( sport = :9119 or sport = :8642 )'
echo 'Container:'
sudo docker inspect haudi-openwebui --format '{{.State.Status}} {{.HostConfig.NetworkMode}} {{.Image}}'
echo 'Public access settings:'
sudo docker inspect haudi-openwebui --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^(HOST|PORT|WEBUI_URL|WEBUI_AUTH|ENABLE_SIGNUP)='
echo 'Host firewall:'
if command -v ufw >/dev/null; then sudo ufw status; fi
echo 'HTTP health:'
curl --silent --fail http://127.0.0.1:9119/health
