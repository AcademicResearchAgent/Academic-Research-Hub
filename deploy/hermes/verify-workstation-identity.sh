set -euo pipefail
/home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import json,re,time
from pathlib import Path
import httpx
root=Path('/home/ubuntu/haudi-hermes')
account=json.loads((root/'openwebui/access.json').read_text())
cases=[
 ('self-introduction',[{'role':'user','content':'你是谁'}]),
 ('capabilities',[{'role':'user','content':'介绍一下你能帮我做哪些科研工作。'}]),
 ('existing-history',[
  {'role':'user','content':'你是谁'},
  {'role':'assistant','content':'我是科研智能体工作站里的科研助手。我的运行环境是 Hermes Agent（由 Nous Research 开发），交互界面是 Open WebUI。'},
  {'role':'user','content':'请重新简短介绍一下你自己。'}]),
]
results=[]
with httpx.Client(base_url='http://127.0.0.1:9119',timeout=180) as c:
 r=c.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')});r.raise_for_status()
 c.headers['Authorization']='Bearer '+r.json()['token']
 for name,messages in cases:
  pieces=[];started=time.monotonic()
  print('Testing:',name,flush=True)
  with c.stream('POST','/api/chat/completions',json={'model':'hermes-agent','stream':True,'messages':messages}) as r:
   r.raise_for_status()
   for line in r.iter_lines():
    if not line.startswith('data:'):continue
    raw=line[5:].strip()
    if not raw or raw=='[DONE]':continue
    e=json.loads(raw)
    assert not e.get('error'),'Chat stream returned an error'
    for choice in e.get('choices',[]):
     content=choice.get('delta',{}).get('content')
     if isinstance(content,str):pieces.append(content)
  answer=''.join(pieces).strip()
  assert answer and '科研' in answer,(name,'Research identity missing')
  assert not re.search(r'hermes|nous\s*research|open\s*webui',answer,re.I),(name,'Unrequested vendor introduction remains')
  result={'case':name,'seconds':round(time.monotonic()-started,1),'answer':answer}
  results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
(root/'openwebui/identity-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print('All identity checks passed through the workstation chat API.')
PY
