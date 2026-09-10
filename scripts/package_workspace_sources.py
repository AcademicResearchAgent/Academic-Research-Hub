"""Package non-secret workspace sources for independent Linux integration checks."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
files={}
for directory in ('overlays/open-webui/workstation_workspace','overlays/open-webui/workstation_models','deploy/workspaces'):
    for path in (ROOT/directory).rglob('*'):
        if path.is_file() and path.suffix=='.py' and '__pycache__' not in path.parts:
            files[path.relative_to(ROOT).as_posix()]=path.read_bytes().replace(b'\r\n',b'\n')
for path in (ROOT/'tests').glob('test_workspace*.py'):
    files[path.relative_to(ROOT).as_posix()]=path.read_bytes().replace(b'\r\n',b'\n')
digest=hashlib.sha256()
for name,data in sorted(files.items()):digest.update(name.encode()+b'\0'+data)
manifest={'release':digest.hexdigest()[:16],'files':{n:hashlib.sha256(d).hexdigest() for n,d in files.items()}}
target=ROOT/'.build/workspace-sources.zip'
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
    for name,data in files.items():archive.writestr(name,data)
    archive.writestr('manifest.json',json.dumps(manifest,indent=2))
print(json.dumps({'release':manifest['release'],'files':len(files),'archive':str(target)}))
