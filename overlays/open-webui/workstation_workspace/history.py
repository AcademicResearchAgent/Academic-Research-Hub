"""Repair legacy assistant file delivery in a backed-up native chat database.

Call only on a rehearsal copy or during a quiesced, backed-up migration. Proven
files receive authenticated references; other internal paths grant no access.
"""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .migration import decoded
from .public_paths import clean_text
from .store import WorkspaceError


PUBLIC_FIELDS = ('content', 'output', 'statusHistory', 'status_history', 'sources', 'embeds', 'error', 'contextSummary', 'context_summary')


def clean_attachment_metadata(value):
    """Remove storage details, retaining opaque native IDs and download routes.

User message text and original file bytes are not rewritten. The nested native
FileModel copied into historical attachments can otherwise disclose file.path.
"""
    if isinstance(value, list):
        return [clean_attachment_metadata(item) for item in value]
    if isinstance(value, dict):
        return {key: clean_attachment_metadata(item) for key, item in value.items()
                if key not in {'path', 'resolved_path', 'storage_path', 'absolute_path'}}
    if isinstance(value, str):
        return clean_text(value)
    return value


def repair_history(native_db, store, proofs, legacy_root):
    references = {}
    for proof in proofs:
        if not proof.get('node'):
            continue
        project = store.project_for_thread(proof['owner'], proof['thread'])
        item, original = store.read(proof['owner'], proof['node'], 1)
        if item['project'] != project['id'] or hashlib.sha256(original).hexdigest() != proof['sha256']:
            raise WorkspaceError('历史文件映射未通过归属与内容验证。')
        source_id = 'legacy:' + hashlib.sha256(proof['relative_path'].encode()).hexdigest()
        with store.db() as db:
            imported = db.execute('SELECT node FROM imports WHERE project=? AND source_id=?', (project['id'], source_id)).fetchone()
        if imported is None or imported['node'] != item['id']:
            raise WorkspaceError('历史文件缺少已验证的迁移来源。')
        relative = Path(proof['relative_path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise WorkspaceError('历史文件相对路径无效。')
        current = next(n for n in store.nodes(proof['owner'], project['id']) if n['id'] == item['id'])
        receipt = {'id': item['id'], 'name': item['name'], 'type': 'file', 'size': item['size'],
                   'content_type': item['mime'], 'url': '/api/workstation/files/' + item['id'] + '/content',
                   'workstation': {'project': project['id'], 'node': item['id'], 'version': item['version']}}
        pattern = re.compile(r'(?<![\w:/])' + re.escape((Path(legacy_root) / relative).as_posix()) + r'''(?=$|[\s`"'<>),\]。；，]|[.!?](?:\s|$))''')
        references.setdefault((proof['owner'], proof['thread']), []).append((pattern, current['path'], receipt))

    def repair(message, key):
        if not isinstance(message, dict):
            return message
        result = copy.deepcopy(message)
        if 'files' in result:
            result['files'] = clean_attachment_metadata(result['files'])
        if message.get('role') != 'assistant':
            return result
        found = {}

        def clean(value):
            if isinstance(value, str):
                for pattern, relative, receipt in references.get(key, []):
                    if pattern.search(value):
                        found[receipt['id']] = receipt
                        value = pattern.sub(lambda _: relative, value)
                return clean_text(value)
            if isinstance(value, list):
                return [clean(v) for v in value]
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()}
            return value

        for field in PUBLIC_FIELDS:
            if field in result:
                result[field] = clean(result[field])
        files = result.get('files') if isinstance(result.get('files'), list) else []
        existing = {f.get('id') for f in files if isinstance(f, dict)}
        if found:
            result['files'] = files + [r for i, r in found.items() if i not in existing]
        return result

    counts = {'chat_documents_changed': 0, 'normalized_messages_changed': 0}
    with closing(sqlite3.connect(native_db)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute('SELECT c.id,c.user_id,c.chat FROM chat c JOIN user u ON u.id=c.user_id').fetchall()
        for row in rows:
            key = (row['user_id'], row['id'])
            document = decoded(row['chat'], {})
            changed = copy.deepcopy(document)
            if isinstance(changed, dict):
                if 'files' in changed:
                    changed['files'] = clean_attachment_metadata(changed['files'])
                history = changed.get('history')
                if isinstance(history, dict) and isinstance(history.get('messages'), dict):
                    history['messages'] = {i: repair(m, key) for i, m in history['messages'].items()}
                if isinstance(changed.get('messages'), list):
                    changed['messages'] = [repair(m, key) for m in changed['messages']]
                if changed != document:
                    db.execute('UPDATE chat SET chat=? WHERE id=? AND user_id=?', (json.dumps(changed, ensure_ascii=False), row['id'], row['user_id']))
                    counts['chat_documents_changed'] += 1
        columns = {r[1] for r in db.execute('PRAGMA table_info(chat_message)')}
        fields = [f for f in (*PUBLIC_FIELDS, 'files') if f in columns]
        if fields and {'id', 'chat_id', 'role'} <= columns:
            messages = db.execute("SELECT m.*,c.user_id migration_owner FROM chat_message m JOIN chat c ON c.id=m.chat_id JOIN user u ON u.id=c.user_id").fetchall()
            for row in messages:
                message = {'role': row['role'], **{f: (row[f] if f == 'context_summary' else decoded(row[f], row[f])) for f in fields}}
                updated = repair(message, (row['migration_owner'], row['chat_id']))
                if updated != message:
                    values = [updated.get(f) if f == 'context_summary' else json.dumps(updated.get(f), ensure_ascii=False) for f in fields]
                    db.execute('UPDATE chat_message SET ' + ','.join(f + '=?' for f in fields) + ' WHERE id=?', (*values, row['id']))
                    counts['normalized_messages_changed'] += 1
    return counts
