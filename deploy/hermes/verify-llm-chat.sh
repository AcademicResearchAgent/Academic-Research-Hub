set -euo pipefail
sudo systemctl restart haudi-hermes-api.service
ready=0
for attempt in $(seq 1 60); do
  if curl --silent --fail http://127.0.0.1:8642/health >/dev/null; then ready=1; break; fi
  sleep 1
done
test "$ready" = 1
/home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import json, time
from pathlib import Path
import httpx
root=Path('/home/ubuntu/haudi-hermes/openwebui')
account=json.loads((root/'access.json').read_text())
with httpx.Client(base_url='http://127.0.0.1:9119',timeout=180) as client:
    r=client.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')})
    if r.status_code != 200:
        raise SystemExit(f'Workstation login failed: HTTP {r.status_code}')
    client.headers['Authorization']='Bearer '+r.json()['token']
    print('Workstation login: OK',flush=True)
    request={'model':'hermes-agent','stream':True,'messages':[{
        'role':'user','content':'这是科研工作站的模型连通性测试。不要调用任何工具，只回复：科研助手已连接，可以开始研究任务。'}]}
    started=time.monotonic()
    chunks=[]
    print('Testing Open WebUI -> Hermes -> DeepSeek streaming response...',flush=True)
    with client.stream('POST','/api/chat/completions',json=request) as r:
        if r.status_code != 200:
            raise SystemExit(f'Chat request failed: HTTP {r.status_code}')
        for line in r.iter_lines():
            if not line.startswith('data:'): continue
            data=line[5:].strip()
            if not data or data=='[DONE]': continue
            event=json.loads(data)
            if event.get('error'):
                raise SystemExit('Chat stream returned an error; inspect server diagnostics.')
            for choice in event.get('choices',[]):
                content=choice.get('delta',{}).get('content')
                if isinstance(content,str): chunks.append(content)
    answer=''.join(chunks).strip()
    if '科研助手已连接' not in answer:
        raise SystemExit('Expected model confirmation missing; inspect server diagnostics.')
    print('Model response:',answer[:200])
    print(f'End-to-end streaming chat: OK ({time.monotonic()-started:.1f}s)')
PY
