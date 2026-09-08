set -euo pipefail
root=/home/ubuntu/haudi-hermes
target=/etc/nginx/conf.d/haudi-workstation-https.conf
if ! sudo test -f "$target"; then
  sudo install -d -m 755 /var/lib/haudi-acme/.well-known/acme-challenge
  sudo tee "$target" >/dev/null <<'EOF'
server {
    listen 80;
    server_name 42.193.15.167;
    location ^~ /.well-known/acme-challenge/ {
        root /var/lib/haudi-acme;
        default_type text/plain;
        try_files $uri =404;
    }
    location / { return 404; }
}
EOF
  sudo nginx -t
  sudo nginx -s reload
fi
printf '%s\n' 'haudi-workstation-acme-check' | sudo tee /var/lib/haudi-acme/.well-known/acme-challenge/workstation-check >/dev/null
curl --fail --silent --retry 5 --retry-connrefused -H 'Host: 42.193.15.167' http://127.0.0.1/.well-known/acme-challenge/workstation-check
if ! test -x "$root/certbot-venv/bin/certbot"; then
  "$root/runtime/uv-bin/uv" venv "$root/certbot-venv" --python "$root/venv/bin/python"
  "$root/runtime/uv-bin/uv" pip install --python "$root/certbot-venv/bin/python" 'certbot==5.4.0'
fi
"$root/certbot-venv/bin/certbot" --version
