set -euo pipefail
python3 - <<'PY'
import os, signal
from pathlib import Path
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit() or int(entry.name)==os.getpid(): continue
    try:
        args=(entry/'cmdline').read_bytes().split(b'\0')
        cwd=(entry/'cwd').resolve()
        if args[:2]==[b'python3',b'-'] and cwd==Path('/home/ubuntu/haudi-hermes'):
            os.kill(int(entry.name),signal.SIGTERM)
            print('Stopped slow uv download:',entry.name)
    except (ProcessLookupError, PermissionError, FileNotFoundError): pass
PY
cd /home/ubuntu/haudi-hermes
mkdir -p runtime/uv-bin
cp runtime/uv-linux runtime/uv-bin/uv
chmod 755 runtime/uv-bin/uv
runtime/uv-bin/uv --version
