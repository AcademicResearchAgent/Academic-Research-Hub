"""Browser acceptance for new-chat defaults using temporary administrator fixtures."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time
import httpx
from dotenv import dotenv_values

ROOT=Path('/home/ubuntu/haudi-hermes')
ENV={**os.environ,'PATH':str(ROOT/'runtime/bin')+':'+str(ROOT/'runtime/node/bin')+':'+os.environ.get('PATH','')}

def browser(*args):
    return subprocess.check_output(['agent-browser','--session','haudi-default-model',*args],env=ENV,text=True,stderr=subprocess.DEVNULL)

def click_observed(label):
    # Resolve each action from a fresh accessibility snapshot, never stale refs.
    for _ in range(20):
        snapshot=browser('snapshot','-i')
        lines=[line for line in snapshot.splitlines() if label in line and ('[ref=' in line or ', ref=' in line)]
        if lines:break
        time.sleep(0.5)
    assert len(lines)==1, 'Expected one visible control: '+label
    ref=re.search(r'ref=(e\d+)',lines[0]).group(1)
    browser('click','@'+ref)

def wait_selected(name):
    for _ in range(70):
        snapshot=browser('snapshot','-i')
        if 'button "已选择：'+name+'"' in snapshot:return
        time.sleep(1)
    raise AssertionError('Expected selected model: '+name)

def main():
    account=json.loads((ROOT/'openwebui/access.json').read_text())
    added=False;fixture=None
    with httpx.Client(base_url='https://42.193.15.167',timeout=180,trust_env=False) as client:
        response=client.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')});response.raise_for_status()
        client.headers['Authorization']='Bearer '+response.json()['token']
        catalog=client.get('/api/workstation/catalog').json()
        assert not any(v['configured'] for v in catalog['credentials'].values()), 'Use the empty test administrator profile'
        try:
            env=dotenv_values(ROOT/'state/.env');key=env.get('DEEPSEEK_API_KEY') or env.get('OPENAI_API_KEY');assert key
            response=client.post('/api/workstation/credentials',json={'model_id':'ws-deepseek-v4-flash','endpoint_id':'official','api_key':key})
            response.raise_for_status();added=True
            # Flash was validated first, but Pro precedes it in the visible list.
            click_observed('link "新科研任务"')
            wait_selected('DeepSeek V4 Pro')
            print('New chat selected first available model (Pro), rather than the first validated key (Flash).',flush=True)
            click_observed('button "已选择：DeepSeek V4 Pro"')
            click_observed('option "选择模型 “DeepSeek V4 Flash”"')
            wait_selected('DeepSeek V4 Flash')
            click_observed('link "新科研任务"')
            wait_selected('DeepSeek V4 Pro')
            print('A new chat resets a previous manual Flash selection to the first available model.',flush=True)
            # Create an empty, explicitly Flash-bound history fixture without an LLM call.
            response=client.post('/api/v1/chats/new',json={'chat':{'title':'default-model-history-fixture',
                'models':['ws-deepseek-v4-flash'],'history':{'messages':{},'currentId':None},'messages':[],'params':{}},'folder_id':None})
            response.raise_for_status();fixture=response.json()['id']
            browser('open','https://42.193.15.167/c/'+fixture)
            wait_selected('DeepSeek V4 Flash')
            print('Existing chat retained its explicit Flash model.',flush=True)
            response=client.delete('/api/workstation/credentials/deepseek');response.raise_for_status();added=False
            click_observed('link "新科研任务"')
            for _ in range(30):
                text=browser('eval','document.body.innerText')
                if '当前没有可用模型' in text:break
                time.sleep(1)
            assert '当前没有可用模型' in text
            snapshot=browser('snapshot','-i')
            assert 'button "已选择：DeepSeek' not in snapshot
            report={'verified_at':datetime.now(timezone.utc).isoformat(),'first_available':True,
                    'new_chat_resets_manual_choice':True,'existing_chat_preserved':True,'no_available_hint':True}
            (ROOT/'openwebui/default-model-verification.json').write_text(json.dumps(report,indent=2))
            print(json.dumps(report),flush=True)
        finally:
            if added:client.delete('/api/workstation/credentials/deepseek').raise_for_status()
            if fixture:client.delete('/api/v1/chats/'+fixture).raise_for_status()
            print('Temporary test credential and history fixture removed.',flush=True)

if __name__=='__main__':main()
