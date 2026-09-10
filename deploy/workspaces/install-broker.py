"""Install the private preview broker from a verified immutable source release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')
SERVICE = 'haudi-workspace-broker-preview.service'


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def service_unit(source, workspace, socket, image, scope='preview'):
    assert scope in {'preview', 'production'}
    return '\n'.join([
        '[Unit]', 'Description=Research workspace isolated execution broker (' + scope + ')',
        'After=docker.service network-online.target', 'Requires=docker.service', '',
        '[Service]', 'Type=simple', 'User=root', 'Group=root', 'UMask=0077',
        'WorkingDirectory=' + str(ROOT),
        'Environment=PYTHONPATH=' + str(source / 'overlays/open-webui'),
        'Environment=WORKSTATION_WORKSPACE_ROOT=' + str(workspace),
        'Environment=WORKSTATION_BROKER_SOCKET=' + str(socket),
        'Environment=WORKSTATION_RUNTIME_IMAGE=' + image,
        'ExecStart=' + str(ROOT / 'venv/bin/python') + ' ' + str(source / 'deploy/workspaces/broker.py'),
        'Restart=on-failure', 'RestartSec=5', 'TimeoutStopSec=120',
        'NoNewPrivileges=true', 'PrivateTmp=true', '', '[Install]', 'WantedBy=multi-user.target', '',
    ])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source_release')
    parser.add_argument('--image', default='haudi-workspace-runtime:v1')
    args = parser.parse_args()
    assert os.geteuid() == 0, 'Run this installer with sudo'
    assert re.fullmatch(r'[0-9a-f]{16}', args.source_release), 'Invalid source release ID'
    source = ROOT / 'workspace-source-releases' / args.source_release
    assert (source / 'deploy/workspaces/broker.py').is_file()
    if subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0:
        raise RuntimeError('A broker is already active; inspect and stop its runs before replacing')
    image = run('docker', 'image', 'inspect', args.image, '--format', '{{.Id}}')
    assert re.fullmatch(r'sha256:[0-9a-f]{64}', image)
    preview = json.loads((ROOT / 'workspace-preview.json').read_text())
    assert preview['preview_healthy']
    workspace = ROOT / 'workspace-preview-store'
    socket = ROOT / 'workspace-broker/broker.sock'
    assert Path(preview['workspace_root']) == workspace
    unit = service_unit(source, workspace, socket, image)
    target = Path('/etc/systemd/system') / SERVICE
    target.write_text(unit)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', SERVICE)
    healthy = False
    for _ in range(20):
        try:
            with httpx.Client(transport=httpx.HTTPTransport(uds=str(socket)), timeout=2, trust_env=False) as client:
                if client.get('http://broker/health').status_code == 200:
                    healthy = True
                    break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    record = {'service': SERVICE, 'source_release': args.source_release, 'image': image,
              'broker_sha256': hashlib.sha256((source / 'deploy/workspaces/broker.py').read_bytes()).hexdigest(),
              'healthy': healthy, 'scope': 'preview', 'public_port': None}
    (ROOT / 'workspace-broker-preview.json').write_text(json.dumps(record, indent=2))
    print(json.dumps(record), flush=True)
    assert healthy, 'Broker health check failed; inspect its unit logs'


if __name__ == '__main__':
    main()
