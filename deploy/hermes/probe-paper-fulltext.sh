set -euo pipefail
cd /home/ubuntu/haudi-hermes/source
export HERMES_HOME=/home/ubuntu/haudi-hermes/state
timeout 65 /home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import asyncio,json,time,xml.etree.ElementTree as ET
import httpx
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/haudi-hermes/state/.env')
t=time.monotonic()
try:
    with httpx.Client(timeout=15,follow_redirects=True) as client:
        r=client.get('https://www.ebi.ac.uk/europepmc/webservices/rest/PMC3257301/fullTextXML')
        result={'probe':'Europe PMC OA full text','http':r.status_code,'bytes':len(r.content)}
        if r.status_code==200:
            xml=ET.fromstring(r.content);body=xml.find('.//body');result['body_present']=body is not None;result['body_text_chars']=len(''.join(body.itertext())) if body is not None else 0
        print(json.dumps(result),flush=True)
except Exception as exc:print('Europe PMC fulltext error:',type(exc).__name__,flush=True)
from tools.web_tools import web_extract_tool
print('Testing current Hermes extraction tool...',flush=True)
result=json.loads(asyncio.run(web_extract_tool(['https://arxiv.org/html/1706.03762'],char_limit=15000)))
serialized=json.dumps(result,ensure_ascii=False)
print(json.dumps({'probe':'Hermes arXiv HTML extraction','success':result.get('success'),'response_chars':len(serialized),'has_attention_section':'Scaled Dot-Product' in serialized,'has_experiment_section':'Training' in serialized,'seconds':round(time.monotonic()-t,1)}))
PY
