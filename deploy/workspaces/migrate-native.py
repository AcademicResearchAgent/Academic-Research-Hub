"""Run inside the trusted UI container, with a mounted private backup directory.

Dry-run is the default. This migrates native uploads; legacy shared outputs need
a separate provenance audit and must never be inferred from message paths.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from open_webui.workstation_workspace.migration import migrate
from open_webui.workstation_workspace.store import WorkspaceStore


def snapshot(source, target):
    if target.exists():
        raise RuntimeError('Backup destination already exists')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    target.chmod(0o600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native-db', type=Path, default=Path('/app/backend/data/webui.db'))
    parser.add_argument('--uploads', type=Path, default=Path('/app/backend/data/uploads'))
    parser.add_argument('--workspace', type=Path, default=Path('/app/workspaces'))
    parser.add_argument('--stored-upload-root', type=Path, help='Explicit path translation for offline database snapshots; no filename guessing')
    parser.add_argument('--backup-root', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    target = args.backup_root.resolve() / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target.mkdir(parents=True, mode=0o700)
    native = args.native_db.resolve()
    snapshot(native, target / 'native-before.db')
    existing = args.workspace.resolve() / 'workspaces.db'
    if args.apply and existing.exists():
        snapshot(existing, target / 'workspace-before.db')
    store = WorkspaceStore(args.workspace) if args.apply else None
    # Use the backup's consistent snapshot, never a moving live chat query.
    report = migrate(target / 'native-before.db', args.uploads, store, stored_upload_root=args.stored_upload_root)
    report['native_database_unchanged'] = True
    report['original_uploads_preserved'] = True
    report['legacy_shared_outputs'] = 'not_imported_requires_provenance_audit'
    report['rollback'] = 'Preserve new workspace versions and writes; do not overwrite a live database with an old snapshot.'
    (target / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'mode': report['mode'], 'counts': report['counts'], 'issues': len(report['issues']),
                      'backup_record': target.name, 'originals_preserved': True}), flush=True)


if __name__ == '__main__':
    main()
