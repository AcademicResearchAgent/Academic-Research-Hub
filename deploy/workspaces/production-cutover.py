"""Plan and perform the first migration from the legacy production workspace.

Production data stays in its existing WebUI directory. Only production-owned
chats/uploads and proven legacy output are imported into a fresh private store.
After migration protection is installed, failures leave services stopped and
data intact; this script never reopens the shared Agent as a rollback.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
from dotenv import dotenv_values

ROOT = Path('/home/ubuntu/haudi-hermes')
LEGACY_IMAGE = 'sha256:3bdcf3f6ffcf90fdb8092c4e1ed165424d61dedb3d93d5e939a6000d043a1876'
LEGACY_SERVICE = 'haudi-hermes-api.service'
SYSTEMD = Path('/etc/systemd/system')
CGROUP_ROOT = Path('/sys/fs/cgroup')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


control = load('cutover_release_control', Path(__file__).with_name('release-control.py'))
installer = load('cutover_broker_installer', Path(__file__).with_name('install-broker.py'))


def source_directory(release):
    assert re.fullmatch(r'[0-9a-f]{16}', release)
    source = ROOT / 'workspace-source-releases' / release
    digest = hashlib.sha256()
    for path in sorted(source.rglob('*.py')):
        if '__pycache__' not in path.parts:
            assert not path.is_symlink()
            digest.update(path.relative_to(source).as_posix().encode() + b'\0' + path.read_bytes().replace(b'\r\n', b'\n'))
    assert digest.hexdigest()[:16] == release, 'Source release no longer matches its content identity'
    return source


def legacy_work():
    key = dotenv_values(ROOT / 'state/.env')['API_SERVER_KEY']
    with httpx.Client(timeout=5, trust_env=False) as client:
        response = client.get('http://127.0.0.1:8642/health/detailed', headers={'Authorization': 'Bearer ' + key})
        response.raise_for_status()
        data = response.json()
    queues = data['readiness']['checks']['background_queues']
    return {'active_agents': int(data['active_agents']),
            **{name: int(queues[name]) for name in ('active_api_runs', 'process_completions', 'active_delegations')}}


def require_legacy_baseline():
    actual = control.inspect('haudi-openwebui')
    assert actual['Image'] == LEGACY_IMAGE and actual['State']['Running']
    assert {m['Destination']: m['Source'] for m in actual['Mounts']} == {'/app/backend/data': str(ROOT / 'openwebui/data')}
    assert control.command('systemctl', 'show', LEGACY_SERVICE, '--property=KillMode', '--value') == 'control-group'
    config = control.configuration('production')
    for path in (config['workspace'], config['socket'], config['ui_record'], config['broker_record'],
                 SYSTEMD / config['service']):
        assert not path.exists(), 'An initial production workspace already exists; inspect it before resuming'


def verify_preview_source(source, preview):
    actual = control.inspect('haudi-openwebui-workspace-preview')
    assert actual['Image'] == preview['image'] and actual['State']['Running']
    expected = {}
    for path in (source / 'overlays/open-webui/workstation_workspace').glob('*.py'):
        expected[path.name] = hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    code = "import hashlib,json;from pathlib import Path;p=Path('/app/backend/open_webui/workstation_workspace');print(json.dumps({f.name:hashlib.sha256(f.read_bytes().replace(b'\\r\\n',b'\\n')).hexdigest() for f in p.glob('*.py')}))"
    received = json.loads(control.command('docker', 'exec', 'haudi-openwebui-workspace-preview', 'python', '-c', code))
    assert received == expected, 'Preview and selected workspace source differ'


def legacy_listener_closed():
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(('127.0.0.1', 8642)) != 0


def assert_legacy_stopped():
    # The old gateway exits with status 1 on an otherwise completed systemd
    # stop. 'failed' is therefore possible; prove process and listener absence
    # rather than treating the unit's historical exit result as a live process.
    values = dict(line.split('=', 1) for line in control.command('systemctl', 'show', LEGACY_SERVICE,
                  '--property=ActiveState,MainPID,ControlGroup').splitlines() if '=' in line)
    assert values['ActiveState'] in {'inactive', 'failed'} and values['MainPID'] == '0', 'Legacy Agent is not stopped'
    group = values.get('ControlGroup', '')
    if group:
        expected = '/system.slice/' + LEGACY_SERVICE
        assert group == expected, 'Unexpected legacy process group'
        directory = CGROUP_ROOT / group.lstrip('/')
        if directory.exists():
            assert not directory.is_symlink()
            for path in directory.rglob('cgroup.procs'):
                assert not path.read_text().strip(), 'Legacy Agent still has child processes'
    assert legacy_listener_closed(), 'Legacy shared listener is still available'


def plan(release):
    require_legacy_baseline()
    source = source_directory(release)
    assert Path(__file__).resolve() == source / 'deploy/workspaces/production-cutover.py', 'Run the immutable source release entry point'
    preview = json.loads((ROOT / 'workspace-preview.json').read_text())
    runtime = json.loads((ROOT / 'workspace-broker-preview.json').read_text())
    assert preview['preview_healthy'] and runtime['healthy']
    verify_preview_source(source, preview)
    work = legacy_work()
    size = sum(int(control.command('du', '-sb', str(ROOT / name)).split()[0])
               for name in ('openwebui/data', 'state', 'workspace'))
    assert shutil.disk_usage(ROOT).free > size * 2 + 512 * 1024**2, 'Insufficient space for a retained production backup'
    result = {'created_at': datetime.now(timezone.utc).isoformat(), 'source_release': release,
              'legacy_image': LEGACY_IMAGE, 'ui': preview, 'worker_image': runtime['image'],
              'legacy_work': work, 'estimated_backup_bytes': size,
              'production_data': str(ROOT / 'openwebui/data'),
              'production_workspace': str(ROOT / 'workspace-production-store'),
              'preview_data_will_not_be_imported': True,
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'actions': ['stop production UI intake', 'wait for legacy work to finish',
                          'stop legacy Agent process group', 'back up production data, state and shared files',
                          'disable legacy startup while the production workspace record exists',
                          'migrate owned files, repair history and quarantine unattributed originals',
                          'start private production broker and workspace UI on existing HTTPS upstream port',
                          'verify health, mounts, stopped legacy listener and retained user records']}
    directory = ROOT / 'workspace-production-plans'
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    path.write_text(json.dumps(result, indent=2))
    return {'plan': str(path), 'source_release': release, 'target_image': preview['image'],
            'legacy_work': work, 'estimated_backup_bytes': size, 'production_changed': False}


def apply(plan_path):
    plan_path = plan_path.resolve()
    assert plan_path.parent == ROOT / 'workspace-production-plans'
    planned = json.loads(plan_path.read_text())
    assert planned['script_sha256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'Cutover implementation changed; generate a new plan'
    require_legacy_baseline()
    source = source_directory(planned['source_release'])
    assert Path(__file__).resolve() == source / 'deploy/workspaces/production-cutover.py'
    verify_preview_source(source, planned['ui'])
    # The separate history/browser check is mandatory before changing the live
    # entry point. File existence alone is not proof of a completed verification.
    history = json.loads((ROOT / 'workspace-history-browser-verification.json').read_text())
    assert history.get('passed') is True and history['source_release'] == planned['source_release']
    assert history['preview_image'] == planned['ui']['image']
    assert not any(legacy_work().values()), 'Legacy work is still active'
    config = control.configuration('production')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = ROOT / 'workspace-production-backups' / stamp
    backup.mkdir(mode=0o700, parents=True)
    progress = {'phase': 'stopping_intake', 'plan': str(plan_path), 'backup': str(backup),
                'data_restored_from_old_snapshot': False, 'preview_data_imported': False}
    event_path = backup / 'cutover-event.json'

    def record(phase, **values):
        progress.update(phase=phase, **values)
        event_path.write_text(json.dumps(progress, indent=2))
        print(json.dumps({'phase': phase}), flush=True)

    protected = False
    try:
        record('stopping_intake')
        control.command('docker', 'stop', '--time', '30', 'haudi-openwebui')
        deadline = time.monotonic() + 120
        while any(legacy_work().values()):
            if time.monotonic() >= deadline:
                raise RuntimeError('Legacy work did not finish before the migration window')
            time.sleep(1)
        control.command('systemctl', 'stop', LEGACY_SERVICE)
        assert_legacy_stopped()
        record('backing_up')
        for label, path in (('data', config['data']), ('state', ROOT / 'state'), ('shared', ROOT / 'workspace')):
            shutil.copytree(path, backup / label, symlinks=True)
        for rel in ('data/webui.db', 'state/state.db'):
            with closing(sqlite3.connect((backup / rel).as_uri() + '?mode=ro', uri=True)) as db:
                assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        unit = SYSTEMD / LEGACY_SERVICE
        if unit.is_file():
            shutil.copy2(unit, backup / 'legacy-agent.service')
        dropin = SYSTEMD / (LEGACY_SERVICE + '.d')
        dropin.mkdir(exist_ok=True)
        guard = dropin / 'workstation-workspace-cutover.conf'
        assert not guard.exists()
        guard.write_text('[Unit]\nConditionPathExists=!' + str(config['ui_record']) + '\n')
        initial = {**planned['ui'], 'data': str(config['data']), 'workspace_root': str(config['workspace']),
                   'scope': 'production', 'phase': 'migrating', 'production_unchanged': False,
                   'cutover_event': str(event_path)}
        initial.pop('release_control_event', None)
        initial.pop('preview_healthy', None)
        protected = True
        config['ui_record'].write_text(json.dumps(initial, indent=2))
        control.command('systemctl', 'daemon-reload')
        control.command('systemctl', 'disable', LEGACY_SERVICE)
        record('migrating')
        sys.path.insert(0, str(source / 'overlays/open-webui'))
        from workstation_workspace.store import WorkspaceStore
        batch = load('production_migration_batch', source / 'deploy/workspaces/migration-batch.py')
        result = batch.migrate_batch(config['data'] / 'webui.db', backup / 'state/state.db', ROOT / 'workspace',
                                     config['data'] / 'uploads', WorkspaceStore(config['workspace']), backup / 'migration')
        record('installing_isolated_services', migration=result)
        config['socket'].mkdir(mode=0o700)
        broker_unit = SYSTEMD / config['service']
        broker_unit.write_text(installer.service_unit(source, config['workspace'], config['socket'] / 'broker.sock',
                                                       planned['worker_image'], 'production'))
        control.command('systemctl', 'daemon-reload')
        control.command('systemctl', 'enable', '--now', config['service'])
        control.resume_broker(config)
        config['broker_record'].write_text(json.dumps({'service': config['service'],
            'source_release': planned['source_release'], 'image': planned['worker_image'],
            'broker_sha256': hashlib.sha256((source / 'deploy/workspaces/broker.py').read_bytes()).hexdigest(),
            'healthy': True, 'scope': 'production', 'public_port': None}, indent=2))
        old_name = 'haudi-openwebui-legacy-before-workspaces-' + stamp
        control.command('docker', 'rename', 'haudi-openwebui', old_name)
        control.start_ui(config, planned['ui']['image'])
        control.health(config)
        with socket.socket() as probe:
            probe.settimeout(1)
            assert probe.connect_ex(('127.0.0.1', 8642)) != 0, 'Legacy shared listener is still available'
        initial.update(phase='active', healthy=True, legacy_container=old_name)
        config['ui_record'].write_text(json.dumps(initial, indent=2))
        control.validate(config)
        record('active', verified_at=datetime.now(timezone.utc).isoformat(), old_container=old_name,
               production_image=planned['ui']['image'], legacy_agent_disabled=True)
        return {'phase': 'active', 'production_image': planned['ui']['image'], 'migration': result,
                'backup': str(backup), 'legacy_agent_disabled': True, 'preview_data_imported': False}
    except BaseException as error:
        if protected:
            # Once isolated data can exist, never restart the old shared Agent.
            # Retain all files and stop intake; the private event identifies the
            # exact completed step for an operator's evidence-based recovery.
            subprocess.run(['systemctl', 'stop', config['service']], capture_output=True)
            names = control.command('docker', 'ps', '--format', '{{.Names}}').splitlines()
            if 'haudi-openwebui' in names:
                subprocess.run(['docker', 'stop', '--time', '30', 'haudi-openwebui'], capture_output=True)
            record('maintenance', failed_step=progress['phase'], error_category=type(error).__name__)
        else:
            control.command('systemctl', 'start', LEGACY_SERVICE)
            control.command('docker', 'start', 'haudi-openwebui')
            record('aborted_before_migration', error_category=type(error).__name__)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('plan', 'apply'))
    parser.add_argument('--source-release')
    parser.add_argument('--plan', type=Path)
    args = parser.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    with (ROOT / 'workspace-production-cutover.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'plan':
            assert args.source_release and args.plan is None
            result = plan(args.source_release)
        else:
            assert args.plan is not None and args.source_release is None
            result = apply(args.plan)
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
