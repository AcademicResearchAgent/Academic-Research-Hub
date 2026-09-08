set -euo pipefail
cd /home/ubuntu/haudi-hermes/source
export HERMES_HOME=/home/ubuntu/haudi-hermes/state
timeout 65 /home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import json,time
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/haudi-hermes/state/.env')
from tools.web_tools import web_search_tool
t=time.monotonic()
print('Calling current Hermes web_search tool...',flush=True)
data=json.loads(web_search_tool('site:arxiv.org/abs Attention Is All You Need 1706.03762',limit=3))
items=data.get('data',{}).get('web',[])
print(json.dumps({'success':data.get('success'),'results':len(items),'seconds':round(time.monotonic()-t,1),'papers':[{'title':i.get('title'),'url':i.get('url')} for i in items[:3]]}))
if not data.get('success'):print('Search failed (raw provider response omitted).')
PY
