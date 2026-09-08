set -euo pipefail
certbot=/home/ubuntu/haudi-hermes/certbot-venv/bin/certbot
args=(certonly --non-interactive --agree-tos --register-unsafely-without-email
      --config-dir /etc/haudi-letsencrypt --work-dir /var/lib/haudi-letsencrypt --logs-dir /var/log/haudi-letsencrypt
      --webroot --webroot-path /var/lib/haudi-acme --preferred-profile shortlived
      --cert-name workstation-ip --ip-address 42.193.15.167)
sudo "$certbot" "${args[@]}" --dry-run
sudo "$certbot" "${args[@]}" --keep-until-expiring
sudo openssl x509 -in /etc/haudi-letsencrypt/live/workstation-ip/fullchain.pem -noout -issuer -dates -ext subjectAltName
