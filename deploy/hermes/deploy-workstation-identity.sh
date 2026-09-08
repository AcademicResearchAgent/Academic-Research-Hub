set -euo pipefail
/home/ubuntu/haudi-hermes/venv/bin/python /home/ubuntu/haudi-hermes/apply-workstation-identity.py
sudo systemctl restart haudi-hermes-api.service
for attempt in $(seq 1 60); do
  if curl --silent --fail http://127.0.0.1:8642/health >/dev/null; then
    echo 'Research assistant API ready.'
    exit 0
  fi
  sleep 1
done
echo 'API health check timed out.' >&2
exit 1
