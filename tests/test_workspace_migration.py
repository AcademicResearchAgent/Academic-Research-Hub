"""Migrate actual native SQLite fixtures; never infer authorization from text paths."""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'overlays/open-webui'))
from workstation_workspace.store import WorkspaceStore
from workstation_workspace.migration import migrate, owned_upload_bytes
from workstation_workspace.store import WorkspaceError


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.uploads = self.root / 'uploads'
        self.uploads.mkdir()
        self.native = self.root / 'webui.db'
        with closing(sqlite3.connect(self.native)) as db, db:
            db.executescript('''
                CREATE TABLE user(id TEXT PRIMARY KEY);
                CREATE TABLE chat(id TEXT PRIMARY KEY,user_id TEXT,title TEXT,chat TEXT,meta TEXT,created_at INTEGER);
                CREATE TABLE file(id TEXT PRIMARY KEY,user_id TEXT,filename TEXT,path TEXT);
                CREATE TABLE chat_message(chat_id TEXT,files TEXT);
                CREATE TABLE chat_file(chat_id TEXT,user_id TEXT,file_id TEXT);
                INSERT INTO user VALUES('alice'),('bob');
            ''')
            for thread, owner in [('a1', 'alice'), ('a2', 'alice'), ('b1', 'bob')]:
                db.execute('INSERT INTO chat VALUES(?,?,?,?,?,?)', (thread, owner, thread, '{}', '{}', 1))
            for name, owner in [('paper', 'alice'), ('private', 'bob')]:
                target = self.uploads / (name + '.pdf')
                target.write_bytes((name + ' PDF fixture').encode())
                db.execute('INSERT INTO file VALUES(?,?,?,?)', (name, owner, target.name, str(target)))
            db.execute('INSERT INTO chat_message VALUES(?,?)', ('a1', json.dumps([{'id': 'paper', 'type': 'file'}, {'id': 'private', 'type': 'file'}])))
            db.execute('INSERT INTO chat_file VALUES(?,?,?)', ('a2', 'alice', 'paper'))

    def test_dry_run_preserves_native_and_repeated_apply_has_stable_ids(self):
        before = self.native.read_bytes()
        report = migrate(self.native, self.uploads)
        self.assertEqual(report['counts']['chats'], 3)
        self.assertEqual(report['counts']['eligible_attachments'], 2)
        self.assertEqual(report['counts']['rejected_references'], 1)
        self.assertEqual(self.native.read_bytes(), before)
        store = WorkspaceStore(self.root / 'workspaces')
        first = migrate(self.native, self.uploads, store)
        second = migrate(self.native, self.uploads, store)
        self.assertEqual(first['chats'], second['chats'])
        projects = store.projects('alice')
        self.assertEqual(len(projects), 2)
        nodes = [store.nodes('alice', p['id'])[0] for p in projects]
        self.assertNotEqual(nodes[0]['id'], nodes[1]['id'])
        store.edit('alice', nodes[0]['id'], b'edited in one project', 1)
        self.assertEqual(store.read('alice', nodes[1]['id'])[1], b'paper PDF fixture')
        self.assertEqual(store.nodes('bob', store.projects('bob')[0]['id']), [])
        self.assertEqual(self.native.read_bytes(), before)

    def test_unavailable_files_and_plain_message_paths_do_not_grant_access(self):
        with closing(sqlite3.connect(self.native)) as db, db:
            db.execute('UPDATE chat SET chat=? WHERE id=?', (json.dumps({'messages': [{'role': 'assistant', 'content': str(self.uploads / 'private.pdf')}]}), 'a1'))
            db.execute('INSERT INTO file VALUES(?,?,?,?)', ('gone', 'alice', 'missing.pdf', str(self.uploads / 'missing.pdf')))
            db.execute('INSERT INTO chat_file VALUES(?,?,?)', ('a1', 'alice', 'gone'))
        store = WorkspaceStore(self.root / 'workspaces')
        result = migrate(self.native, self.uploads, store)
        self.assertEqual(result['counts']['unavailable_attachments'], 1)
        self.assertFalse(any(n['name'] == 'private.pdf' for p in store.projects('alice') for n in store.nodes('alice', p['id'])))
        project = store.project_for_thread('alice', 'a1')['id']
        store.delete_project('alice', project)
        migrate(self.native, self.uploads, store)
        self.assertEqual(len(store.projects('alice')), 1)

    def test_explicit_storage_root_translation_does_not_allow_parent_paths(self):
        stored = self.root / 'container-only-uploads'
        with closing(sqlite3.connect(self.native)) as db, db:
            db.execute('UPDATE file SET path=? WHERE id=?', (str(stored / 'paper.pdf'), 'paper'))
        result = migrate(self.native, self.uploads, stored_upload_root=stored)
        self.assertEqual(result['counts']['eligible_attachments'], 2)
        with closing(sqlite3.connect(self.native)) as db, db:
            db.execute('UPDATE file SET path=? WHERE id=?', (str(stored / '..' / 'uploads' / 'private.pdf'), 'paper'))
        result = migrate(self.native, self.uploads, stored_upload_root=stored)
        self.assertEqual(result['counts']['unavailable_attachments'], 2)
        self.assertNotIn('eligible_attachments', result['counts'])

    @unittest.skipUnless(os.name == 'posix', 'Production Linux upload traversal')
    def test_upload_reader_rejects_intermediate_links_and_special_files(self):
        private = self.root / 'private'
        private.mkdir()
        (private / 'secret').write_bytes(b'not an upload')
        (self.uploads / 'linked').symlink_to(private, target_is_directory=True)
        (self.uploads / 'leaf').symlink_to(private / 'secret')
        os.link(private / 'secret', self.uploads / 'hardlink')
        os.mkfifo(self.uploads / 'pipe')
        for name in ('linked/secret', 'leaf', 'hardlink', 'pipe'):
            with self.assertRaises((WorkspaceError, OSError)):
                owned_upload_bytes(self.uploads / name, self.uploads, 100)


if __name__ == '__main__':
    unittest.main()
