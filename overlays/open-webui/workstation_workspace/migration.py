"""Idempotent native-chat migration from a consistent, read-only SQLite view.

Message paths never select files. Only native file records owned by the chat's
real account are eligible. Each task gets its own copy; the original is retained.
"""
from collections import Counter
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

from .store import WorkspaceError


def decoded(value, fallback):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return fallback
    return value if value is not None else fallback


def attachment_ids(attachments):
    if not isinstance(attachments, list):
        return set()
    return {item['id'] for item in attachments if isinstance(item, dict)
            and isinstance(item.get('id'), str) and not item.get('workstation')
            and item.get('type', 'file') in {'file', 'image'}}


def legacy_chat_attachments(chat):
    if not isinstance(chat, dict):
        return set()
    ids = attachment_ids(chat.get('files'))
    history = chat.get('history') or {}
    messages = history.get('messages', {}) if isinstance(history, dict) else {}
    values = list(messages.values()) if isinstance(messages, dict) else []
    values += chat.get('messages', []) if isinstance(chat.get('messages'), list) else []
    for message in values:
        if isinstance(message, dict):
            ids.update(attachment_ids(message.get('files')))
    return ids


def owned_upload_bytes(path, uploads, limit):
    """Read a native storage record below uploads, rejecting every symlink hop."""
    root = Path(uploads).resolve()
    candidate = Path(path)
    # Do not resolve first: doing so would conceal an intermediate symlink.
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        parts = candidate.relative_to(root).parts
    except ValueError:
        raise WorkspaceError('附件不在已批准的上传目录内。') from None
    if not parts or any(part in {'.', '..'} for part in parts):
        raise WorkspaceError('附件路径无效。')
    if os.name == 'posix':
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for index, part in enumerate(parts):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if index < len(parts) - 1:
                    flags |= os.O_DIRECTORY
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise WorkspaceError('附件不是独立的普通文件。')
            with os.fdopen(os.dup(fd), 'rb') as source:
                data = source.read(limit + 1)
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise WorkspaceError('附件仍在写入。', 409)
        finally:
            os.close(fd)
    else:
        current = root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise WorkspaceError('附件链接不受支持。')
        if not current.is_file() or current.stat().st_nlink != 1:
            raise WorkspaceError('附件不是独立的普通文件。')
        with current.open('rb') as source:
            data = source.read(limit + 1)
    if len(data) > limit:
        raise WorkspaceError('附件超过文件大小限制。', 413)
    return data


def migrate(native_db, uploads, store=None, *, max_file_bytes=64 * 1024 * 1024, stored_upload_root=None):
    report = {'mode': 'apply' if store else 'dry-run', 'chats': [], 'issues': [], 'counts': {}}
    counts = Counter()
    with closing(sqlite3.connect(Path(native_db).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'chat', 'user', 'file'}.issubset(tables):
            raise WorkspaceError('不是受支持的原始聊天数据库。')
        chats = db.execute('SELECT c.* FROM chat c JOIN user u ON u.id=c.user_id ORDER BY c.created_at,c.id').fetchall()
        for chat in chats:
            meta = decoded(chat['meta'], {}) if 'meta' in chat.keys() else {}
            if isinstance(meta, dict) and meta.get('internal'):
                counts['internal_chats_skipped'] += 1
                continue
            owner, thread = chat['user_id'], chat['id']
            item = {'thread': thread, 'files': []}
            project = None
            if store:
                try:
                    project = store.ensure_thread(owner, thread, chat['title'])['id']
                except WorkspaceError as error:
                    if error.status == 404:
                        counts['deleted_bindings_preserved'] += 1
                        continue
                    raise
                item['project'] = project
            refs = legacy_chat_attachments(decoded(chat['chat'], {}))
            if 'chat_message' in tables:
                for message in db.execute('SELECT files FROM chat_message WHERE chat_id=?', (thread,)):
                    refs.update(attachment_ids(decoded(message['files'], [])))
            if 'chat_file' in tables:
                refs.update(row['file_id'] for row in db.execute('SELECT file_id FROM chat_file WHERE chat_id=? AND user_id=?', (thread, owner)))
            counts['chats'] += 1
            for file_id in sorted(refs):
                file = db.execute('SELECT * FROM file WHERE id=? AND user_id=?', (file_id, owner)).fetchone()
                if file is None:
                    report['issues'].append({'thread': thread, 'file': file_id, 'reason': 'missing_or_foreign_owner'})
                    counts['rejected_references'] += 1
                    continue
                try:
                    path = file['path'] or ''
                    if stored_upload_root is not None:
                        try:
                            relative = Path(path).relative_to(Path(stored_upload_root))
                        except ValueError:
                            raise WorkspaceError('附件不属于指定的原始上传目录。') from None
                        if '..' in relative.parts:
                            raise WorkspaceError('附件路径无效。')
                        path = str(Path(uploads).resolve() / relative)
                    data = owned_upload_bytes(path, uploads, max_file_bytes)
                    record = {'native_file': file_id, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                    if store:
                        node = store.create_node(owner, project, file['filename'], content=data,
                                                 source='upload', thread=thread, source_id='webui:' + file_id)
                        record['node'] = node['id']
                    item['files'].append(record)
                    counts['eligible_attachments'] += 1
                except (OSError, WorkspaceError) as error:
                    # Exception strings can disclose host paths; only record
                    # a bounded category plus opaque IDs in migration reports.
                    report['issues'].append({'thread': thread, 'file': file_id,
                                             'reason': 'unavailable_or_unsafe_content', 'category': type(error).__name__})
                    counts['unavailable_attachments'] += 1
            report['chats'].append(item)
    report['counts'] = dict(counts)
    return report
