"""Apply research-workstation copy through supported settings and the Hermes identity file."""
import json
import os
from pathlib import Path
import shutil
import httpx

os.umask(0o077)
deploy=Path('/home/ubuntu/haudi-hermes')
root=deploy/'openwebui'
copy=json.loads((deploy/'research-copy.json').read_text())
account=json.loads((root/'access.json').read_text())
backup=root/'research-copy-backup'
backup.mkdir(exist_ok=True)

with httpx.Client(base_url='http://127.0.0.1:9119',timeout=30) as client:
    login=client.post('/api/v1/auths/signin',json={key:account[key] for key in ['email','password']})
    login.raise_for_status()
    client.headers['Authorization']='Bearer '+login.json()['token']
    config=client.get('/api/config')
    config.raise_for_status()
    saved=backup/'suggestions.json'
    if not saved.exists():
        saved.write_text(json.dumps(config.json().get('default_prompt_suggestions',[]),ensure_ascii=False,indent=2))
    response=client.post('/api/v1/configs/suggestions',json={'suggestions':copy['suggestions']})
    response.raise_for_status()
    assert response.json()==copy['suggestions']
    print('Six research workflow suggestions configured.')

    existing=client.get('/api/v1/models/model',params={'id':'hermes-agent'})
    if existing.status_code==200:
        model=existing.json()
        if not (backup/'model.json').exists():
            (backup/'model.json').write_text(json.dumps(model,ensure_ascii=False,indent=2))
        endpoint='/api/v1/models/model/update'
    elif existing.status_code in (401,404):
        model={'id':'hermes-agent','base_model_id':None,'meta':{},'params':{},'is_active':True}
        endpoint='/api/v1/models/create'
    else:
        existing.raise_for_status()
    model['name']=copy['assistant_name']
    model.setdefault('meta',{})['description']=copy['assistant_description']
    response=client.post(endpoint,json=model)
    response.raise_for_status()
    assert response.json()['name']==copy['assistant_name']
    response=client.get('/api/models')
    response.raise_for_status()
    visible=next(m for m in response.json()['data'] if m['id']=='hermes-agent')
    assert visible['name']==copy['assistant_name']
    print('Hermes display name and research description configured; API model ID retained.')

env=root/'container.env'
if not (backup/'container.env').exists(): shutil.copy2(env,backup/'container.env')
settings={
    'WEBUI_NAME':copy['app_name'],
    'DEFAULT_PROMPT_SUGGESTIONS':json.dumps(copy['suggestions'],ensure_ascii=False,separators=(',',':')),
}
lines=env.read_text().splitlines()
lines=[line for line in lines if line.split('=',1)[0] not in settings]
env.write_text('\n'.join(lines)+'\n'+''.join(k+'='+v+'\n' for k,v in settings.items()))
env.chmod(0o600)

soul=deploy/'state'/'SOUL.md'
if soul.exists() and not (backup/'SOUL.md').exists(): shutil.copy2(soul,backup/'SOUL.md')
soul.write_text((deploy/'research-SOUL.md').read_text())
soul.chmod(0o600)
print('Research workstation name and Hermes research identity saved.')
