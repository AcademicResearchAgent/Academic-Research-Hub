"""Publish the default-model frontend on the pinned v7 image with rollback."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import time
import httpx

ROOT=Path('/home/ubuntu/haudi-hermes')
BASE='sha256:5cf0afa93bb42dbf92c7d9b9b4b04ff4d001b1badee11e409dcf0812b3cb0b8c'
TAG='haudi-openwebui:0.11.3-research-v8'

def run(*args):return subprocess.check_output(args,text=True).strip()
def healthy():
    for _ in range(90):
        try:
            if httpx.get('http://127.0.0.1:9119/health',timeout=2,trust_env=False).status_code==200:return
        except httpx.HTTPError:pass
        time.sleep(2)
    raise RuntimeError('UI health check failed')

def main():
    assert run('sudo','docker','inspect','haudi-openwebui','--format','{{.Image}}')==BASE,'Expected v7 baseline'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    release=ROOT/'model-releases'/stamp;release.mkdir(parents=True)
    with tarfile.open(ROOT/'model-release.tar.gz') as archive:archive.extractall(release,filter='data')
    assert (release/'reference/open-webui/build/index.html').exists()
    (release/'Dockerfile').write_text('FROM '+BASE+'\nCOPY reference/open-webui/build/ /app/build/\n')
    run('sudo','docker','build','-t',TAG,str(release))
    print('Default model frontend image built.',flush=True)
    previous='haudi-openwebui-before-default-model-'+stamp
    stopped=renamed=created=False
    try:
        run('sudo','docker','stop','haudi-openwebui');stopped=True
        run('sudo','docker','rename','haudi-openwebui',previous);renamed=True
        created=True
        run('sudo','docker','run','-d','--name','haudi-openwebui','--network','host','--restart','unless-stopped',
            '--env-file',str(ROOT/'openwebui/container.env'),'-e','PORT=9119',
            '--mount',f'type=bind,src={ROOT}/openwebui/data,dst=/app/backend/data',TAG)
        healthy()
    except Exception:
        if created:subprocess.run(['sudo','docker','rm','-f','haudi-openwebui'],capture_output=True)
        if renamed:run('sudo','docker','rename',previous,'haudi-openwebui')
        if stopped:run('sudo','docker','start','haudi-openwebui');healthy()
        raise
    image=run('sudo','docker','inspect','haudi-openwebui','--format','{{.Image}}')
    record={'image':image,'tag':TAG,'release':str(release),'previous_container':previous,'previous_image':BASE,
            'archive_sha256':hashlib.sha256((ROOT/'model-release.tar.gz').read_bytes()).hexdigest()}
    (ROOT/'openwebui/image.txt').write_text(image+'\n')
    (ROOT/'openwebui/default-model-deployment.json').write_text(json.dumps(record,indent=2))
    print(json.dumps(record),flush=True)

if __name__=='__main__':main()
