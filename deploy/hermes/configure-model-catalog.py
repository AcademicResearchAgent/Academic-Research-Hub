"""Register account-key models through supported administrator APIs, preserving base ACLs."""
import json
import os
from pathlib import Path
import httpx

os.umask(0o077)
root=Path('/home/ubuntu/haudi-hermes')
catalog=json.loads((root/'model-catalog.json').read_text())
account=json.loads((root/'openwebui/access.json').read_text())
with httpx.Client(base_url='http://127.0.0.1:9119',timeout=45) as client:
    response=client.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')})
    response.raise_for_status()
    client.headers['Authorization']='Bearer '+response.json()['token']
    response=client.get('/api/v1/evaluations/config');response.raise_for_status()
    backup=root/'openwebui/model-catalog-backup'
    backup.mkdir(exist_ok=True)
    if not (backup/'evaluations.json').exists():
        (backup/'evaluations.json').write_text(json.dumps(response.json(),ensure_ascii=False,indent=2))
    # Random Arena routing bypasses the explicit provider/key selection workflow.
    response=client.post('/api/v1/evaluations/config',json={'ENABLE_EVALUATION_ARENA_MODELS':False})
    response.raise_for_status()
    response=client.get('/api/v1/models/model',params={'id':'hermes-agent'})
    response.raise_for_status();base=response.json()
    grants=[{k:g[k] for k in ('principal_type','principal_id','permission')} for g in base.get('access_grants',[])]
    for entry in catalog['models']:
        response=client.get('/api/v1/models/model',params={'id':entry['id']})
        if response.status_code==200:
            model=response.json();url='/api/v1/models/model/update'
        elif response.status_code in (401,404):
            model={'id':entry['id'],'base_model_id':'hermes-agent','params':base.get('params',{}),'is_active':True,'access_grants':grants}
            url='/api/v1/models/create'
        else:response.raise_for_status()
        model['name']=entry['name']
        model.setdefault('meta',{}).update({'description':entry['description']+' · 首次使用需配置个人 API Key',
            'capabilities':{**(base.get('meta',{}).get('capabilities') or {}),'vision':entry['vision']},
            'tags':[{'name':catalog['providers'][entry['provider']]['name']}]})
        response=client.post(url,json=model);response.raise_for_status()
    response=client.get('/api/models');response.raise_for_status()
    visible={m['id'] for m in response.json()['data']}
    assert {m['id'] for m in catalog['models']}<=visible
    print(f"Registered {len(catalog['models'])} personal-key models; existing base access permissions preserved.")
