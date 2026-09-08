"""Fetch the public upstream OCI image locally for a faster SSH-assisted import."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import tarfile
import time
import urllib.request

repo = 'open-webui/open-webui'
base = 'https://ghcr.io/v2/' + repo
root = Path(__file__).resolve().parent / '.cache' / 'openwebui-oci'
blobdir = root / 'blobs' / 'sha256'
blobdir.mkdir(parents=True, exist_ok=True)
with urllib.request.urlopen('https://ghcr.io/token?scope=repository:' + repo + ':pull', timeout=45) as r:
    token = json.load(r)['token']
headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json'}

def get_manifest(ref):
    req = urllib.request.Request(base + '/manifests/' + ref, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    digest = hashlib.sha256(data).hexdigest()
    (blobdir / digest).write_bytes(data)
    return json.loads(data), {'mediaType': json.loads(data)['mediaType'], 'digest': 'sha256:' + digest, 'size': len(data)}

index, _ = get_manifest('main-slim')
desc = next(d for d in index['manifests'] if d.get('platform', {}).get('architecture') == 'amd64' and d['platform']['os'] == 'linux')
manifest, desc = get_manifest(desc['digest'])
print('Linux amd64 image:', desc['digest'], flush=True)
blobs = [manifest['config'], *manifest['layers']]
print('Compressed image size: %.1f MiB' % (sum(b['size'] for b in blobs) / 2**20), flush=True)

def fetch(blob):
    digest = blob['digest'].split(':')[1]
    target = blobdir / digest
    if target.exists() and target.stat().st_size == blob['size']:
        if hashlib.file_digest(target.open('rb'), 'sha256').hexdigest() == digest:
            return
    if blob['size'] > 100 * 2**20:
        chunk_size = 256 * 1024
        old_chunkdir = root.parent / ('chunks-' + digest[:12])
        chunkdir = root.parent / ('chunks256k-' + digest[:12])
        chunkdir.mkdir(exist_ok=True)
        part = target.with_suffix('.part')
        def chunk(start):
            end = min(start + chunk_size, blob['size']) - 1
            dest = chunkdir / str(start)
            expected = end - start + 1
            if dest.exists() and dest.stat().st_size == expected: return dest
            previous_start = start // (4 * 2**20) * (4 * 2**20)
            previous = root.parent / ('chunks4m-' + digest[:12]) / str(previous_start)
            if previous.exists() and previous.stat().st_size >= end + 1 - previous_start:
                with previous.open('rb') as source:
                    source.seek(start - previous_start)
                    dest.write_bytes(source.read(expected))
                return dest
            old_start = start // (32 * 2**20) * (32 * 2**20)
            old_chunk = old_chunkdir / str(old_start)
            if old_chunk.exists() and old_chunk.stat().st_size >= end + 1 - old_start:
                with old_chunk.open('rb') as source:
                    source.seek(start - old_start)
                    dest.write_bytes(source.read(expected))
                return dest
            if part.exists() and part.stat().st_size >= end + 1:
                with part.open('rb') as source:
                    source.seek(start)
                    dest.write_bytes(source.read(expected))
                return dest
            for attempt in range(8):
                try:
                    started = time.monotonic()
                    req = urllib.request.Request(base + '/blobs/' + blob['digest'], headers={**headers, 'Range': f'bytes={start}-{end}'})
                    with urllib.request.urlopen(req, timeout=10) as r, dest.open('wb') as out:
                        assert r.status == 206 and r.headers['Content-Range'].startswith(f'bytes {start}-{end}/')
                        while block := r.read(64 * 1024):
                            out.write(block)
                            if time.monotonic() - started > 12:
                                raise TimeoutError('Retrying slow public registry connection')
                    assert dest.stat().st_size == expected
                    print('Downloaded %s chunk %d/%d' % (digest[:12], start//chunk_size+1, (blob['size']+chunk_size-1)//chunk_size), flush=True)
                    return dest
                except Exception:
                    if attempt == 7: raise
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            chunks = list(pool.map(chunk, range(0, blob['size'], chunk_size)))
        sha = hashlib.sha256()
        with target.with_suffix('.assembled').open('wb') as out:
            for path in chunks:
                with path.open('rb') as source:
                    while block := source.read(1024 * 1024):
                        out.write(block)
                        sha.update(block)
        assert sha.hexdigest() == digest, 'Registry blob digest mismatch'
        target.with_suffix('.assembled').replace(target)
        print('Verified large layer: ' + digest[:12], flush=True)
        return
    for attempt in range(3):
        try:
            start = time.monotonic()
            sha = hashlib.sha256()
            req = urllib.request.Request(base + '/blobs/' + blob['digest'], headers=headers)
            with urllib.request.urlopen(req, timeout=90) as r, target.with_suffix('.part').open('wb') as out:
                while block := r.read(1024 * 1024):
                    out.write(block)
                    sha.update(block)
            assert sha.hexdigest() == digest, 'Registry blob digest mismatch'
            target.with_suffix('.part').replace(target)
            print('Layer %s: %.1f MiB in %.1fs' % (digest[:12], blob['size']/2**20, time.monotonic()-start), flush=True)
            return
        except Exception:
            if attempt == 2: raise

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    list(pool.map(fetch, blobs))
desc['annotations'] = {'org.opencontainers.image.ref.name': 'ghcr.io/open-webui/open-webui:haudi-pinned'}
(root / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')
(root / 'index.json').write_text(json.dumps({'schemaVersion': 2, 'manifests': [desc]}))
archive = root.parent / 'openwebui-image.tar'
with tarfile.open(archive, 'w') as tar:
    for path in root.rglob('*'):
        if path.is_file() and not path.name.endswith('.part'):
            tar.add(path, arcname=path.relative_to(root).as_posix())
print('Verified OCI archive ready:', archive, flush=True)
