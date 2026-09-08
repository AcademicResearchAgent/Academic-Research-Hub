"""Exercise real upload, vector retrieval, web indexing and chat citations with synthetic material."""
import json,time,uuid
from pathlib import Path
import httpx
root=Path('/home/ubuntu/haudi-hermes')
account=json.loads((root/'openwebui/access.json').read_text())
text='科研检索验收记录。实验代号 ASTER-913。培养温度为31摄氏度，持续时间为17小时。对照组使用无菌水，实验组加入海藻糖。These are synthetic test data, not real research findings.'
with httpx.Client(base_url='http://127.0.0.1:9119',timeout=180) as c:
 r=c.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')});r.raise_for_status()
 c.headers['Authorization']='Bearer '+r.json()['token']
 filename='retrieval-verification-'+uuid.uuid4().hex[:8]+'.txt'
 r=c.post('/api/v1/files/',params={'process_in_background':'false'},files={'file':(filename,text.encode(),'text/plain')});r.raise_for_status()
 file=r.json();fid=file['id']
 try:
  r=c.get('/api/v1/files/'+fid);r.raise_for_status();file=r.json()
  assert file.get('data',{}).get('status')=='completed','File indexing did not complete'
  assert not file.get('data',{}).get('error'),'File indexing reported an error'
  collection=file['meta']['collection_name']
  r=c.post('/api/v1/retrieval/query/doc',json={'collection_name':collection,'query':'实验的培养温度和持续时间是多少？','k':3});r.raise_for_status()
  assert '31' in json.dumps(r.json()),'Vector search did not retrieve synthetic evidence'
  print('Text upload and Chinese vector retrieval: PASS',flush=True)
  r=c.post('/api/v1/retrieval/process/web',json={'url':'https://example.com'});r.raise_for_status()
  web=r.json();assert web.get('status') and web.get('collection_name')
  r=c.post('/api/v1/retrieval/query/doc',json={'collection_name':web['collection_name'],'query':'What is this domain used for?','k':3});r.raise_for_status()
  assert 'example' in json.dumps(r.json()).lower()
  print('Public webpage indexing and vector retrieval: PASS',flush=True)
  pieces=[];citations=[]
  payload={'model':'hermes-agent','stream':True,
   'messages':[{'role':'user','content':'请只根据所附验收记录回答 ASTER-913 的培养温度和持续时间，并引用附件。不要调用其他工具。'}],
   'files':[{'type':'file','id':fid,'name':filename,'collection_name':collection,'status':'uploaded'}]}
  with c.stream('POST','/api/chat/completions',json=payload) as r:
   r.raise_for_status()
   for line in r.iter_lines():
    if not line.startswith('data:'):continue
    raw=line[5:].strip()
    if not raw or raw=='[DONE]':continue
    event=json.loads(raw)
    assert not event.get('error'),'Chat stream error'
    if event.get('sources'):citations.extend(event['sources'])
    if event.get('citations'):citations.extend(event['citations'])
    for choice in event.get('choices',[]):
     delta=choice.get('delta',{}).get('content')
     if isinstance(delta,str):pieces.append(delta)
  answer=''.join(pieces)
  assert '31' in answer and '17' in answer,'Chat did not use file evidence'
  assert citations,'Chat citation source event missing'
  print('Chat answer:',answer,flush=True)
  print('Chat citation sources:',len(citations),flush=True)
  (root/'openwebui/retrieval-verification.json').write_text(json.dumps({'file_upload':'pass','vector_query':'pass','web_index':'pass','chat_answer':answer,'citation_count':len(citations)},ensure_ascii=False,indent=2))
 finally:
  r=c.delete('/api/v1/files/'+fid);r.raise_for_status()
  print('Synthetic uploaded file removed.',flush=True)
