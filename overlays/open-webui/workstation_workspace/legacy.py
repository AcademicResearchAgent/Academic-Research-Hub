"""Conservative legacy-output attribution from native ownership and tool receipts.

The caller supplies the production session-scope function, not a client-supplied
identity map. No reply path, guessed filename or precomputed report grants access.
"""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3

from .migration import decoded, owned_upload_bytes
from .store import WorkspaceError


def tool_result(text):
    if text.startswith('<untrusted_tool_result '):
        text = text.split('\n\n', 1)[-1].rsplit('\n</untrusted_tool_result>', 1)[0]
    return decoded(text, {})


def inventory(shared):
    """Inventory names without traversing symlink directories or opening files."""
    found = []
    for current, dirs, files in os.walk(shared, followlinks=False):
        for name in dirs[:]:
            path = Path(current) / name
            if path.is_symlink():
                found.append(path.relative_to(shared).as_posix())
                dirs.remove(name)
        found.extend((Path(current) / name).relative_to(shared).as_posix() for name in files)
    return sorted(found)


def migrate_legacy(native_db, agent_db, shared, scope_resolver, store=None):
    shared = Path(shared).resolve()
    proofs, titles, matched = [], {}, 0
    with closing(sqlite3.connect(Path(native_db).resolve().as_uri() + '?mode=ro', uri=True)) as web:
        with closing(sqlite3.connect(Path(agent_db).resolve().as_uri() + '?mode=ro', uri=True)) as agent:
            web.row_factory = agent.row_factory = sqlite3.Row
            web.execute('BEGIN')
            agent.execute('BEGIN')
            models = {r[0] for r in web.execute('SELECT DISTINCT model_id FROM chat_message WHERE model_id IS NOT NULL')}
            scopes = {}
            for chat in web.execute('SELECT c.id,c.user_id,c.title,c.chat,c.meta FROM chat c JOIN user u ON c.user_id=u.id'):
                meta = decoded(chat['meta'], {})
                if isinstance(meta, dict) and meta.get('internal'):
                    continue
                chat_data = decoded(chat['chat'], {})
                chat_models = chat_data.get('models', []) if isinstance(chat_data, dict) else []
                candidates = models | {m for m in chat_models if isinstance(m, str)} if isinstance(chat_models, list) else models
                titles[chat['id']] = chat['title']
                for model in candidates:
                    scope = scope_resolver(chat['user_id'], model, chat['id'], '')
                    identity = (chat['user_id'], chat['id'])
                    if scope in scopes and scopes[scope] != identity:
                        raise WorkspaceError('历史会话归属存在冲突。')
                    scopes[scope] = identity
            for session in agent.execute('SELECT id,session_key FROM sessions'):
                identity = scopes.get(session['session_key'])
                if identity is None:
                    continue
                matched += 1
                messages = agent.execute("SELECT tool_calls FROM messages WHERE session_id=? AND role='assistant' AND tool_calls IS NOT NULL", (session['id'],))
                for message in messages:
                    calls = decoded(message['tool_calls'], [])
                    if not isinstance(calls, list):
                        continue
                    for call in calls:
                        function = call.get('function', {}) if isinstance(call, dict) else {}
                        if not isinstance(function, dict) or function.get('name') != 'write_file':
                            continue
                        args = decoded(function.get('arguments'), {})
                        if not isinstance(args, dict) or not isinstance(args.get('content'), str):
                            continue
                        receipt = agent.execute("SELECT id,content FROM messages WHERE session_id=? AND tool_call_id=? AND role='tool' AND tool_name='write_file' ORDER BY id DESC LIMIT 1", (session['id'], call.get('id'))).fetchone()
                        if receipt is None:
                            continue
                        result = tool_result(receipt['content'] or '')
                        if not isinstance(result, dict) or result.get('error') or result.get('success') is False:
                            continue
                        path = result.get('resolved_path')
                        if not isinstance(path, str) or not Path(path).is_absolute():
                            continue
                        try:
                            data = owned_upload_bytes(path, shared, 64 * 1024 * 1024)
                        except (WorkspaceError, OSError):
                            continue
                        if data != args['content'].encode('utf-8'):
                            continue
                        proofs.append({'owner': identity[0], 'thread': identity[1],
                                       'relative_path': Path(path).relative_to(shared).as_posix(),
                                       'session': session['id'], 'receipt': receipt['id'],
                                       'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                                       'evidence': 'owned_session_successful_write_and_exact_bytes'})
    identities = {}
    for proof in proofs:
        identities.setdefault(proof['relative_path'], set()).add((proof['owner'], proof['thread']))
    ambiguous = {path for path, owners in identities.items() if len(owners) > 1}
    # Multiple successful writes by the same thread are a single legacy file.
    eligible = list({p['relative_path']: p for p in proofs if p['relative_path'] not in ambiguous}.values())
    issues = []
    if store:
        for proof in eligible:
            try:
                # Re-read after auditing. A changed source is not imported using
                # an obsolete receipt, even if an operator saved the old report.
                data = owned_upload_bytes(shared / proof['relative_path'], shared, store.max_file_bytes)
                if hashlib.sha256(data).hexdigest() != proof['sha256']:
                    raise WorkspaceError('历史产物在迁移期间发生变化。', 409)
                with store.db() as db:
                    owner, thread = proof['owner'], proof['thread']
                    project = store.ensure_thread(owner, thread, titles[thread])['id']
                    source_id = 'legacy:' + hashlib.sha256(proof['relative_path'].encode()).hexdigest()
                    existing = db.execute('SELECT node FROM imports WHERE project=? AND source_id=?', (project, source_id)).fetchone()
                    if existing:
                        proof.update(project=project, node=existing['node'], already_imported=True)
                        continue
                    parent = ''
                    relative = Path(proof['relative_path'])
                    for part in relative.parts[:-1]:
                        row = db.execute('SELECT id,kind FROM nodes WHERE project=? AND parent=? AND name=? AND deleted=0', (project, parent, part)).fetchone()
                        if row:
                            if row['kind'] != 'directory':
                                raise WorkspaceError('迁移目录与现有文件冲突。', 409)
                            parent = row['id']
                        else:
                            parent = store.create_node(owner, project, part, parent=parent, directory=True, source='migration', thread=thread)['id']
                    node = store.create_node(owner, project, relative.name, parent=parent, content=data,
                                             source='migration', thread=thread, source_id=source_id)
                    proof.update(project=project, node=node['id'], already_imported=False)
            except (OSError, WorkspaceError) as error:
                issues.append({'thread': proof['thread'], 'sha256': proof['sha256'], 'category': type(error).__name__, 'status': getattr(error, 'status', None)})
    return {'matched_owned_sessions': matched, 'eligible': eligible, 'ambiguous_paths': sorted(ambiguous),
            'unclassified': [p for p in inventory(shared) if p not in {e['relative_path'] for e in eligible}],
            'issues': issues, 'applied': store is not None, 'originals_unchanged': True}
