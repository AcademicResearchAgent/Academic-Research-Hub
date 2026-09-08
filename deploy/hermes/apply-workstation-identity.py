"""Apply product identity without renaming runtime interfaces or upstream notices."""
import ast
import json
import os
from pathlib import Path
import shutil
import time
import httpx

os.umask(0o077)
root=Path('/home/ubuntu/haudi-hermes')
backup=root/'openwebui'/('identity-backup-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
backup.mkdir()
soul=root/'state/SOUL.md'
source=root/'source/agent/prompt_builder.py'
new_soul=(root/'research-SOUL.md').read_text()
text=source.read_text()
changes={
    'You are Hermes Agent, built by Nous Research. ': 'You are the research assistant in the scientific research workstation. ',
    'You run on Hermes Agent (by Nous Research). ': '',
}
expected=[1,2]
for (old,new),count in zip(changes.items(),expected):
    if old in text:
        assert text.count(old)==count, 'Upstream identity structure changed'
        text=text.replace(old,new)
ast.parse(text)
shutil.copy2(soul,backup/'SOUL.md')
shutil.copy2(source,backup/'prompt_builder.py')

# Model-level instructions are sent on each request, including conversations
# with an older cached base prompt. Preserve all other settings and grants.
identity=new_soul.split('## 产品身份\n\n',1)[1].split('\n## 按研究阶段推进',1)[0].strip()
account=json.loads((root/'openwebui/access.json').read_text())
with httpx.Client(base_url='http://127.0.0.1:9119',timeout=30) as c:
    r=c.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')}); r.raise_for_status()
    c.headers['Authorization']='Bearer '+r.json()['token']
    r=c.get('/api/v1/models/model',params={'id':'hermes-agent'}); r.raise_for_status()
    model=r.json()
    (backup/'model.json').write_text(json.dumps(model,ensure_ascii=False,indent=2))
    params=model.setdefault('params',{})
    start='<!-- workstation-identity:start -->'
    end='<!-- workstation-identity:end -->'
    prior=params.get('system','') or ''
    if start in prior:
        assert prior.count(start)==prior.count(end)==1
        before,tail=prior.split(start,1)
        prior=before+tail.split(end,1)[1]
    params['system']=prior.rstrip()+'\n\n'+start+'\n'+identity+'\n'+end
    r=c.post('/api/v1/models/model/update',json=model); r.raise_for_status()
    assert r.json()['params']['system']==params['system']
soul.write_text(new_soul); soul.chmod(0o600)
source.write_text(text)
print('Product identity updated in SOUL, runtime default introductions and per-request model instructions.')
print('Backup:',backup.name)
