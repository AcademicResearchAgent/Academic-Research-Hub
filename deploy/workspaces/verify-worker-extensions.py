"""Launch the current preview worker with synthetic files and run extensions."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')


def main():
    assert os.geteuid() == 0
    release = json.loads((ROOT / 'workspace-broker-preview.json').read_text())
    source = ROOT / 'workspace-source-releases' / release['source_release']
    test_root = ROOT / 'workspace-extension-checks' / secrets.token_hex(12)
    test_root.mkdir(parents=True, mode=0o700)
    os.environ.update(WORKSTATION_WORKSPACE_ROOT=str(test_root), WORKSTATION_BROKER_SOCKET=str(test_root / 'unused.sock'), WORKSTATION_RUNTIME_IMAGE=release['image'])
    sys.path.insert(0, str(source / 'overlays/open-webui'))
    spec = importlib.util.spec_from_file_location('checked_broker', source / 'deploy/workspaces/broker.py')
    broker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(broker)
    from workstation_workspace.runs import begin_run, finish_run, discard_completed_copy
    broker.STORE.ensure_thread('extension-fixture', 'extension-thread')
    run = begin_run(broker.STORE, 'extension-fixture', 'extension-thread')
    container = 'haudi-ws-' + run['id']
    try:
        _, port = broker.start_container(run, secrets.token_urlsafe(32))
        with httpx.Client(timeout=2, trust_env=False) as client:
            for _ in range(90):
                try:
                    if client.get(f'http://127.0.0.1:{port}/health').status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise AssertionError('Worker did not become healthy')
        code = Path(__file__).with_name('check-worker-extensions.py').read_text()
        result = subprocess.run(['docker', 'exec', '-i', '--user', '1000:1000', container, '/opt/venv/bin/python', '-'], input=code, text=True, capture_output=True, timeout=240)
        if result.returncode:
            # Contains only synthetic fixture diagnostics, never model keys.
            print(result.stdout[-3000:] + result.stderr[-5000:], flush=True)
            raise AssertionError('Worker extension check failed')
        report = json.loads(next(line.split('=', 1)[1] for line in result.stdout.splitlines() if line.startswith('EXTENSIONS_RESULT=')))
        broker.stop_container(container)
        collected = finish_run(broker.STORE, 'extension-fixture', run['id'])
        report.update(verified_at=datetime.now(timezone.utc).isoformat(), image=release['image'], source_release=release['source_release'], artifacts_registered=len(collected['files']))
        assert collected['files'] and not collected['skipped']
        (ROOT / 'workspace-extension-verification.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
    finally:
        broker.remove_container(container)
        finish_run(broker.STORE, 'extension-fixture', run['id'], interrupted=True)
        discard_completed_copy(broker.STORE, 'extension-fixture', run['id'])


if __name__ == '__main__':
    main()
