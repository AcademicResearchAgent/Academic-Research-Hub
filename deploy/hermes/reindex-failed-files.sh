set -euo pipefail
sudo docker exec -i haudi-openwebui python - <<'PY'
import json,sqlite3,httpx
from pathlib import Path
db=sqlite3.connect('file:/app/backend/data/webui.db?mode=ro',uri=True)
failed=[]
for fid,data in db.execute('select id,data from file'):
 data=json.loads(data or '{}')
 if data.get('status')=='failed' or data.get('error'):failed.append(fid)
print('Failed upload count:',len(failed))
# Emit identifiers only to the calling process over a private pipe, never content.
Path('/app/backend/data/failed-reindex-ids.json').write_text(json.dumps(failed))
Path('/app/backend/data/failed-reindex-ids.json').chmod(0o600)
PY
/home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import json,httpx,subprocess
from pathlib import Path
root=Path('/home/ubuntu/haudi-hermes/openwebui')
account=json.loads((root/'access.json').read_text())
ids=json.loads(subprocess.check_output(['sudo','cat',str(root/'data/failed-reindex-ids.json')]))
with httpx.Client(base_url='http://127.0.0.1:9119',timeout=180) as c:
 r=c.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')});r.raise_for_status()
 c.headers['Authorization']='Bearer '+r.json()['token']
 for fid in ids:
  r=c.post('/api/v1/retrieval/process/file',json={'file_id':fid});r.raise_for_status()
  assert r.json().get('status') is True
 print('Previously failed uploads reindexed:',len(ids))
PY
