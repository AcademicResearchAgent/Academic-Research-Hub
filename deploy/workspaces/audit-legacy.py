"""Read-only evidence audit for legacy shared outputs; never guess by filename.

Eligibility requires an authenticated chat scope, a successful write_file tool
receipt and byte-for-byte agreement with the recorded write content. Unproven
files remain unassigned. The private report contains IDs/hashes, never contents.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from workstation_models.core import session_scope
from workstation_workspace.migration import decoded, owned_upload_bytes
from workstation_workspace.store import WorkspaceError

ROOT = Path('/home/ubuntu/haudi-hermes')


def tool_result(text):
    if text.startswith('<untrusted_tool_result '):
        text = text.split('\n\n', 1)[-1].rsplit('\n</untrusted_tool_result>', 1)[0]
    return decoded(text, {})


def main():
    os.umask(0o077)
    native = ROOT / 'openwebui/data/webui.db'
    state = ROOT / 'state/state.db'
    shared = ROOT / 'workspace'
    proofs, matched = [], 0
    with closing(sqlite3.connect(native.as_uri() + '?mode=ro', uri=True)) as web:
        with closing(sqlite3.connect(state.as_uri() + '?mode=ro', uri=True)) as agent:
            web.row_factory = agent.row_factory = sqlite3.Row
            web.execute('BEGIN')
            agent.execute('BEGIN')
            models = {r[0] for r in web.execute('SELECT DISTINCT model_id FROM chat_message WHERE model_id IS NOT NULL')}
            scopes = {}
            for chat in web.execute('SELECT c.id,c.user_id FROM chat c JOIN user u ON c.user_id=u.id'):
                for model in models:
                    scopes[session_scope(chat['user_id'], model, chat['id'], '')] = {'owner': chat['user_id'], 'thread': chat['id']}
            for session in agent.execute('SELECT id,session_key FROM sessions'):
                identity = scopes.get(session['session_key'])
                if identity is None:
                    continue
                matched += 1
                for message in agent.execute("SELECT tool_calls FROM messages WHERE session_id=? AND role='assistant' AND tool_calls IS NOT NULL", (session['id'],)):
                    calls = decoded(message['tool_calls'], [])
                    if not isinstance(calls, list):
                        continue
                    for call in calls:
                        function = call.get('function', {}) if isinstance(call, dict) else {}
                        if function.get('name') != 'write_file':
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
                            content = owned_upload_bytes(path, shared, 64 * 1024 * 1024)
                        except (WorkspaceError, OSError):
                            continue
                        if content != args['content'].encode('utf-8'):
                            continue
                        proofs.append({**identity, 'relative_path': Path(path).relative_to(shared).as_posix(),
                                       'session': session['id'], 'receipt': receipt['id'],
                                       'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content),
                                       'evidence': 'owned_session_successful_write_and_exact_bytes'})
    ambiguous = {p['relative_path'] for p in proofs if len({(q['owner'], q['thread']) for q in proofs if q['relative_path'] == p['relative_path']}) > 1}
    eligible = [p for p in proofs if p['relative_path'] not in ambiguous]
    files = [p for p in shared.rglob('*') if p.is_file() and not p.is_symlink()]
    target = ROOT / 'workspace-migration-audits' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target.mkdir(parents=True, mode=0o700)
    report = {'matched_owned_sessions': matched, 'eligible': eligible,
              'ambiguous_paths': sorted(ambiguous),
              'unclassified': [p.relative_to(shared).as_posix() for p in files if p.relative_to(shared).as_posix() not in {v['relative_path'] for v in eligible}],
              'applied': False, 'originals_unchanged': True}
    (target / 'legacy-proof.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'audit': target.name, 'matched_owned_sessions': matched, 'proven_outputs': len(eligible),
                      'ambiguous_paths': len(ambiguous), 'unclassified_files': len(report['unclassified']), 'applied': False}), flush=True)


if __name__ == '__main__':
    main()
