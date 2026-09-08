set -euo pipefail
deploy_root=/home/ubuntu/haudi-hermes
"$deploy_root/venv/bin/python" - <<'PY'
import os, secrets
from pathlib import Path
from dotenv import dotenv_values
os.umask(0o077)
root=Path('/home/ubuntu/haudi-hermes/openwebui')
root.mkdir(exist_ok=True)
(root/'data').mkdir(exist_ok=True)
envfile=root/'container.env'
old=dotenv_values(envfile) if envfile.exists() else {}
key=dotenv_values('/home/ubuntu/haudi-hermes/state/.env')['API_SERVER_KEY']
values={
    **old,
    'HOST':old.get('HOST') or '127.0.0.1',
    'OPENAI_API_BASE_URL':'http://127.0.0.1:8642/v1',
    'OPENAI_API_KEY':key,
    'WEBUI_SECRET_KEY':old.get('WEBUI_SECRET_KEY') or secrets.token_hex(32),
    'WEBUI_URL':old.get('WEBUI_URL') or 'http://127.0.0.1:9119',
    'WEBUI_AUTH':'true',
    'ENABLE_SIGNUP':'false',
    'ENABLE_OLLAMA_API':'false',
    'OFFLINE_MODE':'true',
    'HF_HUB_OFFLINE':'1',
    'RAG_EMBEDDING_MODEL_AUTO_UPDATE':'false',
    'ENABLE_VERSION_UPDATE_CHECK':'false',
    'ENABLE_TITLE_GENERATION':'false',
    'ENABLE_TAGS_GENERATION':'false',
    'ENABLE_FOLLOW_UP_GENERATION':'false',
    'DEFAULT_LOCALE':'zh-CN',
    'DEFAULT_MODELS':'hermes-agent',
}
envfile.write_text(''.join(k+'='+v+'\n' for k,v in values.items()))
envfile.chmod(0o600)
print('Open WebUI connection settings prepared; model credentials unchanged.')
PY
if sudo docker container inspect haudi-openwebui >/dev/null 2>&1; then
  echo 'Existing task container found; leaving it unchanged.'
  exit 0
fi
if [ -f "$deploy_root/openwebui/research-image.txt" ]; then
  image_ref=$(cat "$deploy_root/openwebui/research-image.txt")
elif [ -f "$deploy_root/openwebui/login-image.txt" ]; then
  image_ref=$(cat "$deploy_root/openwebui/login-image.txt")
else
  image_ref=$(sudo docker image inspect ghcr.io/open-webui/open-webui:main-slim --format '{{.Id}}')
fi
printf '%s\n' "$image_ref" > "$deploy_root/openwebui/image.txt"
sudo docker run -d --name haudi-openwebui --network host --restart unless-stopped \
  --env-file "$deploy_root/openwebui/container.env" -e PORT=18119 \
  --mount type=bind,src="$deploy_root/openwebui/data",dst=/app/backend/data \
  "$image_ref"
