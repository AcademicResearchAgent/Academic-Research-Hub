"""Upgrade the pinned v8 UI and tool receipts, with source guards and rollback."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')
BASE = 'sha256:4d985c52e1b09c9574a16ec876ada7a35cbfba5312231618313562fc3883e6ab'
TAG = 'haudi-openwebui:0.11.3-research-v9'
ROUTE = 'gateway/platforms/api_server_openai_routes.py'
ACTIVITY = 'gateway/workstation_activity.py'


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def healthy(port):
    for _ in range(90):
        try:
            if httpx.get(f'http://127.0.0.1:{port}/health', timeout=2, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise RuntimeError(f'Service health check failed on {port}')


def main():
    assert run('sudo', 'docker', 'inspect', 'haudi-openwebui', '--format', '{{.Image}}') == BASE, 'Expected v8 baseline'
    assert digest(ROOT / 'source' / ROUTE) == 'fdd1308fb711f96cc8f0e2b5cb1ce23b6d577d1e0e93b5729f9db2c69342535a', 'Engine has changed'
    assert digest(ROOT / 'state/SOUL.md') == '338ff0074628dfc8c91634dfea5d00e586e4425b816338bf0fc9f9e2e9bbb257', 'SOUL has changed'
    assert not (ROOT / 'source' / ACTIVITY).exists(), 'Activity module already exists'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    release = ROOT / 'model-releases' / stamp
    release.mkdir(parents=True)
    with tarfile.open(ROOT / 'model-release.tar.gz') as archive:
        archive.extractall(release, filter='data')
    (release / 'Dockerfile').write_text('FROM ' + BASE + '\nCOPY reference/open-webui/build/ /app/build/\nCOPY overlays/open-webui/workstation_models/ /app/backend/open_webui/workstation_models/\n')
    run('sudo', 'docker', 'build', '-t', TAG, str(release))
    for pattern in ('test_workstation_streaming.py', 'test_workstation_activity.py'):
        run('sudo', 'docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python',
            '--mount', f'type=bind,src={release},dst=/work', '-w', '/work', TAG,
            '-m', 'unittest', 'discover', '-s', 'tests', '-p', pattern, '-v')
    print('UI built; activity and stream tests passed.', flush=True)
    backup = ROOT / 'activity-backups' / stamp
    backup.mkdir(parents=True, mode=0o700)
    shutil.copy2(ROOT / 'source' / ROUTE, backup / 'api_server_openai_routes.py')
    shutil.copy2(ROOT / 'state/SOUL.md', backup / 'SOUL.md')
    previous = 'haudi-openwebui-before-activity-' + stamp
    stopped = renamed = created = False
    try:
        for rel in (ROUTE, ACTIVITY):
            shutil.copy2(release / 'reference/hermes-agent' / rel, ROOT / 'source' / rel)
        shutil.copy2(release / 'configs/workstation/SOUL.md', ROOT / 'state/SOUL.md')
        run(str(ROOT / 'venv/bin/python'), '-m', 'unittest', 'discover', '-s', str(release / 'tests'),
            '-p', 'test_hermes_reasoning_stream.py', '-v',
            env={**os.environ, 'WORKSTATION_HERMES_SOURCE': str(ROOT / 'source')})
        run('sudo', 'systemctl', 'restart', 'haudi-hermes-api.service')
        healthy(8642)
        run('sudo', 'docker', 'stop', 'haudi-openwebui'); stopped = True
        run('sudo', 'docker', 'rename', 'haudi-openwebui', previous); renamed = True
        created = True
        run('sudo', 'docker', 'run', '-d', '--name', 'haudi-openwebui', '--network', 'host', '--restart', 'unless-stopped',
            '--env-file', str(ROOT / 'openwebui/container.env'), '-e', 'PORT=9119',
            '--mount', f'type=bind,src={ROOT}/openwebui/data,dst=/app/backend/data', TAG)
        healthy(9119)
    except Exception:
        shutil.copy2(backup / 'api_server_openai_routes.py', ROOT / 'source' / ROUTE)
        shutil.copy2(backup / 'SOUL.md', ROOT / 'state/SOUL.md')
        (ROOT / 'source' / ACTIVITY).unlink(missing_ok=True)
        run('sudo', 'systemctl', 'restart', 'haudi-hermes-api.service')
        if created:
            subprocess.run(['sudo', 'docker', 'rm', '-f', 'haudi-openwebui'], capture_output=True)
        if renamed:
            run('sudo', 'docker', 'rename', previous, 'haudi-openwebui')
        if stopped:
            run('sudo', 'docker', 'start', 'haudi-openwebui')
        raise
    image = run('sudo', 'docker', 'inspect', 'haudi-openwebui', '--format', '{{.Image}}')
    record = {'image': image, 'tag': TAG, 'release': str(release), 'backup': str(backup),
              'previous_container': previous, 'previous_image': BASE,
              'archive_sha256': hashlib.sha256((ROOT / 'model-release.tar.gz').read_bytes()).hexdigest()}
    (ROOT / 'openwebui/image.txt').write_text(image + '\n')
    (ROOT / 'openwebui/activity-deployment.json').write_text(json.dumps(record, indent=2))
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
