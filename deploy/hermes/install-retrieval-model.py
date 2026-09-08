"""Download a pinned safetensors embedding model into persistent application data."""
import hashlib,json,os,time
from pathlib import Path
import httpx
os.umask(0o022)
root=Path('/home/ubuntu/haudi-hermes')
spec=json.loads((root/'retrieval.json').read_text())
target=root/'openwebui/data/models/multilingual-e5-small'
target.mkdir(parents=True,exist_ok=True)
endpoint=spec['download_endpoint'];repo=spec['model_id'];rev=spec['revision']
with httpx.Client(follow_redirects=True,timeout=120) as c:
 r=c.get(f'{endpoint}/api/models/{repo}/revision/{rev}',params={'blobs':'true'});r.raise_for_status()
 info=r.json();assert info['sha']==rev
 selected=[f for f in info['siblings'] if f['rfilename'] in {
  'config.json','config_sentence_transformers.json','modules.json','sentence_bert_config.json',
  'tokenizer.json','tokenizer_config.json','special_tokens_map.json','sentencepiece.bpe.model',
  'model.safetensors','1_Pooling/config.json','README.md'}]
 assert any(f['rfilename']=='model.safetensors' for f in selected)
 for item in selected:
  name=item['rfilename'];dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True)
  checksum=(item.get('lfs') or {}).get('sha256')
  if dest.exists() and (not checksum or hashlib.sha256(dest.read_bytes()).hexdigest()==checksum):
   print('Already present:',name,flush=True);continue
  temporary=dest.with_suffix(dest.suffix+'.partial')
  for attempt in range(3):
   try:
    h=hashlib.sha256();size=0;reported=0
    with c.stream('GET',f'{endpoint}/{repo}/resolve/{rev}/{name}',params={'download':'true'}) as response:
     response.raise_for_status()
     with temporary.open('wb') as out:
      for chunk in response.iter_bytes(1024*1024):
       out.write(chunk);h.update(chunk);size+=len(chunk)
       if size-reported>=50*1024*1024:
        print(name,round(size/1024/1024),'MiB',flush=True);reported=size
    if checksum:assert h.hexdigest()==checksum,'Model checksum mismatch'
    temporary.replace(dest)
    print('Installed:',name,size,flush=True);break
   except Exception as exc:
    print('Download retry:',name,attempt+1,type(exc).__name__,flush=True)
    if attempt==2:raise
    time.sleep(2)
 (target/'download-manifest.json').write_text(json.dumps({'model':repo,'revision':rev,'files':selected},indent=2))
print('Pinned embedding model installed in persistent data.',flush=True)
