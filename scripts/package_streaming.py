"""Package streaming changes with hashes of the baseline they replace."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ('gateway/platforms/api_server.py', 'gateway/platforms/api_server_openai_routes.py')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main(baseline_ref='HEAD'):
    lock = json.loads(git('show', baseline_ref + ':sources.lock.json'))
    base = ROOT / '.build'
    base.mkdir(exist_ok=True)
    # Reconstruct the committed product baseline in a scratch directory, without
    # changing either the actual checkout or its index.
    with tempfile.TemporaryDirectory(prefix='stream-base-', dir=base) as name:
        scratch = Path(name)
        patch = git('show', baseline_ref + ':patches/hermes-agent/0001-workstation-identity.patch')
        for line in patch.decode().splitlines():
            if line.startswith('--- a/'):
                relative = line[6:]
                target = scratch / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(git('-C', str(ROOT / 'reference/hermes-agent'), 'show',
                                      lock['sources']['hermes-agent']['commit'] + ':' + relative))
        patchfile = base / 'streaming-baseline.patch'
        patchfile.write_bytes(patch)
        subprocess.run(['git', 'apply', '--directory=' + scratch.relative_to(ROOT).as_posix(), str(patchfile)], cwd=ROOT, check=True)
        baseline = {rel: hashlib.sha256((scratch / rel).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for rel in ENGINE}
    paths = [*('reference/hermes-agent/' + rel for rel in ENGINE),
             'overlays/open-webui/workstation_models/router.py', 'overlays/open-webui/workstation_models/streaming.py',
             'tests/test_workstation_streaming.py', 'tests/test_hermes_reasoning_stream.py']
    files = {rel: (ROOT / rel).read_bytes().replace(b'\r\n', b'\n') for rel in paths}
    digest = hashlib.sha256(b''.join(n.encode() + b'\0' + d for n, d in sorted(files.items()))).hexdigest()[:16]
    old_router = git('show', baseline_ref + ':overlays/open-webui/workstation_models/router.py').replace(b'\r\n', b'\n')
    manifest = {'release': digest, 'baseline_engine': baseline,
                'baseline_router': hashlib.sha256(old_router).hexdigest(),
                'baseline_image': lock['production']['custom_image'],
                'files': {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}}
    files['manifest.json'] = json.dumps(manifest, indent=2).encode()
    target = base / 'streaming-release.tar.gz'
    with tarfile.open(target, 'w:gz') as archive:
        for path, data in files.items():
            info = tarfile.TarInfo(path)
            info.size, info.mode = len(data), 0o644
            archive.addfile(info, io.BytesIO(data))
    print(json.dumps({'release': digest, 'archive': str(target), 'baseline_engine': baseline}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline-ref', default='HEAD', help='Git revision describing the currently deployed baseline')
    main(parser.parse_args().baseline_ref)
