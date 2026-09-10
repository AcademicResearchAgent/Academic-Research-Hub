"""Deploy the model status UI on the verified v6 baseline; retain rollback data."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import httpx

ROOT=Path('/home/ubuntu/haudi-hermes')
BASE_IMAGE='sha256:74d19ba28a028688fe502d4a0964d6c852d55d634d8534f1e567c54a405029e9'
TAG='haudi-openwebui:0.11.3-research-v7'

def run(*args):return subprocess.check_output(args,text=True).strip()

def healthy():
    for _ in range(90):
        try:
            if httpx.get('http://127.0.0.1:9119/health',timeout=2,trust_env=False).status_code==200:return
        except httpx.HTTPError:pass
        time.sleep(2)
    raise RuntimeError('UI health check failed')

def main():
    os.umask(0o077)
    assert run('sudo','docker','inspect','haudi-openwebui','--format','{{.Image}}')==BASE_IMAGE,'Expected v6 baseline'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    release=ROOT/'model-releases'/stamp;release.mkdir(parents=True)
    with tarfile.open(ROOT/'model-release.tar.gz') as archive:archive.extractall(release,filter='data')
    catalog=json.loads((release/'configs/workstation/model-catalog.json').read_text())
    old_catalog=json.loads((ROOT/'source/gateway/workstation_catalog.json').read_text())
    assert any(m['id']=='ws-deepseek-v4-flash-vision-exp' for m in old_catalog['models']),'Unexpected engine catalog'
    (release/'Dockerfile').write_text('FROM '+BASE_IMAGE+'\nCOPY reference/open-webui/build/ /app/build/\nCOPY reference/open-webui/backend/open_webui/ /app/backend/open_webui/\n')
    run('sudo','docker','build','-t',TAG,str(release))
    for pattern in ('test_workstation*.py','test_model_availability.py'):
        run('sudo','docker','run','--rm','--network','none','--entrypoint','python',
            '--mount',f'type=bind,src={release},dst=/work','-w','/work',TAG,
            '-m','unittest','discover','-s','tests','-p',pattern,'-v')
    print('v7 built; isolated model and streaming tests passed.',flush=True)
    backup=ROOT/'model-status-backups'/stamp;backup.mkdir(parents=True)
    for rel in ('source/gateway/workstation_catalog.json','model-catalog.json'):
        (backup/rel).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,backup/rel)
    account=json.loads((ROOT/'openwebui/access.json').read_text())
    client=httpx.Client(base_url='http://127.0.0.1:9119',timeout=45,trust_env=False)
    response=client.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')});response.raise_for_status()
    client.headers['Authorization']='Bearer '+response.json()['token']
    models=[]
    for model_id in [m['id'] for m in catalog['models']]+catalog['retired_models']:
        response=client.get('/api/v1/models/model',params={'id':model_id});response.raise_for_status();models.append(response.json())
    (backup/'models.json').write_text(json.dumps(models))
    previous='haudi-openwebui-before-model-status-'+stamp
    stopped=renamed=created=False
    try:
        shutil.copy2(release/'configs/workstation/model-catalog.json',ROOT/'source/gateway/workstation_catalog.json')
        shutil.copy2(release/'configs/workstation/model-catalog.json',ROOT/'model-catalog.json')
        run('sudo','docker','stop','haudi-openwebui');stopped=True
        run('sudo','docker','rename','haudi-openwebui',previous);renamed=True
        created=True
        run('sudo','docker','run','-d','--name','haudi-openwebui','--network','host','--restart','unless-stopped',
            '--env-file',str(ROOT/'openwebui/container.env'),'-e','PORT=9119',
            '--mount',f'type=bind,src={ROOT}/openwebui/data,dst=/app/backend/data',TAG)
        healthy()
        desired={m['id']:m for m in catalog['models']}
        for original in models:
            model=json.loads(json.dumps(original))
            if model['id'] in desired:
                model['name']=desired[model['id']]['name']
                model.setdefault('meta',{})['description']=desired[model['id']]['description']
            else:
                model['is_active']=False;model.setdefault('meta',{})['hidden']=True
            response=client.post('/api/v1/models/model/update',json=model);response.raise_for_status()
        response=client.get('/api/workstation/catalog');response.raise_for_status()
        assert set(response.json()['availability'])==set(desired)
        response=client.get('/api/models');response.raise_for_status()
        visible={m['id'] for m in response.json()['data'] if not m.get('info',{}).get('meta',{}).get('hidden')}
        assert set(desired)<=visible and not (set(catalog['retired_models']) & visible)
    except Exception:
        for rel in ('source/gateway/workstation_catalog.json','model-catalog.json'):shutil.copy2(backup/rel,ROOT/rel)
        if created:subprocess.run(['sudo','docker','rm','-f','haudi-openwebui'],capture_output=True)
        if renamed:run('sudo','docker','rename',previous,'haudi-openwebui')
        if stopped:run('sudo','docker','start','haudi-openwebui');healthy()
        for model in models:
            response=client.post('/api/v1/models/model/update',json=model);response.raise_for_status()
        raise
    finally:client.close()
    image=run('sudo','docker','inspect','haudi-openwebui','--format','{{.Image}}')
    record={'image':image,'tag':TAG,'release':str(release),'backup':str(backup),'previous_container':previous,
            'archive_sha256':hashlib.sha256((ROOT/'model-release.tar.gz').read_bytes()).hexdigest()}
    (ROOT/'openwebui/image.txt').write_text(image+'\n')
    (ROOT/'openwebui/model-status-deployment.json').write_text(json.dumps(record,indent=2))
    print(json.dumps(record),flush=True)

if __name__=='__main__':main()
