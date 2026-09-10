"""Rehearse complete historical attribution in a private, unused workspace store.

Original databases/files and both web services remain untouched. The retained
snapshot and quarantine are outside every worker mount. Reports omit contents.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path('/home/ubuntu/haudi-hermes')


def snapshot(source, target):
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-release', required=True)
    args = parser.parse_args()
    assert os.geteuid() == 0 and re.fullmatch(r'[0-9a-f]{16}', args.source_release)
    os.umask(0o077)
    source = ROOT / 'workspace-source-releases' / args.source_release
    sys.path.insert(0, str(source / 'overlays/open-webui'))
    from workstation_models.core import session_scope
    from workstation_workspace.store import WorkspaceStore, WorkspaceError
    from workstation_workspace.migration import migrate, owned_upload_bytes
    from workstation_workspace.legacy import migrate_legacy
    from workstation_workspace.history import repair_history
    target = ROOT / 'workspace-migration-rehearsals' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target.mkdir(parents=True, mode=0o700)
    snapshot(ROOT / 'openwebui/data/webui.db', target / 'native.db')
    snapshot(ROOT / 'state/state.db', target / 'agent.db')
    store = WorkspaceStore(target / 'workspaces')
    uploads = ROOT / 'openwebui/data/uploads'
    shared = ROOT / 'workspace'
    first = migrate(target / 'native.db', uploads, store, stored_upload_root='/app/backend/data/uploads')
    legacy = migrate_legacy(target / 'native.db', target / 'agent.db', shared, session_scope, store)
    assert not first['issues'] and not legacy['issues'], 'Migration issues require review before cutover'
    second = migrate(target / 'native.db', uploads, store, stored_upload_root='/app/backend/data/uploads')
    repeated = migrate_legacy(target / 'native.db', target / 'agent.db', shared, session_scope, store)
    assert first['chats'] == second['chats'], 'Native migration changed IDs on repeated apply'
    assert [(p['node'], p['sha256']) for p in legacy['eligible']] == [(p['node'], p['sha256']) for p in repeated['eligible']]
    assert all(p['already_imported'] for p in repeated['eligible'])
    checked = 0
    for chat in first['chats']:
        with store.db() as db:
            owner = db.execute('SELECT owner FROM projects WHERE id=?', (chat['project'],)).fetchone()[0]
        for file in chat['files']:
            data = store.read(owner, file['node'])[1]
            assert hashlib.sha256(data).hexdigest() == file['sha256']
            checked += 1
    for file in legacy['eligible']:
        assert hashlib.sha256(store.read(file['owner'], file['node'])[1]).hexdigest() == file['sha256']
        checked += 1
        for forbidden in ('migration-unowned-test',):
            try:
                store.read(forbidden, file['node'])
                raise AssertionError('Foreign account could read migrated file')
            except WorkspaceError as error:
                assert error.status == 404
    quarantine = target / 'quarantine'
    quarantine.mkdir(mode=0o700)
    inventory = []
    for relative in legacy['unclassified']:
        record = {'relative_path': relative}
        try:
            data = owned_upload_bytes(shared / relative, shared, store.max_file_bytes)
            opaque = hashlib.sha256(relative.encode()).hexdigest()
            (quarantine / opaque).write_bytes(data)
            record.update(copy=opaque, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        except (OSError, WorkspaceError):
            record['status'] = 'unsafe_or_unavailable_preserved_at_original'
        inventory.append(record)
    (target / 'native-report.json').write_text(json.dumps(first, indent=2))
    (target / 'legacy-report.json').write_text(json.dumps(legacy, ensure_ascii=False, indent=2))
    (quarantine / 'inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2))
    snapshot(target / 'native.db', target / 'native-repaired.db')
    repaired = repair_history(target / 'native-repaired.db', store, legacy['eligible'], shared)
    assert not any(repair_history(target / 'native-repaired.db', store, legacy['eligible'], shared).values()), 'History repair must be idempotent'
    summary = {'verified_at': datetime.now(timezone.utc).isoformat(), 'source_release': args.source_release,
               'rehearsal': target.name, 'native_chats': first['counts'].get('chats', 0),
               'native_attachments': first['counts'].get('eligible_attachments', 0),
               'proven_legacy_outputs': len(legacy['eligible']), 'unclassified_quarantined': sum('copy' in p for p in inventory),
               'unclassified_preserved_only': sum('copy' not in p for p in inventory), 'content_hashes_verified': checked,
               'repeated_apply_stable_ids': True, 'originals_not_written': True,
               'history_repair': repaired, 'history_repair_idempotent': True,
               'production_changed': False, 'preview_changed': False}
    (ROOT / 'workspace-migration-verification.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
