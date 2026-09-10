"""Stage the workspace UI on loopback port 9120 without altering production."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import time
import httpx

ROOT=Path('/home/ubuntu/haudi-hermes')
BASE='sha256:3bdcf3f6ffcf90fdb8092c4e1ed165424d61dedb3d93d5e939a6000d043a1876'


def run(*args):
    return subprocess.check_output(args,text=True).strip()


def main():
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--resume-release', help='Resume an inspected, built release before its preview started')
    mode.add_argument('--replace-preview', action='store_true', help='Build first, then replace only the recorded preview; preserve its data and prior container')
    args=parser.parse_args()
    if os.geteuid()!=0:
        raise RuntimeError('Run with sudo: cloning the private UI database requires root access')
    assert run('sudo','docker','inspect','haudi-openwebui','--format','{{.Image}}')==BASE,'Production baseline changed'
    preview='haudi-openwebui-workspace-preview'
    exists=preview in run('sudo','docker','ps','-a','--format','{{.Names}}').splitlines()
    old_record=None
    if args.replace_preview:
        old_record=json.loads((ROOT/'workspace-preview.json').read_text())
        assert exists and run('sudo','docker','inspect',preview,'--format','{{.Image}}')==old_record['image'],'Preview state changed'
    elif exists:
        raise RuntimeError('A preview already exists; inspect it before replacing')
    archive=ROOT/'model-release.tar.gz'
    if args.resume_release:
        release=Path(args.resume_release).resolve()
        if release.parent!=(ROOT/'workspace-releases').resolve() or not (release/'Dockerfile').is_file():
            raise RuntimeError('Resume target must be an existing workspace release')
        tag='haudi-openwebui:0.11.3-workspaces-'+release.name
        run('sudo','docker','image','inspect',tag,'--format','{{.Id}}')
    else:
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        release=ROOT/'workspace-releases'/stamp
        release.mkdir(parents=True,mode=0o700)
        with tarfile.open(archive) as source:
            source.extractall(release,filter='data')
        (release/'Dockerfile').write_text('FROM '+BASE+'\nCOPY reference/open-webui/build/ /app/build/\nCOPY reference/open-webui/backend/open_webui/ /app/backend/open_webui/\n')
        tag='haudi-openwebui:0.11.3-workspaces-'+stamp
        subprocess.run(['sudo','docker','build','-t',tag,str(release)],check=True)
    data=ROOT/'workspace-preview-data'
    if not args.replace_preview and data.exists() and (not args.resume_release or any(data.iterdir())):
        raise RuntimeError('Preview data already exists; do not overwrite a database that may have been used')
    data.mkdir(mode=0o700,exist_ok=True)
    for name in ('webui.db','workstation-credentials.db'):
        if args.replace_preview:
            continue
        source=ROOT/'openwebui/data'/name
        if source.exists():
            with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(data/name) as dst:src.backup(dst)
            (data/name).chmod(0o600)
    workspaces=ROOT/'workspace-preview-store';workspaces.mkdir(exist_ok=True,mode=0o700)
    socket_dir=ROOT/'workspace-broker';socket_dir.mkdir(exist_ok=True,mode=0o700)
    previous=None
    if args.replace_preview:
        previous=preview+'-previous-'+release.name
        (release/'previous-preview.json').write_text(json.dumps(old_record,indent=2))
        run('sudo','docker','stop','--time','10',preview)
        run('sudo','docker','rename',preview,previous)
    subprocess.run(['sudo','docker','run','-d','--name','haudi-openwebui-workspace-preview',
        '--network','host','--memory','1024m','--memory-swap','1536m','--cpus','1',
        '--env-file',str(ROOT/'openwebui/container.env'),'-e','PORT=9120',
        '-e','WORKSTATION_WORKSPACE_ROOT=/app/workspaces',
        '-e','WORKSTATION_BROKER_SOCKET=/app/workspace-broker/broker.sock',
        '-e','OFFLINE_MODE=true','-e','HF_HUB_OFFLINE=1',
        '--mount',f'type=bind,src={data},dst=/app/backend/data',
        '--mount',f'type=bind,src={workspaces},dst=/app/workspaces',
        '--mount',f'type=bind,src={socket_dir},dst=/app/workspace-broker',tag],check=True)
    healthy=False
    for _ in range(90):
        try:
            if httpx.get('http://127.0.0.1:9120/health',timeout=2).status_code==200:
                healthy=True;break
        except httpx.HTTPError:pass
        time.sleep(2)
    record={'release':str(release),'tag':tag,'image':run('sudo','docker','inspect','haudi-openwebui-workspace-preview','--format','{{.Image}}'),
            'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'preview_healthy':healthy,
            'workspace_root':str(workspaces),'data':str(data),'production_unchanged':True}
    (ROOT/'workspace-preview.json').write_text(json.dumps(record,indent=2))
    print(json.dumps(record),flush=True)
    if not healthy:raise RuntimeError('Preview did not become healthy; inspect its container logs')


if __name__=='__main__':main()
