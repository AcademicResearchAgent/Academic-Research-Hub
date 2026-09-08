set -euo pipefail
sudo docker inspect haudi-openwebui --format '{{.Image}}'
sudo docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' haudi-openwebui
free -m
sudo docker exec -i haudi-openwebui python - <<'PY'
import os,sqlite3,json
from pathlib import Path
db=sqlite3.connect('file:/app/backend/data/webui.db?mode=ro',uri=True)
statuses={}
for (data,) in db.execute('select data from file'):
 status=json.loads(data or '{}').get('status','unknown');statuses[status]=statuses.get(status,0)+1
print('Persisted file status counts:',statuses)
for name in ('RAG_EMBEDDING_MODEL','RAG_EMBEDDING_QUERY_PREFIX','RAG_EMBEDDING_CONTENT_PREFIX','OMP_NUM_THREADS'):
 print(name,repr(os.getenv(name)))
ids=Path('/app/backend/data/failed-reindex-ids.json')
if ids.exists():ids.unlink()
PY
curl --silent --fail http://127.0.0.1:9119/health
curl --silent --fail http://127.0.0.1:8642/health
