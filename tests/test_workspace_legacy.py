from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'overlays/open-webui'))
from workstation_models.core import session_scope
from workstation_workspace.legacy import migrate_legacy
from workstation_workspace.store import WorkspaceStore
from workstation_workspace.history import repair_history


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.shared = self.root / 'shared'
        self.shared.mkdir()
        self.web = self.root / 'web.db'
        self.agent = self.root / 'agent.db'
        with closing(sqlite3.connect(self.web)) as db, db:
            db.executescript('''CREATE TABLE user(id TEXT); CREATE TABLE chat(id TEXT,user_id TEXT,title TEXT,chat TEXT,meta TEXT);
                CREATE TABLE chat_message(model_id TEXT); INSERT INTO user VALUES('alice'),('bob');
                INSERT INTO chat VALUES('a','alice','Alice project','{}','{}'),('b','bob','Bob project','{}','{}');
                INSERT INTO chat_message VALUES('model-a');''')
        with closing(sqlite3.connect(self.agent)) as db, db:
            db.executescript('''CREATE TABLE sessions(id TEXT,session_key TEXT);
                CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,tool_calls TEXT,tool_call_id TEXT,tool_name TEXT,content TEXT);''')
            for user, thread in [('alice', 'a'), ('bob', 'b')]:
                db.execute('INSERT INTO sessions VALUES(?,?)', (thread, session_scope(user, 'model-a', thread, '')))
        self.store = WorkspaceStore(self.root / 'store')

    def record(self, thread, relative, content, call='call', error=False):
        path = self.shared / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        calls = [{'id': call, 'function': {'name': 'write_file', 'arguments': json.dumps({'content': content})}}]
        result = {'resolved_path': str(path)}
        if error:
            result['error'] = 'failed'
        with closing(sqlite3.connect(self.agent)) as db, db:
            db.execute("INSERT INTO messages(session_id,role,tool_calls) VALUES(?,'assistant',?)", (thread, json.dumps(calls)))
            db.execute("INSERT INTO messages(session_id,role,tool_call_id,tool_name,content) VALUES(?,'tool',?,'write_file',?)", (thread, call, json.dumps(result)))
        return path

    def migrate(self, apply=False):
        return migrate_legacy(self.web, self.agent, self.shared, session_scope, self.store if apply else None)

    def test_proven_file_is_owned_nested_idempotent_and_preserves_user_edits(self):
        path = self.record('a', 'papers/review.md', 'Synthetic source')
        before = (self.web.read_bytes(), self.agent.read_bytes(), path.read_bytes())
        result = self.migrate()
        self.assertEqual(len(result['eligible']), 1)
        self.assertEqual(self.store.projects('alice'), [])
        first = self.migrate(True)['eligible'][0]
        self.assertEqual(first['owner'], 'alice')
        self.assertEqual(self.store.read('alice', first['node'])[1], b'Synthetic source')
        self.assertIn('papers/review.md', [n['path'] for n in self.store.nodes('alice', first['project'])])
        self.store.edit('alice', first['node'], b'User revision', 1)
        second = self.migrate(True)['eligible'][0]
        self.assertEqual(first['node'], second['node'])
        self.assertTrue(second['already_imported'])
        self.assertEqual(self.store.read('alice', first['node'])[1], b'User revision')
        self.assertEqual(before, (self.web.read_bytes(), self.agent.read_bytes(), path.read_bytes()))
        self.assertEqual(self.store.projects('bob'), [])

    def test_ambiguous_changed_failed_and_unowned_outputs_are_not_imported(self):
        self.record('a', 'shared.md', 'same', 'a-call')
        self.record('b', 'shared.md', 'same', 'b-call')
        self.record('a', 'changed.md', 'original', 'changed').write_text('changed after tool receipt')
        self.record('a', 'failed.md', 'failed', 'failed', error=True)
        self.record('unknown-session', 'unowned.md', 'unowned', 'unowned')
        result = self.migrate(True)
        self.assertEqual(result['eligible'], [])
        self.assertEqual(result['ambiguous_paths'], ['shared.md'])
        self.assertEqual(len(result['unclassified']), 4)
        self.assertEqual(self.store.projects('alice'), [])

    def test_repeated_writes_do_not_duplicate_and_deleted_project_stays_deleted(self):
        self.record('a', 'same.md', 'same', 'first')
        self.record('a', 'same.md', 'same', 'second')
        result = self.migrate(True)
        self.assertEqual(len(result['eligible']), 1)
        proof = result['eligible'][0]
        self.store.delete_project('alice', proof['project'])
        result = self.migrate(True)
        self.assertEqual(result['issues'][0]['status'], 404)
        self.assertEqual(self.store.projects('alice'), [])

    def test_history_receipts_require_matching_owner_and_preserve_user_messages(self):
        self.record('a', 'papers/review.md', 'Synthetic source')
        proof = self.migrate(True)['eligible'][0]
        legacy_root = '/home/ubuntu/haudi-hermes/workspace'
        content = '已生成 `' + legacy_root + '/papers/review.md`，未关联 /home/ubuntu/private.txt 。'
        user = {'id': 'user', 'role': 'user', 'content': '请解释 /home/example 的含义'}
        assistant = {'id': 'assistant', 'role': 'assistant', 'content': content}
        document = {'history': {'messages': {'user': user, 'assistant': assistant}}, 'messages': [user, assistant]}
        with closing(sqlite3.connect(self.web)) as db, db:
            for column in ('id', 'chat_id', 'role', 'content', 'files', 'status_history'):
                db.execute('ALTER TABLE chat_message ADD COLUMN ' + column + ' TEXT')
            for thread in ('a', 'b'):
                db.execute('UPDATE chat SET chat=? WHERE id=?', (json.dumps(document), thread))
                db.execute('INSERT INTO chat_message(id,chat_id,role,content,files,status_history) VALUES(?,?,?,?,?,?)',
                           (thread + '-assistant', thread, 'assistant', json.dumps(content), '[]', json.dumps([{'description': '/opt/hermes/private'}])))
        report = repair_history(self.web, self.store, [proof], legacy_root)
        self.assertEqual(report, {'chat_documents_changed': 2, 'normalized_messages_changed': 2})
        with closing(sqlite3.connect(self.web)) as db:
            own = json.loads(db.execute("SELECT chat FROM chat WHERE id='a'").fetchone()[0])
            foreign = json.loads(db.execute("SELECT chat FROM chat WHERE id='b'").fetchone()[0])
            normalized = db.execute("SELECT content,files,status_history FROM chat_message WHERE id='a-assistant'").fetchone()
        self.assertEqual(own['messages'][0], user)
        self.assertEqual(own['history']['messages']['assistant'], own['messages'][1])
        self.assertNotIn('/home/ubuntu/', own['messages'][1]['content'])
        self.assertIn('papers/review.md', own['messages'][1]['content'])
        self.assertEqual(own['messages'][1]['files'][0]['id'], proof['node'])
        self.assertNotIn('files', foreign['messages'][1])
        self.assertNotIn(proof['node'], json.dumps(foreign))
        self.assertEqual(json.loads(normalized[1])[0]['id'], proof['node'])
        self.assertNotIn('/opt/hermes', normalized[2])
        self.assertEqual(repair_history(self.web, self.store, [proof], legacy_root),
                         {'chat_documents_changed': 0, 'normalized_messages_changed': 0})

    def test_upload_storage_metadata_is_removed_from_every_export_shape(self):
        attachment = {'id': 'native-owned-file', 'type': 'file', 'name': 'paper.pdf',
                      'url': '/api/v1/files/native-owned-file/content',
                      'file': {'id': 'native-owned-file', 'path': '/app/backend/data/uploads/private-paper.pdf',
                               'meta': {'name': 'paper.pdf', 'size': 123}}}
        text = '用户原文：请解释 /home/example 和 /app/example。'
        user = {'id': 'user', 'role': 'user', 'content': text, 'files': [attachment]}
        assistant = {'id': 'assistant', 'role': 'assistant', 'content': '原件存于 /app/backend/data/uploads/private-paper.pdf 。'}
        document = {'files': [attachment], 'history': {'messages': {'user': user, 'assistant': assistant}},
                    'messages': [user, assistant]}
        with closing(sqlite3.connect(self.web)) as db, db:
            for column in ('id', 'chat_id', 'role', 'content', 'files'):
                db.execute('ALTER TABLE chat_message ADD COLUMN ' + column + ' TEXT')
            db.execute("UPDATE chat SET chat=? WHERE id='a'", (json.dumps(document),))
            for message in (user, assistant):
                db.execute('INSERT INTO chat_message(id,chat_id,role,content,files) VALUES(?,?,?,?,?)',
                           (message['id'], 'a', message['role'], json.dumps(message['content']), json.dumps(message.get('files', []))))
        report = repair_history(self.web, self.store, [], '/home/ubuntu/haudi-hermes/workspace')
        self.assertEqual(report, {'chat_documents_changed': 1, 'normalized_messages_changed': 2})
        with closing(sqlite3.connect(self.web)) as db:
            repaired = json.loads(db.execute("SELECT chat FROM chat WHERE id='a'").fetchone()[0])
            stored_user = db.execute("SELECT content,files FROM chat_message WHERE id='user'").fetchone()
        for files in (repaired['files'], repaired['messages'][0]['files'],
                      repaired['history']['messages']['user']['files'], json.loads(stored_user[1])):
            self.assertNotIn('path', files[0]['file'])
            self.assertEqual(files[0]['url'], attachment['url'])
            self.assertEqual(files[0]['id'], attachment['id'])
            self.assertEqual(files[0]['file']['meta'], attachment['file']['meta'])
        self.assertEqual(repaired['messages'][0]['content'], text)
        self.assertEqual(json.loads(stored_user[0]), text)
        self.assertNotIn('/app/backend/', repaired['messages'][1]['content'])
        self.assertEqual(repair_history(self.web, self.store, [], '/home/ubuntu/haudi-hermes/workspace'),
                         {'chat_documents_changed': 0, 'normalized_messages_changed': 0})

    def test_complete_offline_batch_preserves_sources_edits_and_quarantines_unknown_files(self):
        source = self.record('a', 'review.md', 'Synthetic proven output')
        unknown = self.shared / 'unattributed.txt'
        unknown.write_bytes(b'Synthetic unowned content')
        uploads = self.root / 'uploads'
        uploads.mkdir()
        original = uploads / 'paper.pdf'
        original.write_bytes(b'Synthetic original upload')
        attachment = {'id': 'uploaded', 'type': 'file', 'file': {'path': '/app/backend/data/uploads/paper.pdf'}}
        user = {'id': 'u', 'role': 'user', 'content': 'Keep this /app/example user text', 'files': [attachment]}
        answer = {'id': 'a', 'role': 'assistant', 'content': 'Output: ' + source.as_posix()}
        document = {'files': [attachment], 'history': {'messages': {'u': user, 'a': answer}}}
        with closing(sqlite3.connect(self.web)) as db, db:
            db.execute('ALTER TABLE chat ADD COLUMN created_at INTEGER DEFAULT 1')
            db.execute('CREATE TABLE file(id TEXT,user_id TEXT,filename TEXT,path TEXT)')
            db.execute('INSERT INTO file VALUES(?,?,?,?)', ('uploaded', 'alice', 'paper.pdf', '/app/backend/data/uploads/paper.pdf'))
            for column in ('id', 'chat_id', 'role', 'content', 'files'):
                db.execute('ALTER TABLE chat_message ADD COLUMN ' + column + ' TEXT')
            db.execute("UPDATE chat SET chat=? WHERE id='a'", (json.dumps(document),))
        path = Path(__file__).resolve().parents[1] / 'deploy/workspaces/migration-batch.py'
        spec = importlib.util.spec_from_file_location('migration_batch_fixture', path)
        batch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(batch)
        before = (source.read_bytes(), unknown.read_bytes(), original.read_bytes(), self.agent.read_bytes())
        report_dir = self.root / 'reports'
        first = batch.migrate_batch(self.web, self.agent, self.shared, uploads, self.store, report_dir)
        self.assertEqual((first['native_attachments'], first['proven_legacy_outputs'], first['quarantined_files']), (1, 1, 1))
        self.assertEqual(first['content_hashes_verified'], 2)
        project = self.store.project_for_thread('alice', 'a')['id']
        nodes = self.store.nodes('alice', project)
        self.assertEqual({node['name'] for node in nodes}, {'paper.pdf', 'review.md'})
        self.assertEqual(self.store.nodes('bob', self.store.project_for_thread('bob', 'b')['id']), [])
        output = next(node for node in nodes if node['name'] == 'review.md')
        self.store.edit('alice', output['id'], b'Edited after migration', 1)
        second = batch.migrate_batch(self.web, self.agent, self.shared, uploads, self.store, report_dir)
        self.assertEqual(self.store.read('alice', output['id'])[1], b'Edited after migration')
        self.assertEqual(second['history_repair'], {'chat_documents_changed': 0, 'normalized_messages_changed': 0})
        self.assertEqual(before, (source.read_bytes(), unknown.read_bytes(), original.read_bytes(), self.agent.read_bytes()))
        inventory = json.loads((report_dir / 'quarantine/inventory.json').read_text())
        self.assertEqual((report_dir / 'quarantine' / inventory[0]['copy']).read_bytes(), unknown.read_bytes())


if __name__ == '__main__':
    unittest.main()
