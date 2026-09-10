"""Offline migration batch used by rehearsal and first production activation.

The caller stops writers and provides a private backup/report directory. Native
file IDs and verified tool receipts determine ownership; no path guesses do.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from workstation_models.core import session_scope
from workstation_workspace.history import repair_history
from workstation_workspace.legacy import migrate_legacy
from workstation_workspace.migration import decoded, migrate, owned_upload_bytes
from workstation_workspace.store import WorkspaceError


def user_text_digest(native):
    records = []
    with closing(sqlite3.connect(native)) as db:
        for thread, raw in db.execute('SELECT id,chat FROM chat ORDER BY id'):
            document = decoded(raw, {})
            if not isinstance(document, dict):
                continue
            history = document.get('history') or {}
            history = history.get('messages') or {} if isinstance(history, dict) else {}
            if not isinstance(history, dict):
                history = {}
            for key, message in sorted(history.items()):
                if isinstance(message, dict) and message.get('role') == 'user':
                    records.append((thread, 'history', key, message.get('content')))
            messages = document.get('messages') or []
            for index, message in enumerate(messages if isinstance(messages, list) else []):
                if isinstance(message, dict) and message.get('role') == 'user':
                    records.append((thread, 'messages', index, message.get('content')))
        columns = {row[1] for row in db.execute('PRAGMA table_info(chat_message)')}
        if {'id', 'role', 'chat_id', 'content'} <= columns:
            for key, thread, raw in db.execute("SELECT id,chat_id,content FROM chat_message WHERE role='user' ORDER BY chat_id,id"):
                records.append((thread, 'normalized', key, decoded(raw, raw)))
    return hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def migrate_batch(native, agent, shared, uploads, store, reports):
    native, agent, shared, uploads, reports = map(Path, (native, agent, shared, uploads, reports))
    reports.mkdir(parents=True, exist_ok=True, mode=0o700)
    before = user_text_digest(native)
    first = migrate(native, uploads, store, stored_upload_root='/app/backend/data/uploads')
    legacy = migrate_legacy(native, agent, shared, session_scope, store)
    (reports / 'native-report.json').write_text(json.dumps(first, indent=2))
    (reports / 'legacy-report.json').write_text(json.dumps(legacy, ensure_ascii=False, indent=2))
    if first['issues'] or legacy['issues']:
        raise RuntimeError('Migration has unresolved ownership/content issues; inspect private reports')
    hashes = 0
    for chat in first['chats']:
        with store.db() as db:
            owner = db.execute('SELECT owner FROM projects WHERE id=?', (chat['project'],)).fetchone()[0]
        for file in chat['files']:
            assert hashlib.sha256(store.read(owner, file['node'], 1)[1]).hexdigest() == file['sha256']
            hashes += 1
    for file in legacy['eligible']:
        assert hashlib.sha256(store.read(file['owner'], file['node'], 1)[1]).hexdigest() == file['sha256']
        hashes += 1
    quarantine = reports / 'quarantine'
    quarantine.mkdir(mode=0o700, exist_ok=True)
    inventory = []
    for relative in legacy['unclassified']:
        record = {'relative_path': relative}
        try:
            data = owned_upload_bytes(shared / relative, shared, store.max_file_bytes)
            name = hashlib.sha256(relative.encode()).hexdigest()
            target = quarantine / name
            if target.exists():
                assert target.read_bytes() == data, 'Quarantine source changed after initial capture'
            else:
                target.write_bytes(data)
            record.update(copy=name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        except (OSError, WorkspaceError):
            record['status'] = 'unsafe_or_unavailable_preserved_at_original'
        inventory.append(record)
    (quarantine / 'inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2))
    repaired = repair_history(native, store, legacy['eligible'], shared)
    second = migrate(native, uploads, store, stored_upload_root='/app/backend/data/uploads')
    repeated = migrate_legacy(native, agent, shared, session_scope, store)
    assert first['chats'] == second['chats'] and not second['issues'] and not repeated['issues']
    assert [(p['node'], p['sha256']) for p in legacy['eligible']] == [(p['node'], p['sha256']) for p in repeated['eligible']]
    assert all(p['already_imported'] for p in repeated['eligible'])
    assert not any(repair_history(native, store, legacy['eligible'], shared).values())
    assert user_text_digest(native) == before, 'Migration changed original user text'
    result = {'native_chats': first['counts'].get('chats', 0),
              'native_attachments': first['counts'].get('eligible_attachments', 0),
              'proven_legacy_outputs': len(legacy['eligible']), 'content_hashes_verified': hashes,
              'quarantined_files': sum('copy' in item for item in inventory),
              'preserved_unsafe_originals': sum('copy' not in item for item in inventory),
              'history_repair': repaired, 'repeated_apply_stable_ids': True,
              'original_user_text_preserved': True, 'original_source_files_preserved': True}
    (reports / 'summary.json').write_text(json.dumps(result, indent=2))
    return result
