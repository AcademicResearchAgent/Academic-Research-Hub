"""Build the locked UI and record the real Node exit status and source identity."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'reference/open-webui'
node = ROOT / '.build/toolchain/node-v22.16.0-win-x64/node.exe'
if not node.is_file():
    node = Path(shutil.which('node') or 'node')
env = {**os.environ, 'NODE_OPTIONS': '--max-old-space-size=8192',
       'PATH': str(node.parent) + os.pathsep + os.environ.get('PATH', '')}
log = ROOT / '.build/workspace-ui-build.log'
with log.open('w', encoding='utf-8') as output:
    result = subprocess.run([str(node), 'node_modules/vite/bin/vite.js', 'build'], cwd=UI,
                            env=env, stdout=output, stderr=subprocess.STDOUT)
if result.returncode:
    raise SystemExit(f'Frontend build failed ({result.returncode}); inspect {log}')
digest = hashlib.sha256()
for path in sorted((UI / 'src').rglob('*')):
    if path.is_file():
        digest.update(path.relative_to(UI).as_posix().encode() + b'\0' + path.read_bytes())
record = {'status': 'passed', 'source_sha256': digest.hexdigest(),
          'index_sha256': hashlib.sha256((UI / 'build/index.html').read_bytes()).hexdigest()}
(ROOT / '.build/workspace-ui-build.json').write_text(json.dumps(record, indent=2))
print(json.dumps(record))
