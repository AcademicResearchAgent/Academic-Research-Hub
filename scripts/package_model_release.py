"""Package a complete frontend build and matching reviewed backend source, without secrets."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]
subprocess.run(['python',str(ROOT/'scripts/prepare_sources.py'),'--check'],check=True)
build=ROOT/'reference/open-webui/build'
assert (build/'index.html').exists(),'Run the frontend production build first'
files={}
workspace_build=ROOT/'.build/workspace-ui-build.json'
if workspace_build.exists():
    proof=json.loads(workspace_build.read_text())
    digest=hashlib.sha256()
    for p in sorted((ROOT/'reference/open-webui/src').rglob('*')):
        if p.is_file():digest.update(p.relative_to(ROOT/'reference/open-webui').as_posix().encode()+b'\0'+p.read_bytes())
    assert digest.hexdigest()==proof['source_sha256'],'Frontend sources changed after the verified build'
    files['workspace-ui-build.json']=workspace_build
for p in build.rglob('*'):
    if p.is_file() and p.suffix!='.map':files[p.relative_to(ROOT).as_posix()]=p
for rel in ('backend/open_webui/main.py','backend/open_webui/env.py','backend/open_webui/utils/chat.py','backend/open_webui/routers/files.py'):
    files['reference/open-webui/'+rel]=ROOT/'reference/open-webui'/rel
for p in (ROOT/'reference/open-webui/backend/open_webui/workstation_models').iterdir():
    if p.suffix in ('.py','.json'):files[p.relative_to(ROOT).as_posix()]=p
for p in (ROOT/'reference/open-webui/backend/open_webui/workstation_workspace').glob('*.py'):
    files[p.relative_to(ROOT).as_posix()]=p
for directory in ('overlays/open-webui/workstation_workspace','deploy/workspaces'):
    for p in (ROOT/directory).rglob('*'):
        if p.is_file() and p.suffix=='.py' and '__pycache__' not in p.parts:
            files[p.relative_to(ROOT).as_posix()]=p
for p in (ROOT/'tests').glob('test_workspace*.py'):
    files[p.relative_to(ROOT).as_posix()]=p
for rel in ('gateway/platforms/api_server.py','gateway/platforms/api_server_openai_routes.py','gateway/workstation_runtime.py','gateway/workstation_catalog.json','gateway/workstation_activity.py'):
    files['reference/hermes-agent/'+rel]=ROOT/'reference/hermes-agent'/rel
for rel in ('overlays/open-webui/workstation_models/core.py','tests/test_workstation_models.py',
            'tests/test_workstation_model_api.py','configs/workstation/model-catalog.json',
            'deploy/hermes/configure-model-catalog.py','deploy/hermes/build-model-release.sh',
            'deploy/hermes/deploy-model-runtime.py','deploy/hermes/deploy-research-copy.sh',
            'deploy/hermes/verify-model-selection.py'):
    files[rel]=ROOT/rel
for p in (ROOT/'overlays/open-webui/workstation_models').glob('*.py'):
    files[p.relative_to(ROOT).as_posix()]=p
for p in (ROOT/'tests').glob('test_workstation*.py'):
    files[p.relative_to(ROOT).as_posix()]=p
for rel in ('tests/test_model_availability.py','deploy/hermes/deploy-model-status.py',
            'overlays/hermes-agent/workstation_activity.py','configs/workstation/SOUL.md',
            'deploy/hermes/deploy-research-activity.py','tests/test_hermes_reasoning_stream.py'):
    files[rel]=ROOT/rel
out=ROOT/'.build/model-release.tar.gz'
with tarfile.open(out,'w:gz',compresslevel=6) as archive:
    for rel,p in sorted(files.items()):archive.add(p,arcname=rel,recursive=False)
print(f'Packaged {len(files)} source/build files ({out.stat().st_size//1024//1024} MiB), SHA256 {hashlib.sha256(out.read_bytes()).hexdigest()}')
