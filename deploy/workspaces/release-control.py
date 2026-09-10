"""Capture or restore a compatible workspace UI release without reverting data.

This is deliberately scoped to the current broker and database schema. It will
not activate the legacy shared-workspace UI or restore an old database snapshot.
Run as root on the deployment host. Checkpoints and backups are private.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Release operation failed: ' + args[0])
    return result.stdout.strip()


def configuration(scope):
    preview = scope == 'preview'
    return {'scope': scope, 'name': 'haudi-openwebui-workspace-preview' if preview else 'haudi-openwebui',
            'port': 9120 if preview else 9119,
            'data': ROOT / ('workspace-preview-data' if preview else 'openwebui/data'),
            'workspace': ROOT / ('workspace-preview-store' if preview else 'workspace-production-store'),
            'socket': ROOT / ('workspace-broker' if preview else 'workspace-production-broker'),
            'service': 'haudi-workspace-broker-' + scope + '.service',
            'ui_record': ROOT / ('workspace-preview.json' if preview else 'workspace-production.json'),
            'broker_record': ROOT / ('workspace-broker-' + scope + '.json')}


def inspect(name):
    return json.loads(command('docker', 'inspect', name))[0]


def broker(config, method, path):
    with httpx.Client(transport=httpx.HTTPTransport(uds=str(config['socket'] / 'broker.sock')),
                      timeout=5, trust_env=False) as client:
        response = client.request(method, 'http://broker' + path)
        response.raise_for_status()
        return response.json()


def resume_broker(config):
    for _ in range(20):
        try:
            broker(config, 'POST', '/resume')
            return
        except (httpx.HTTPError, OSError):
            time.sleep(1)
    raise RuntimeError('Workspace broker did not resume')


def schemas(config):
    result = {}
    for name, path in {'native': config['data'] / 'webui.db',
                       'workspace': config['workspace'] / 'workspaces.db'}.items():
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            rows = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
            result[name] = hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()
    return result


def validate(config):
    ui = json.loads(config['ui_record'].read_text())
    runtime = json.loads(config['broker_record'].read_text())
    actual = inspect(config['name'])
    assert actual['Image'] == ui['image'] and actual['State']['Running']
    assert actual['HostConfig']['NetworkMode'] == 'host'
    mounts = {item['Destination']: item['Source'] for item in actual['Mounts']}
    expected = {'/app/backend/data': config['data'], '/app/workspaces': config['workspace'],
                '/app/workspace-broker': config['socket']}
    assert mounts == {key: str(value) for key, value in expected.items()}, 'Workspace mount boundary differs'
    for path in expected.values():
        assert path.resolve() == path and path.is_relative_to(ROOT), 'Unexpected persistent path'
    env = dict(item.split('=', 1) for item in actual['Config']['Env'] if '=' in item)
    assert env.get('WORKSTATION_WORKSPACE_ROOT') == '/app/workspaces'
    assert env.get('WORKSTATION_BROKER_SOCKET') == '/app/workspace-broker/broker.sock'
    assert runtime['service'] == config['service'] and runtime['healthy']
    unit = Path('/etc/systemd/system') / config['service']
    unit_text = unit.read_text()
    assert 'WORKSTATION_WORKSPACE_ROOT=' + str(config['workspace']) in unit_text
    assert 'WORKSTATION_RUNTIME_IMAGE=' + runtime['image'] in unit_text
    assert '/workspace-source-releases/' + runtime['source_release'] + '/' in unit_text
    assert command('systemctl', 'is-active', config['service']) == 'active'
    health = broker(config, 'GET', '/health')
    assert health['status'] == 'ok', 'Broker is already in maintenance'
    return {'ui': ui, 'broker': runtime, 'unit_sha256': hashlib.sha256(unit.read_bytes()).hexdigest(),
            'schemas': schemas(config), 'scope': config['scope']}


def health(config):
    for _ in range(90):
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                response = client.get('http://127.0.0.1:' + str(config['port']) + '/health')
                if response.status_code == 200 and broker(config, 'GET', '/health')['status'] == 'ok':
                    return
        except (httpx.HTTPError, OSError):
            pass
        time.sleep(2)
    raise RuntimeError('Workspace release did not become healthy')


def assert_no_workers(config):
    # Inspect only this store's exact run IDs; unrelated preview/production runs
    # are not stopped or removed by release control.
    with closing(sqlite3.connect((config['workspace'] / 'workspaces.db').as_uri() + '?mode=ro', uri=True)) as db:
        assert db.execute("SELECT count(*) FROM runs WHERE status='running'").fetchone()[0] == 0
        names = {'haudi-ws-' + row[0] for row in db.execute('SELECT id FROM runs')}
    running = set(command('docker', 'ps', '--filter', 'label=haudi.workspace.managed=true', '--format', '{{.Names}}').splitlines())
    assert not names.intersection(running), 'A workspace worker is still active'


def backup(config, destination):
    # All writers have stopped. Preserve files, versions and incomplete copies;
    # symlinks are copied as links, never followed into another private tree.
    for label in ('data', 'workspace'):
        shutil.copytree(config[label], destination / label, symlinks=True)
    for rel in ('data/webui.db', 'workspace/workspaces.db'):
        with closing(sqlite3.connect((destination / rel).as_uri() + '?mode=ro', uri=True)) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def start_ui(config, image):
    assert re.fullmatch(r'sha256:[0-9a-f]{64}', image)
    command('docker', 'run', '-d', '--name', config['name'], '--restart', 'unless-stopped',
            '--network', 'host', '--memory', '1024m', '--memory-swap', '1536m', '--cpus', '1',
            '--env-file', str(ROOT / 'openwebui/container.env'), '-e', 'PORT=' + str(config['port']),
            '-e', 'WORKSTATION_WORKSPACE_ROOT=/app/workspaces',
            '-e', 'WORKSTATION_BROKER_SOCKET=/app/workspace-broker/broker.sock',
            '-e', 'OFFLINE_MODE=true', '-e', 'HF_HUB_OFFLINE=1',
            '--mount', 'type=bind,src=' + str(config['data']) + ',dst=/app/backend/data',
            '--mount', 'type=bind,src=' + str(config['workspace']) + ',dst=/app/workspaces',
            '--mount', 'type=bind,src=' + str(config['socket']) + ',dst=/app/workspace-broker', image)


def switch(config, target_path, expected_image, destination):
    current = validate(config)
    assert current['ui']['image'] == expected_image, 'Active release changed'
    target_path = target_path.resolve()
    assert target_path.parent == ROOT / 'workspace-release-checkpoints'
    target = json.loads(target_path.read_text())
    assert target['scope'] == config['scope'] and target['schemas'] == current['schemas']
    assert target['broker'] == current['broker'] and target['unit_sha256'] == current['unit_sha256'], 'Broker changed; capture and validate a new compatible checkpoint'
    assert target['ui']['image'] != current['ui']['image'], 'Target is already active'
    assert command('docker', 'image', 'inspect', target['ui']['image'], '--format', '{{.Id}}') == target['ui']['image']
    stamp = destination.name
    previous_name = config['name'] + '-before-switch-' + stamp
    record = {'scope': config['scope'], 'phase': 'draining', 'from_image': expected_image,
              'to_image': target['ui']['image'], 'checkpoint': target_path.name,
              'backup': str(destination), 'data_restore_performed': False}
    record_path = destination / 'release-event.json'
    record_path.write_text(json.dumps(record, indent=2))
    stopped = renamed = False
    try:
        broker(config, 'POST', '/drain')
        deadline = time.monotonic() + 90
        while broker(config, 'GET', '/health')['requests']:
            if time.monotonic() >= deadline:
                raise RuntimeError('Active work did not drain before the release window expired')
            time.sleep(1)
        command('docker', 'stop', '--time', '30', config['name'])
        stopped = True
        command('systemctl', 'stop', config['service'])
        assert_no_workers(config)
        backup(config, destination)
        assert schemas(config) == current['schemas']
        command('docker', 'rename', config['name'], previous_name)
        renamed = True
        command('systemctl', 'start', config['service'])
        start_ui(config, target['ui']['image'])
        health(config)
        assert schemas(config) == current['schemas'], 'Release changed the database schema'
        restored = {**target['ui'], 'release_control_event': str(record_path)}
        config['ui_record'].write_text(json.dumps(restored, indent=2))
        validate(config)
        record.update(phase='complete', verified_at=datetime.now(timezone.utc).isoformat(),
                      old_container_retained=previous_name, current_data_retained=True, isolation_retained=True)
    except BaseException as error:
        record.update(phase='failed', error_category=type(error).__name__)
        try:
            names = command('docker', 'ps', '-a', '--format', '{{.Names}}').splitlines()
            if renamed and config['name'] in names:
                command('docker', 'stop', '--time', '30', config['name'])
                command('docker', 'rename', config['name'], config['name'] + '-failed-switch-' + stamp)
            if schemas(config) != current['schemas']:
                command('systemctl', 'stop', config['service'])
                record['recovery'] = 'maintenance_schema_changed_preserve_all_data'
            else:
                if renamed:
                    command('docker', 'rename', previous_name, config['name'])
                command('systemctl', 'start', config['service'])
                resume_broker(config)
                if stopped:
                    command('docker', 'start', config['name'])
                config['ui_record'].write_text(json.dumps(current['ui'], indent=2))
                health(config)
                record['recovery'] = 'previous_release_restored_with_current_data'
        except BaseException as recovery_error:
            record['recovery_error_category'] = type(recovery_error).__name__
        record_path.write_text(json.dumps(record, indent=2))
        raise
    record_path.write_text(json.dumps(record, indent=2))
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('capture', 'switch'))
    parser.add_argument('--scope', choices=('preview', 'production'), default='preview')
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--expect-image')
    args = parser.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    config = configuration(args.scope)
    directory = ROOT / 'workspace-release-checkpoints'
    directory.mkdir(mode=0o700, exist_ok=True)
    with (directory / (args.scope + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        if args.action == 'capture':
            assert args.checkpoint is None and args.expect_image is None
            checkpoint = directory / (args.scope + '-' + stamp + '.json')
            data = validate(config)
            data['captured_at'] = datetime.now(timezone.utc).isoformat()
            checkpoint.write_text(json.dumps(data, indent=2))
            print(json.dumps({'checkpoint': str(checkpoint), 'image': data['ui']['image'],
                              'scope': args.scope, 'data_changed': False}), flush=True)
        else:
            assert args.checkpoint is not None and args.expect_image is not None
            destination = ROOT / 'workspace-release-backups' / stamp
            destination.mkdir(mode=0o700, parents=True)
            print(json.dumps(switch(config, args.checkpoint, args.expect_image, destination)), flush=True)


if __name__ == '__main__':
    main()
