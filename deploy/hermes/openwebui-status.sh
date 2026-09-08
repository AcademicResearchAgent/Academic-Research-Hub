set -u
sudo journalctl -u haudi-hermes-api.service -n 45 --no-pager
sudo docker ps --filter name=haudi-openwebui --format '{{.Names}} {{.Status}}'
systemctl show haudi-hermes-api.service -p ActiveState -p SubState -p NRestarts
