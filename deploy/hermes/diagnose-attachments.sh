set -euo pipefail
free -m
df -h /
sudo docker exec -i haudi-openwebui python - <<'PY'
import importlib.util,os,sqlite3,json
for module in ['torch','sentence_transformers','transformers','pypdf']:
 print('module',module,bool(importlib.util.find_spec(module)))
db=sqlite3.connect('file:/app/backend/data/webui.db?mode=ro',uri=True)
print('config-columns',[row[1] for row in db.execute('PRAGMA table_info(config)')])
for key in ['RAG_EMBEDDING_MODEL','OFFLINE_MODE','HF_HUB_OFFLINE','RAG_EMBEDDING_MODEL_AUTO_UPDATE']:
 print('env',key,os.environ.get(key,'<default>'))
print('files',db.execute('select count(*) from file').fetchone()[0])
PY
/home/ubuntu/haudi-hermes/venv/bin/python - <<'PY'
import httpx
for host in ['https://huggingface.co','https://hf-mirror.com']:
 try:
  r=httpx.get(host+'/api/models/intfloat/multilingual-e5-small',timeout=12)
  print('model-host',host,r.status_code)
  if r.status_code==200:print('revision',r.json().get('sha'))
 except Exception as e:print('model-host',host,type(e).__name__)
PY
