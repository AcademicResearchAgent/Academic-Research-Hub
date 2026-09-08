set -euo pipefail
timeout 180 /home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import json,time
from pathlib import Path
import httpx
account=json.loads(Path('/home/ubuntu/haudi-hermes/openwebui/access.json').read_text())
prompt='科研主题检索验收 paper-audit-20260908-03：请实际调用 web_search，检索2024—2025年发表、PubMed可核验的 base editing（碱基编辑）综述，选出两篇。再用网页读取工具核验这两篇的题录。每篇只给标题、年份、PMID、DOI、来源URL，并标明只读了题录/摘要还是全文。不需要综述内容。最多4次工具调用，不要安装软件，不要使用终端，不要读写文件。未找到或访问失败时如实说明，不要用记忆补全。'
with httpx.Client(base_url='http://127.0.0.1:9119',timeout=150) as c:
    r=c.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')})
    if r.status_code!=200:raise SystemExit('Login failed')
    c.headers['Authorization']='Bearer '+r.json()['token']
    started=time.monotonic();pieces=[];events=[];event_name=''
    print('Starting real topic search...',flush=True)
    with c.stream('POST','/api/chat/completions',json={'model':'hermes-agent','stream':True,'messages':[{'role':'user','content':prompt}]}) as r:
        if r.status_code!=200:raise SystemExit('Chat HTTP '+str(r.status_code))
        for line in r.iter_lines():
            if line.startswith('event:'):event_name=line[6:].strip();continue
            if not line: event_name='';continue
            if not line.startswith('data:'):continue
            raw=line[5:].strip()
            if not raw or raw=='[DONE]':continue
            e=json.loads(raw)
            if event_name=='hermes.tool.progress':
                item={k:e.get(k) for k in ('tool','status')};events.append(item);print(json.dumps(item),flush=True)
            if e.get('error'):raise SystemExit('Chat stream error')
            for choice in e.get('choices',[]):
                content=choice.get('delta',{}).get('content')
                if isinstance(content,str):pieces.append(content)
    print(json.dumps({'seconds':round(time.monotonic()-started,1),'answer':''.join(pieces),'tool_events':events},ensure_ascii=False))
PY
