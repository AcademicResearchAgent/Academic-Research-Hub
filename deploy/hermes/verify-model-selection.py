"""Exercise personal-key routing with the existing server's DeepSeek key; never print secrets."""
import json
from pathlib import Path
import sqlite3
import uuid
import httpx
from dotenv import dotenv_values

root=Path('/home/ubuntu/haudi-hermes')
account=json.loads((root/'openwebui/access.json').read_text())
env=dotenv_values(root/'state/.env')
key=env.get('DEEPSEEK_API_KEY') or env.get('OPENAI_API_KEY')
assert key,'Existing provider key was not found'
with httpx.Client(base_url='http://127.0.0.1:9119',timeout=240,trust_env=False) as c:
    response=c.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')});response.raise_for_status()
    user=response.json();c.headers['Authorization']='Bearer '+user['token']
    response=c.get('/api/workstation/catalog');response.raise_for_status()
    catalog=response.json()
    assert len(catalog['models'])>=4
    assert not catalog['credentials']['deepseek']['configured'],'Do not overwrite an existing personal credential'
    ids={m['id'] for m in c.get('/api/models').json()['data']}
    assert all(m['id'] in ids for m in catalog['models'])
    print('Catalog and first-selection status: PASS',flush=True)
    response=c.post('/api/workstation/models/ws-deepseek-v4-flash/activate')
    assert response.status_code==428
    try:
        response=c.post('/api/workstation/credentials',json={'model_id':'ws-deepseek-v4-flash','endpoint_id':'official','api_key':key})
        assert response.status_code==200,'Personal key validation failed (HTTP '+str(response.status_code)+')'
        print('Real DeepSeek credential validation: PASS',flush=True)
        for model in ('ws-deepseek-v4-flash','ws-deepseek-v4-pro'):
            response=c.post('/api/workstation/models/'+model+'/activate')
            assert response.status_code==200,'Model activation failed: '+model
            marker='model-check-'+uuid.uuid4().hex[:10]
            payload={'model':model,'stream':True,'messages':[{'role':'user','content':marker+' 请只回答 MODEL_OK，不要调用工具。'}]}
            parts=[]
            with c.stream('POST','/api/chat/completions',json=payload) as response:
                assert response.status_code==200,'Chat HTTP failure'
                for line in response.iter_lines():
                    if not line.startswith('data:'):continue
                    raw=line[5:].strip()
                    if not raw or raw=='[DONE]':continue
                    event=json.loads(raw)
                    assert not event.get('error'),'Model stream returned an error'
                    for choice in event.get('choices',[]):
                        delta=choice.get('delta',{}).get('content')
                        if isinstance(delta,str):parts.append(delta)
            assert 'MODEL_OK' in ''.join(parts),'Expected test answer not returned'
            # Verify the execution engine persisted the real model, without reading other chats.
            with sqlite3.connect(root/'state/state.db') as db:
                row=db.execute('SELECT s.model FROM sessions s JOIN messages m ON m.session_id=s.id WHERE m.content LIKE ? ORDER BY m.timestamp DESC LIMIT 1',('%'+marker+'%',)).fetchone()
            assert row and row[0]==model.removeprefix('ws-'),'Agent model did not match selection'
            print(model+': streaming reply and actual Agent model PASS',flush=True)
    finally:
        response=c.delete('/api/workstation/credentials/deepseek')
        assert response.status_code==200
        print('Temporary administrator credential removed; first-use setup restored.',flush=True)
