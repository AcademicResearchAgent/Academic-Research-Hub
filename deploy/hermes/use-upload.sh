set -euo pipefail
cd /home/ubuntu/haudi-hermes
printf '%s  %s\n' a29debcfd09013fe9a91d9756c765aafbc7742de24ae7f513aec3c92467d00c4 runtime/source-upload.tar.gz | sha256sum -c -
python3 - <<'PY'
import os, signal
from pathlib import Path
url=b'https://codeload.github.com/NousResearch/hermes-agent/tar.gz/693641aa8b4359c602283bdbbc14041e03bc47bc'
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit(): continue
    try:
        args=(entry/'cmdline').read_bytes().split(b'\0')
        if args and args[0].rsplit(b'/',1)[-1]==b'curl' and url in args:
            os.kill(int(entry.name),signal.SIGTERM)
            print('Stopped slow source download:',entry.name)
    except (ProcessLookupError, PermissionError, FileNotFoundError): pass
PY
if [ -d source ] && [ ! -f source/pyproject.toml ]; then mv source source-fetch-incomplete; fi
mkdir -p source
tar -xzf runtime/source-upload.tar.gz -C source
printf '%s\n' 693641aa8b4359c602283bdbbc14041e03bc47bc > source/.source-revision
echo SOURCE_READY
