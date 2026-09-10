"""Apply real historical migration to the retained private preview, with backup.

Production databases and files are read-only sources. Existing synthetic preview
data stays in place; native upload originals are copied only when absent and
only from the approved production uploads root.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys


ROOT = Path('/home/ubuntu/haudi-hermes')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-release', required=True)
    args = parser.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    cutover = load('preview_history_cutover', Path(__file__).with_name('production-cutover.py'))
    control = cutover.control
    source = cutover.source_directory(args.source_release)
    sys.path.insert(0, str(source / 'overlays/open-webui'))
    from workstation_workspace.migration import owned_upload_bytes
    from workstation_workspace.store import WorkspaceStore
    batch = load('preview_history_batch', source / 'deploy/workspaces/migration-batch.py')
    config = control.configuration('preview')
    current = control.validate(config)
    cutover.verify_preview_source(source, current['ui'])
    report_path = ROOT / 'workspace-preview-history-migration.json'
    assert not report_path.exists(), 'Inspect the existing preview history migration before repeating it'
    assert not any(cutover.legacy_work().values()), 'Legacy source is busy; defer the preview snapshot'
    assert control.broker(config, 'GET', '/health')['requests'] == 0
    target = ROOT / 'workspace-preview-history-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target.mkdir(parents=True, mode=0o700)
    report = {'phase': 'stopping_preview', 'source_release': args.source_release,
              'preview_image': current['ui']['image'], 'backup': str(target), 'production_changed': False}
    report_path.write_text(json.dumps(report, indent=2))
    try:
        control.broker(config, 'POST', '/drain')
        control.command('docker', 'stop', '--time', '30', config['name'])
        control.command('systemctl', 'stop', config['service'])
        control.assert_no_workers(config)
        control.backup(config, target)
        with closing(sqlite3.connect((ROOT / 'state/state.db').as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(target / 'agent.db')) as snapshot:
                original.backup(snapshot)
        uploads = config['data'] / 'uploads'
        uploads.mkdir(exist_ok=True, mode=0o700)
        copied = 0
        with closing(sqlite3.connect((config['data'] / 'webui.db').as_uri() + '?mode=ro', uri=True)) as db:
            records = db.execute('SELECT f.path FROM file f JOIN user u ON u.id=f.user_id WHERE f.path IS NOT NULL').fetchall()
        for (stored,) in records:
            relative = Path(stored).relative_to('/app/backend/data/uploads')
            assert relative.parts and '..' not in relative.parts
            destination = uploads / relative
            if destination.exists():
                # Existing preview uploads include synthetic fixtures. They are
                # never replaced by another source based on filename alone.
                owned_upload_bytes(destination, uploads, 64 * 1024**2)
                continue
            content = owned_upload_bytes(ROOT / 'openwebui/data/uploads' / relative,
                                         ROOT / 'openwebui/data/uploads', 64 * 1024**2)
            directory = uploads
            for part in relative.parts[:-1]:
                directory /= part
                assert not directory.is_symlink()
                directory.mkdir(exist_ok=True, mode=0o700)
            assert not destination.is_symlink()
            destination.write_bytes(content)
            copied += 1
        report['phase'] = 'migrating'
        report_path.write_text(json.dumps(report, indent=2))
        result = batch.migrate_batch(config['data'] / 'webui.db', target / 'agent.db', ROOT / 'workspace',
                                     uploads, WorkspaceStore(config['workspace']), target / 'migration')
        report.update(phase='migrated', migration=result, native_originals_copied=copied)
    except BaseException as error:
        report.update(phase='failed', error_category=type(error).__name__)
        raise
    finally:
        report_path.write_text(json.dumps(report, indent=2))
        control.command('systemctl', 'start', config['service'])
        control.resume_broker(config)
        control.command('docker', 'start', config['name'])
        control.health(config)
    report.update(phase='complete', verified_at=datetime.now(timezone.utc).isoformat(), preview_healthy=True)
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
