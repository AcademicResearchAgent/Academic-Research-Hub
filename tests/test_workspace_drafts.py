import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'overlays/open-webui'))
from workstation_workspace.drafts import first_title, has_messages, promote
from workstation_workspace.store import WorkspaceStore, WorkspaceError


class DraftTests(unittest.TestCase):
    def test_blank_navigation_has_no_title_and_no_work(self):
        for document in ({}, {'history': {'messages': {}}}, {'history': {'messages': {'x': {'role': 'user', 'content': ' \n '}}}}):
            self.assertFalse(has_messages(document))
            with self.assertRaises(WorkspaceError):
                first_title(document, [])
        self.assertEqual(first_title({}, [{'name': '资料.pdf'}]), '资料.pdf')
        self.assertEqual(first_title({'history': {'messages': {'u': {'role': 'user', 'content': '  我的研究\n问题  '}}}}, []), '我的研究 问题')

    def test_upload_failure_rolls_back_project_thread_and_all_files(self):
        with tempfile.TemporaryDirectory() as root:
            store = WorkspaceStore(root, max_workspace_bytes=4)
            with self.assertRaises(WorkspaceError):
                promote(store, 'alice', 'thread-a', '资料', None,
                        [{'id': '1', 'name': 'a.txt', 'content': b'123'}, {'id': '2', 'name': 'b.txt', 'content': b'456'}])
            with store.db() as db:
                for table in ('projects', 'threads', 'nodes', 'versions', 'imports'):
                    self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
            self.assertEqual(list(store.blobs.rglob('*')), [])

    def test_existing_project_promotion_is_owned_and_repeatable(self):
        with tempfile.TemporaryDirectory() as root:
            store = WorkspaceStore(root)
            first = promote(store, 'alice', 'one', 'first', None, [])
            upload = [{'id': '1', 'name': 'a.txt', 'content': b'original'}]
            for _ in range(2):
                result = promote(store, 'alice', 'two', 'second', first['id'], upload)
                self.assertEqual(result['id'], first['id'])
            self.assertEqual(len(store.projects('alice')[0]['threads']), 2)
            self.assertEqual(len(store.nodes('alice', first['id'])), 1)
            with self.assertRaises(WorkspaceError):
                promote(store, 'bob', 'foreign', 'stolen', first['id'], upload)
            self.assertEqual(store.projects('bob'), [])


if __name__ == '__main__':
    unittest.main()
