"""Stage non-secret deployment artifacts with the filenames expected by existing server scripts."""
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'.build/deploy'
FILES={
 'configs/workstation/research-copy.json':'research-copy.json',
 'configs/workstation/SOUL.md':'research-SOUL.md',
 'configs/workstation/retrieval.json':'retrieval.json',
 'overlays/open-webui/screen-capture.js':'screen-capture.js',
 **{f'deploy/hermes/{name}':name for name in (
 'build-research-copy.py','configure-research-copy.py','apply-workstation-identity.py',
 'build-workstation-branding.sh','configure-research-copy.sh','deploy-research-copy.sh',
 'deploy-workstation-identity.sh','verify-research-copy.sh','verify-workstation-identity.sh',
 'install-retrieval-model.py','install-retrieval-model.sh','configure-retrieval.py','configure-retrieval.sh',
 'verify-retrieval.py','verify-retrieval.sh','reindex-failed-files.sh')},
}
TARGET.mkdir(parents=True,exist_ok=True)
for source,destination in FILES.items():
    shutil.copyfile(ROOT/source,TARGET/destination)
(TARGET/'manifest.json').write_text(json.dumps(FILES,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'Staged {len(FILES)} non-secret artifacts in {TARGET}. Nothing uploaded or deployed.')
