import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

meta=json.load(urllib.request.urlopen('https://pypi.org/pypi/uv/json',timeout=30))
wheel=next(f for f in meta['urls'] if f['filename'].endswith('.whl') and 'manylinux' in f['filename'] and 'x86_64' in f['filename'])
print('Downloading:',wheel['filename'],flush=True)
data=urllib.request.urlopen(wheel['url'],timeout=120).read()
assert hashlib.sha256(data).hexdigest()==wheel['digests']['sha256'], 'uv checksum mismatch'
with zipfile.ZipFile(io.BytesIO(data)) as archive:
    item=next(n for n in archive.namelist() if n.endswith('/uv'))
    dest=Path(__file__).resolve().parent/'.cache/uv-linux'
    dest.write_bytes(archive.read(item))
print('uv download verified',flush=True)
