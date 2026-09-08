"""Run as root on the workstation host after issuing the IP certificate."""
from datetime import datetime,timezone
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import time
import httpx

ROOT=Path('/home/ubuntu/haudi-hermes')
HOST='42.193.15.167'
URL='https://'+HOST
NGINX=Path('/etc/nginx/conf.d/haudi-workstation-https.conf')
CERT=Path('/etc/haudi-letsencrypt/live/workstation-ip')
os.umask(0o077)

def run(*args):
    result=subprocess.run(args,capture_output=True,text=True)
    if result.returncode:raise RuntimeError('Command failed: '+args[0]+' '+args[1])
    return result.stdout.strip()

def ready():
    for _ in range(180):
        try:
            with httpx.Client(trust_env=False,timeout=2) as client:
                if client.get('http://127.0.0.1:9119/health').status_code==200:return
        except httpx.HTTPError:pass
        time.sleep(1)
    raise RuntimeError('Backend health check failed')

def public_url(value):
    account=json.loads((ROOT/'openwebui/access.json').read_text())
    with httpx.Client(base_url='http://127.0.0.1:9119',trust_env=False,timeout=30) as client:
        response=client.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')})
        response.raise_for_status()
        client.headers['Authorization']='Bearer '+response.json()['token']
        response=client.post('/api/v1/configs/import',json={'config':{'webui.url':value}})
        response.raise_for_status() # Do not print the returned configuration.

assert os.geteuid()==0,'Run this deployment script with sudo'
assert (CERT/'fullchain.pem').exists() and (CERT/'privkey.pem').exists()
address=json.loads(run('ip','-j','-4','route','get','1.1.1.1'))[0]['prefsrc']
ipaddress.IPv4Address(address)
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup=ROOT/'openwebui'/('https-backup-'+stamp)
backup.mkdir()
envfile=ROOT/'openwebui/container.env'
shutil.copy2(envfile,backup/'container.env')
shutil.copy2(NGINX,backup/'nginx.conf')
image=run('docker','inspect','haudi-openwebui','--format','{{.Image}}')
old_container='haudi-openwebui-before-https-'+stamp
settings={'HOST':'127.0.0.1','WEBUI_URL':URL,'FORWARDED_ALLOW_IPS':'127.0.0.1',
          'WEBUI_SESSION_COOKIE_SECURE':'true','WEBUI_AUTH_COOKIE_SECURE':'true'}
lines=envfile.read_text().splitlines()
previous_url=next((line.split('=',1)[1] for line in lines if line.startswith('WEBUI_URL=')),'http://'+HOST+':9119')
lines=[line for line in lines if line.split('=',1)[0] not in settings]
envfile.write_text('\n'.join(lines)+'\n'+''.join(k+'='+v+'\n' for k,v in settings.items()))
envfile.chmod(0o600)
config='''map $http_upgrade $haudi_ws_connection {
    default upgrade;
    '' close;
}
server {
    listen 80;
    server_name __HOST__;
    location ^~ /.well-known/acme-challenge/ {
        root /var/lib/haudi-acme;
        default_type text/plain;
        try_files $uri =404;
    }
    location / { return 308 https://__HOST__$request_uri; }
}
server {
    listen __ADDRESS__:9119;
    server_name __HOST__;
    return 308 https://__HOST__$request_uri;
}
server {
    listen 443 ssl;
    server_name __HOST__;
    ssl_certificate /etc/haudi-letsencrypt/live/workstation-ip/fullchain.pem;
    ssl_certificate_key /etc/haudi-letsencrypt/live/workstation-ip/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:haudi_tls:10m;
    client_max_body_size 0;
    location / {
        proxy_pass http://127.0.0.1:9119;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $haudi_ws_connection;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 900s;
        proxy_send_timeout 900s;
    }
}
'''.replace('__HOST__',HOST).replace('__ADDRESS__',address)
renamed=False
try:
    run('docker','stop','haudi-openwebui')
    run('docker','rename','haudi-openwebui',old_container);renamed=True
    run('docker','run','-d','--name','haudi-openwebui','--network','host','--restart','unless-stopped',
        '--env-file',str(envfile),'-e','PORT=9119','--mount',f'type=bind,src={ROOT}/openwebui/data,dst=/app/backend/data',image)
    ready()
    NGINX.write_text(config);NGINX.chmod(0o644)
    run('nginx','-t');run('nginx','-s','reload')
    for attempt in range(10):
        try:
            with socket.create_connection(('127.0.0.1',443),timeout=5) as raw:
                with ssl.create_default_context().wrap_socket(raw,server_hostname=HOST) as conn:
                    conn.sendall(('GET /health HTTP/1.1\r\nHost: '+HOST+'\r\nConnection: close\r\n\r\n').encode())
                    assert b'200 OK' in conn.recv(4096),'HTTPS health check failed'
            break
        except ConnectionRefusedError:
            if attempt==9:raise
            time.sleep(1)
    public_url(URL)
except Exception:
    shutil.copy2(backup/'nginx.conf',NGINX)
    run('nginx','-t');run('nginx','-s','reload')
    shutil.copy2(backup/'container.env',envfile)
    if renamed:
        subprocess.run(['docker','rm','-f','haudi-openwebui'],capture_output=True)
        run('docker','rename',old_container,'haudi-openwebui')
    run('docker','start','haudi-openwebui');ready();public_url(previous_url)
    raise

hook=Path('/usr/local/sbin/haudi-certificate-reloaded')
hook.write_text('#!/bin/sh\nset -eu\n/usr/sbin/nginx -t\n/usr/sbin/nginx -s reload\n')
hook.chmod(0o755)
Path('/etc/systemd/system/haudi-certificate-renew.service').write_text('''[Unit]
Description=Renew research workstation HTTPS certificate
After=network-online.target nginx.service
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/home/ubuntu/haudi-hermes/certbot-venv/bin/certbot renew --quiet --no-random-sleep-on-renew --config-dir /etc/haudi-letsencrypt --work-dir /var/lib/haudi-letsencrypt --logs-dir /var/log/haudi-letsencrypt --deploy-hook /usr/local/sbin/haudi-certificate-reloaded
''')
Path('/etc/systemd/system/haudi-certificate-renew.timer').write_text('''[Unit]
Description=Check workstation certificate renewal every six hours
[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
RandomizedDelaySec=15m
Persistent=true
Unit=haudi-certificate-renew.service
[Install]
WantedBy=timers.target
''')
run('systemctl','daemon-reload')
run('systemctl','enable','--now','haudi-certificate-renew.timer')
(ROOT/'openwebui/https-deployment.json').write_text(json.dumps({'url':URL,'backup':str(backup),'rollback_container':old_container,'legacy_listen_address':address},indent=2))
print('HTTPS deployed:',URL)
print('HTTP 80 and the previous public 9119 entry redirect to HTTPS.')
print('Backend is loopback-only; certificate renewal timer enabled.')
print('Rollback container:',old_container)
