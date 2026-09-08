"""Enable the installed multilingual embedding model; preserve credentials and unrelated settings."""
import json,os,shutil,time
from pathlib import Path
import httpx
os.umask(0o077)
root=Path('/home/ubuntu/haudi-hermes');ui=root/'openwebui'
spec=json.loads((root/'retrieval.json').read_text())
account=json.loads((ui/'access.json').read_text())
backup=ui/('retrieval-backup-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()));backup.mkdir()
with httpx.Client(base_url='http://127.0.0.1:9119',timeout=180) as c:
 r=c.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')});r.raise_for_status()
 c.headers['Authorization']='Bearer '+r.json()['token']
 for name,path in [('embedding','/api/v1/retrieval/embedding'),('retrieval','/api/v1/retrieval/config')]:
  r=c.get(path);r.raise_for_status();(backup/(name+'.json')).write_text(json.dumps(r.json()))
 r=c.post('/api/v1/retrieval/embedding/update',json={
  'RAG_EMBEDDING_ENGINE':'','RAG_EMBEDDING_MODEL':spec['container_path'],
  'RAG_EMBEDDING_BATCH_SIZE':spec['batch_size'],'ENABLE_ASYNC_EMBEDDING':True,
  'RAG_EMBEDDING_CONCURRENT_REQUESTS':1});r.raise_for_status()
 r=c.post('/api/v1/retrieval/config/update',json={
  'BYPASS_EMBEDDING_AND_RETRIEVAL':False,'RAG_FULL_CONTEXT':False,
  'CHUNK_SIZE':spec['chunk_size'],'CHUNK_OVERLAP':spec['chunk_overlap']});r.raise_for_status()
env=ui/'container.env';shutil.copy2(env,backup/'container.env')
settings={'RAG_EMBEDDING_MODEL':spec['container_path'],'RAG_EMBEDDING_QUERY_PREFIX':spec['query_prefix'],
 'RAG_EMBEDDING_CONTENT_PREFIX':spec['content_prefix'],'RAG_EMBEDDING_BATCH_SIZE':'1',
 'OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2','TOKENIZERS_PARALLELISM':'false'}
lines=[line for line in env.read_text().splitlines() if line.split('=',1)[0] not in settings]
env.write_text('\n'.join(lines)+'\n'+''.join(k+'='+v+'\n' for k,v in settings.items()));env.chmod(0o600)
print('Retrieval configured; prefix/thread environment takes effect at UI container recreation.')
print('Backup:',backup.name)
