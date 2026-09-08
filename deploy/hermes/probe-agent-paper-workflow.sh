set -euo pipefail
timeout 240 /home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import json,time
from pathlib import Path
import httpx
account=json.loads(Path('/home/ubuntu/haudi-hermes/openwebui/access.json').read_text())
prompt='科研检索能力验收，编号 paper-audit-20260908-02：请实际调用检索工具，找到 Attention Is All You Need（arXiv:1706.03762），再读取其公开 HTML 正文。核实标题、年份、arXiv ID，并从正文确认 scaled dot-product attention 的缩放因子，给出所在章节名和来源链接。说明你实际读取的是摘要、正文片段还是完整全文。限用最多4次工具调用；不要安装软件、修改配置或读写工作区文件。如果工具失败就报告失败，不要凭记忆补写。最终回答限350字。'
with httpx.Client(base_url='http://127.0.0.1:9119',timeout=180) as client:
    login=client.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')})
    if login.status_code!=200:raise SystemExit('Login failed: '+str(login.status_code))
    client.headers['Authorization']='Bearer '+login.json()['token']
    started=time.monotonic(); content=[]; progress=[]
    print('Starting real DeepSeek/Hermes paper search and reading task...',flush=True)
    with client.stream('POST','/api/chat/completions',json={'model':'hermes-agent','stream':True,'messages':[{'role':'user','content':prompt}]}) as r:
        if r.status_code!=200:raise SystemExit('Chat HTTP '+str(r.status_code))
        for line in r.iter_lines():
            if not line.startswith('data:'):continue
            raw=line[5:].strip()
            if not raw or raw=='[DONE]':continue
            event=json.loads(raw)
            if event.get('error'):raise SystemExit('Chat stream error (details omitted).')
            for choice in event.get('choices',[]):
                delta=choice.get('delta',{})
                if isinstance(delta.get('content'),str):content.append(delta['content'])
            # Record public tool progress without credentials, user metadata or internal arguments.
            if event.get('type')=='hermes.tool.progress':
                item={k:event.get(k) for k in ('type','tool','status')};progress.append(item);print(json.dumps(item),flush=True)
    print(json.dumps({'seconds':round(time.monotonic()-started,1),'answer':''.join(content),'progress_events':progress},ensure_ascii=False),flush=True)
PY
