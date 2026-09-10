"""Build a workspace UI candidate and capture compatible deployment targets.

Does not switch running services or restore persistent data. Use release-control
with the generated scope-specific checkpoint after validating the candidate.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
from datetime import datetime, timezone

ROOT = Path('/home/ubuntu/haudi-hermes')


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    runtime = json.loads((ROOT / 'workspace-broker-production.json').read_text())
    entry = ROOT / 'workspace-source-releases' / runtime['source_release'] / 'deploy/workspaces/release-control.py'
    spec = importlib.util.spec_from_file_location('ui_release_control', entry)
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    production = control.validate(control.configuration('production'))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    release = ROOT / 'workspace-releases' / stamp
    release.mkdir(mode=0o700, parents=True)
    archive = ROOT / 'model-release.tar.gz'
    with tarfile.open(archive) as source:
        source.extractall(release, filter='data')
    build = json.loads((release / 'workspace-ui-build.json').read_text())
    assert build['status'] == 'passed'
    assert hashlib.sha256((release / 'reference/open-webui/build/index.html').read_bytes()).hexdigest() == build['index_sha256']
    (release / 'Dockerfile').write_text('FROM ' + production['ui']['image'] + '\nCOPY reference/open-webui/build/ /app/build/\nCOPY reference/open-webui/backend/open_webui/ /app/backend/open_webui/\n')
    tag = 'haudi-openwebui:workspaces-' + stamp
    subprocess.run(['docker', 'build', '-t', tag, str(release)], check=True)
    image = control.command('docker', 'image', 'inspect', tag, '--format', '{{.Id}}')
    targets = {}
    for scope in ('preview', 'production'):
        current = control.validate(control.configuration(scope))
        before = ROOT / 'workspace-release-checkpoints' / (scope + '-before-' + stamp + '.json')
        before.write_text(json.dumps(current, indent=2))
        updated = {**current, 'ui': {**current['ui'], 'image': image, 'release': str(release),
                   'package_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), **build}}
        target = ROOT / 'workspace-release-checkpoints' / (scope + '-candidate-' + stamp + '.json')
        target.write_text(json.dumps(updated, indent=2))
        targets[scope] = {'target': str(target), 'previous': str(before), 'expected_image': current['ui']['image']}
    result = {'image': image, 'release': str(release), 'targets': targets,
              'services_changed': False, 'built_at': datetime.now(timezone.utc).isoformat()}
    (release / 'candidate.json').write_text(json.dumps(result, indent=2))
    (ROOT / 'workspace-ui-candidate.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
