set -euo pipefail
root=/home/ubuntu/haudi-hermes
curl --silent --show-error --fail https://42.193.15.167/health
curl --silent --head http://42.193.15.167:9119/ | head -5
sudo systemctl is-active haudi-certificate-renew.timer
sudo systemctl list-timers haudi-certificate-renew.timer --no-pager
sudo "$root/certbot-venv/bin/certbot" renew --dry-run --run-deploy-hooks --no-random-sleep-on-renew \
  --config-dir /etc/haudi-letsencrypt --work-dir /var/lib/haudi-letsencrypt --logs-dir /var/log/haudi-letsencrypt \
  --deploy-hook /usr/local/sbin/haudi-certificate-reloaded
WORKSTATION_VERIFY_URL=https://42.193.15.167 "$root/venv/bin/python" -u "$root/verify-model-selection.py"
