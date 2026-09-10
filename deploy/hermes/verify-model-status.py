"""Check real account model states; temporary fixtures are always removed."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import time
import httpx
from dotenv import dotenv_values

ROOT=Path('/home/ubuntu/haudi-hermes')

def main(browser_ref=None):
    account=json.loads((ROOT/'openwebui/access.json').read_text())
    temporary=[]
    with httpx.Client(base_url='https://42.193.15.167',timeout=180,trust_env=False) as client:
        response=client.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')});response.raise_for_status()
        user=response.json();client.headers['Authorization']='Bearer '+user['token']
        catalog=client.get('/api/workstation/catalog').json()
        assert len(catalog['models'])==9
        assert not any('vision-exp' in m['id'] for m in catalog['models'])
        assert next(m for m in catalog['models'] if m['upstream_id']=='kimi-k2.7-code')['name']=='Kimi K2.7'
        try:
            if not catalog['credentials']['deepseek']['configured']:
                env=dotenv_values(ROOT/'state/.env')
                key=env.get('DEEPSEEK_API_KEY') or env.get('OPENAI_API_KEY');assert key
                response=client.post('/api/workstation/credentials',json={'model_id':'ws-deepseek-v4-flash','endpoint_id':'official','api_key':key})
                response.raise_for_status();temporary.append('deepseek')
            states={}
            for model_id in ('ws-deepseek-v4-flash','ws-deepseek-v4-pro'):
                response=client.post('/api/workstation/models/'+model_id+'/check');response.raise_for_status()
                result=response.json();assert result['state']=='available',result
                repeated=client.post('/api/workstation/models/'+model_id+'/check').json()
                assert result['checked_at']==repeated['checked_at'],'Expected cached probe'
                states[model_id]=result['state']
            # Simulate a once-configured key that has become invalid, in the test
            # administrator account only. Public key-save validation stays enabled.
            provider=next(p for p in ('glm','qwen','kimi') if not catalog['credentials'][p]['configured'])
            model=next(m for m in catalog['models'] if m['provider']==provider)
            endpoint=catalog['providers'][provider]['endpoints'][0]['id']
            script='''import sys
from open_webui.workstation_models.router import store
user,provider,endpoint,model=sys.argv[1:]
assert store().get(user,provider) is None
store().put(user,provider,endpoint,"invalid-availability-test-fixture",model)
'''
            subprocess.run(['sudo','docker','exec','haudi-openwebui','python','-c',script,user['id'],provider,endpoint,model['id']],check=True,capture_output=True)
            temporary.append(provider)
            response=client.post('/api/workstation/models/'+model['id']+'/check');response.raise_for_status()
            assert response.json()['state']=='unavailable',response.json()
            states[model['id']]='unavailable'
            current=client.get('/api/workstation/catalog').json()
            assert any(v['state']=='unconfigured' for v in current['availability'].values())
            report={'verified_at':datetime.now(timezone.utc).isoformat(),'models':states,'cache_reused':True,'catalog_count':9}
            print(json.dumps(report),flush=True)
            if browser_ref:
                env={**os.environ,'PATH':str(ROOT/'runtime/bin')+':'+str(ROOT/'runtime/node/bin')+':'+os.environ.get('PATH','')}
                command=['agent-browser','--session','haudi-model-status']
                def browser(*args):return subprocess.check_output([*command,*args],env=env,text=True,stderr=subprocess.DEVNULL)
                browser('click',browser_ref)
                for _ in range(50):
                    text=browser('eval','document.body.innerText')
                    if all(label in text for label in ('未配置','不可用','可用','Kimi K2.7')) and '检测中' not in text:break
                    time.sleep(1)
                assert all(label in text for label in ('未配置','不可用','可用','Kimi K2.7'))
                assert 'Kimi K2.7 Code' not in text and 'Vision · 实验版' not in text
                report['browser']={'all_three_states':True,'simplified_kimi_name':True,'experimental_model_absent':True}
                print(browser('snapshot','-i'),flush=True)
            (ROOT/'openwebui/model-status-verification.json').write_text(json.dumps(report,indent=2))
        finally:
            for provider in temporary:
                result=client.delete('/api/workstation/credentials/'+provider);result.raise_for_status()
            refreshed=client.get('/api/workstation/catalog').json()
            assert all(not refreshed['credentials'][p]['configured'] for p in temporary)
            print('Temporary test credentials removed.',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--browser-selector-ref')
    main(parser.parse_args().browser_selector_ref)
