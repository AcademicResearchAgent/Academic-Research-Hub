set -euo pipefail
deploy_root=/home/ubuntu/haudi-hermes
mkdir -p "$deploy_root"/{runtime,state,workspace,logs}
chmod 700 "$deploy_root/state"
cd "$deploy_root"
if [ ! -f source/pyproject.toml ]; then
  curl -fL --retry 3 --connect-timeout 15 --max-time 600 https://codeload.github.com/NousResearch/hermes-agent/tar.gz/693641aa8b4359c602283bdbbc14041e03bc47bc -o runtime/source.tar.gz
  if [ -d source ]; then mv source source-fetch-incomplete; fi
  mkdir source
  tar -xzf runtime/source.tar.gz --strip-components=1 -C source
  printf '%s\n' 693641aa8b4359c602283bdbbc14041e03bc47bc > source/.source-revision
fi
echo SOURCE_READY
if [ ! -x runtime/node/bin/node ]; then
  python3 - <<'PY'
import json, urllib.request
from pathlib import Path
releases=json.load(urllib.request.urlopen('https://nodejs.org/dist/index.json',timeout=30))
version=next(r['version'] for r in releases if r['version'].startswith('v24.') and r['lts'])
Path('runtime/node-version').write_text(version)
print('Node release:', version)
PY
  node_version=$(cat runtime/node-version)
  curl -fL --retry 3 --connect-timeout 15 --max-time 600 "https://nodejs.org/dist/$node_version/node-$node_version-linux-x64.tar.xz" -o runtime/node.tar.xz
  curl -fsSL --retry 3 "https://nodejs.org/dist/$node_version/SHASUMS256.txt" -o runtime/node-shasums.txt
  expected=$(awk -v file="node-$node_version-linux-x64.tar.xz" '$2==file {print $1}' runtime/node-shasums.txt)
  printf '%s  %s\n' "$expected" runtime/node.tar.xz | sha256sum -c -
  mkdir -p runtime/node
  tar -xJf runtime/node.tar.xz --strip-components=1 -C runtime/node
fi
export PATH="$deploy_root/runtime/node/bin:$PATH"
node --version
npm --version
if [ ! -x runtime/uv-bin/uv ]; then
  python3 - <<'PY'
import hashlib, io, json, urllib.request, zipfile
from pathlib import Path
meta=json.load(urllib.request.urlopen('https://pypi.org/pypi/uv/json',timeout=30))
wheel=next(f for f in meta['urls'] if f['filename'].endswith('.whl') and 'manylinux' in f['filename'] and 'x86_64' in f['filename'])
data=urllib.request.urlopen(wheel['url'],timeout=120).read()
assert hashlib.sha256(data).hexdigest()==wheel['digests']['sha256'], 'uv checksum mismatch'
with zipfile.ZipFile(io.BytesIO(data)) as archive:
    item=next(n for n in archive.namelist() if n.endswith('/uv'))
    dest=Path('runtime/uv-bin/uv')
    dest.parent.mkdir(exist_ok=True)
    dest.write_bytes(archive.read(item))
    dest.chmod(0o755)
print('uv wheel verified:',meta['info']['version'])
PY
fi
export PATH="$deploy_root/runtime/uv-bin:$PATH"
uv venv --allow-existing --python /usr/bin/python3 "$deploy_root/venv"
uv pip install --python "$deploy_root/venv/bin/python" -e "$deploy_root/source[web,pty]"
echo PYTHON_READY
cd source
npm ci --workspace web --workspace ui-tui --workspace apps/shared --workspace ui-tui/packages/hermes-ink --include-workspace-root --no-audit --no-fund
npm run build --workspace ui-tui
npm run build --workspace web
echo BUILD_READY
