"""Deploy the reviewed streaming release with source/image guards and rollback."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import tarfile
import time

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def healthy(port):
    for _ in range(90):
        try:
            if httpx.get(f'http://127.0.0.1:{port}/health', timeout=2, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise RuntimeError('Service did not become healthy on port ' + str(port))


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    with tarfile.open(ROOT / 'streaming-release.tar.gz') as archive:
        manifest = json.load(archive.extractfile('manifest.json'))
        release = ROOT / 'streaming-releases' / stamp
        release.mkdir(parents=True)
        for name, expected in manifest['files'].items():
            path = (release / name).resolve()
            assert path.is_relative_to(release.resolve())
            data = archive.extractfile(name).read()
            assert digest(data) == expected, 'Release checksum mismatch'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    files = list(manifest['baseline_engine'])
    for rel, expected in manifest['baseline_engine'].items():
        current = (ROOT / 'source' / rel).read_bytes()
        assert digest(current) in {expected, manifest['files']['reference/hermes-agent/' + rel]}, 'Unexpected engine source: ' + rel
        py_compile.compile(str(release / 'reference/hermes-agent' / rel), doraise=True)
    image = run('sudo', 'docker', 'inspect', 'haudi-openwebui', '--format', '{{.Image}}')
    assert image == manifest['baseline_image'], 'Unexpected current WebUI image; review before deployment'
    router_hash = run('sudo', 'docker', 'exec', 'haudi-openwebui', 'python', '-c',
                     'from pathlib import Path; import hashlib; print(hashlib.sha256(Path("/app/backend/open_webui/workstation_models/router.py").read_bytes().replace(b"\\r\\n", b"\\n")).hexdigest())')
    assert router_hash == manifest['baseline_router'], 'Unexpected deployed model router'
    (release / 'Dockerfile').write_text('FROM ' + image + '\nCOPY overlays/open-webui/workstation_models/ /app/backend/open_webui/workstation_models/\n')
    tag = 'haudi-openwebui:0.11.3-research-v6'
    run('sudo', 'docker', 'build', '-t', tag, str(release))
    run('sudo', 'docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python',
        '--mount', f'type=bind,src={release},dst=/work', '-w', '/work', tag,
        '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_workstation_streaming.py', '-v')
    print('New UI image built; stream bridge tests passed.', flush=True)
    backup = ROOT / 'streaming-backups' / stamp
    backup.mkdir(parents=True, mode=0o700)
    for rel in files:
        (backup / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'source' / rel, backup / rel)
    previous = 'haudi-openwebui-before-streaming-' + stamp
    stopped = renamed = created = False
    try:
        for rel in files:
            shutil.copy2(release / 'reference/hermes-agent' / rel, ROOT / 'source' / rel)
        run(str(ROOT / 'venv/bin/python'), '-m', 'unittest', 'discover', '-s', str(release / 'tests'),
            '-p', 'test_hermes_reasoning_stream.py', '-v',
            env={**os.environ, 'WORKSTATION_HERMES_SOURCE': str(ROOT / 'source')})
        run('sudo', 'systemctl', 'restart', 'haudi-hermes-api.service')
        healthy(8642)
        run('sudo', 'docker', 'stop', 'haudi-openwebui')
        stopped = True
        run('sudo', 'docker', 'rename', 'haudi-openwebui', previous)
        renamed = True
        created = True
        run('sudo', 'docker', 'run', '-d', '--name', 'haudi-openwebui', '--network', 'host',
            '--restart', 'unless-stopped', '--env-file', str(ROOT / 'openwebui/container.env'), '-e', 'PORT=9119',
            '--mount', f'type=bind,src={ROOT}/openwebui/data,dst=/app/backend/data', tag)
        healthy(9119)
    except Exception:
        for rel in files:
            shutil.copy2(backup / rel, ROOT / 'source' / rel)
        run('sudo', 'systemctl', 'restart', 'haudi-hermes-api.service')
        if created:
            subprocess.run(['sudo', 'docker', 'rm', '-f', 'haudi-openwebui'], capture_output=True)
        if renamed:
            run('sudo', 'docker', 'rename', previous, 'haudi-openwebui')
        if stopped:
            run('sudo', 'docker', 'start', 'haudi-openwebui')
        raise
    image = run('sudo', 'docker', 'inspect', 'haudi-openwebui', '--format', '{{.Image}}')
    record = {'release': manifest['release'], 'path': str(release), 'image': image, 'tag': tag,
              'backup': str(backup), 'previous_container': previous, 'previous_image': manifest['baseline_image']}
    (ROOT / 'openwebui/streaming-deployment.json').write_text(json.dumps(record, indent=2))
    (ROOT / 'openwebui/image.txt').write_text(image + '\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
