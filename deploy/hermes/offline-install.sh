set -euo pipefail
deploy_root=/home/ubuntu/haudi-hermes
python3 - <<'PY'
import os, signal
from pathlib import Path
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit(): continue
    try:
        args=(entry/'cmdline').read_bytes().split(b'\0')
        if len(args)>2 and args[0].rsplit(b'/',1)[-1]==b'uv' and args[1:3]==[b'pip',b'install'] and b'/home/ubuntu/haudi-hermes/source[web,pty]' in args:
            os.kill(int(entry.name),signal.SIGTERM)
            print('Stopped slow online dependency resolution:',entry.name)
    except (ProcessLookupError, PermissionError, FileNotFoundError): pass
PY
cd "$deploy_root/runtime"
tar -xzf python-wheels.tar.gz
export PATH="$deploy_root/runtime/uv-bin:$deploy_root/runtime/node/bin:$deploy_root/venv/bin:$PATH"
uv pip install --python "$deploy_root/venv/bin/python" --no-index --find-links wheels --require-hashes -r requirements-linux.txt
uv pip install --python "$deploy_root/venv/bin/python" --no-index --find-links wheels setuptools==83.0.0 wheel==0.48.0
uv pip install --python "$deploy_root/venv/bin/python" --no-index --no-deps --no-build-isolation -e "$deploy_root/source"
echo PYTHON_READY
cd "$deploy_root/source"
npm ci --workspace web --workspace ui-tui --workspace apps/shared --workspace ui-tui/packages/hermes-ink --include-workspace-root --no-audit --no-fund
npm run build --workspace ui-tui
npm run build --workspace web
echo BUILD_READY
