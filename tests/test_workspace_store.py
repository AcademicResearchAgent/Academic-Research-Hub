"""Real filesystem/database tests for owned workspaces, without model/network mocks."""
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'overlays/open-webui'))
from workstation_workspace.store import WorkspaceStore, WorkspaceError
from workstation_workspace.runs import begin_run, finish_run, inspect_outputs, discard_completed_copy, recover_run, recoverable_runs


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = WorkspaceStore(self.temp.name)
        self.a = self.store.ensure_thread('alice', 'chat-a', '研究 A')['id']
        self.b = self.store.ensure_thread('bob', 'chat-b', '研究 B')['id']

    def test_unified_model_and_idempotent_migration(self):
        self.assertEqual(self.store.ensure_thread('alice', 'chat-a')['id'], self.a)
        self.store.ensure_thread('alice', 'chat-a2', '实验', self.a)
        self.assertEqual(len(self.store.projects('alice')), 1)
        self.assertEqual(len(self.store.projects('alice')[0]['threads']), 2)
        self.assertEqual(self.store.project_for_thread('alice', 'chat-a2')['id'], self.a)
        with self.assertRaises(WorkspaceError):
            self.store.ensure_thread('bob', 'chat-a')
        with self.assertRaises(WorkspaceError):
            self.store.ensure_thread('alice', 'chat-a', project=self.b)

    def test_title_and_thread_delete_preserve_workspace(self):
        self.store.ensure_thread('alice', 'chat-a', '综述')
        self.assertEqual(self.store.projects('alice')[0]['title'], '综述')
        self.store.rename_project('alice', self.a, '我的课题')
        self.store.ensure_thread('alice', 'chat-a', '模型生成的新标题')
        node = self.store.create_node('alice', self.a, '综述.md', content=b'paper')
        self.store.delete_thread('alice', 'chat-a')
        self.assertEqual(self.store.projects('alice')[0]['title'], '我的课题')
        self.assertEqual(self.store.read('alice', node['id'])[1], b'paper')

    def test_background_binding_does_not_replace_last_viewed_thread(self):
        self.store.ensure_thread('alice', 'chat-a2', '第二条对话', self.a)
        self.store.project_for_thread('alice', 'chat-a2', remember=True)
        self.store.ensure_thread('alice', 'chat-a', '后台生成的标题')
        self.store.project_for_thread('alice', 'chat-a')
        run = begin_run(self.store, 'alice', 'chat-a')
        finish_run(self.store, 'alice', run['id'])
        self.assertEqual(self.store.projects('alice')[0]['last_thread'], 'chat-a2')
        with self.assertRaises(WorkspaceError):
            self.store.project_for_thread('bob', 'chat-a', remember=True)
        self.assertEqual(self.store.projects('alice')[0]['last_thread'], 'chat-a2')
        remembered = self.store.project_for_thread('alice', 'chat-a', remember=True)
        self.assertEqual(remembered['last_thread'], 'chat-a')

    def test_every_file_operation_checks_owner(self):
        node = self.store.create_node('alice', self.a, 'private.txt', content=b'private')
        for action in (
            lambda: self.store.nodes('bob', self.a),
            lambda: self.store.read('bob', node['id']),
            lambda: self.store.versions('bob', node['id']),
            lambda: self.store.edit('bob', node['id'], b'stolen', 1),
            lambda: self.store.move('bob', node['id'], name='stolen'),
            lambda: self.store.delete_node('bob', node['id']),
            lambda: self.store.create_node('bob', self.a, 'intruder'),
            lambda: self.store.delete_project('bob', self.a),
        ):
            with self.assertRaises(WorkspaceError) as error:
                action()
            self.assertEqual(error.exception.status, 404)
        self.assertEqual(self.store.read('alice', node['id'])[1], b'private')

    def test_version_conflict_and_stable_reference_on_move(self):
        node = self.store.create_node('alice', self.a, 'draft.md', content=b'v1')
        updated = self.store.edit('alice', node['id'], b'v2', 1)
        self.assertEqual(updated['version'], 2)
        with self.assertRaises(WorkspaceError) as error:
            self.store.edit('alice', node['id'], b'outdated edit', 1)
        self.assertEqual(error.exception.status, 409)
        folder = self.store.create_node('alice', self.a, '论文', directory=True)
        self.store.move('alice', node['id'], name='main.md', parent=folder['id'])
        self.assertEqual(self.store.read('alice', node['id'])[1], b'v2')
        self.assertEqual(self.store.read('alice', node['id'], 1)[1], b'v1')
        self.assertIn('论文/main.md', [n['path'] for n in self.store.nodes('alice', self.a)])
        with self.assertRaises(WorkspaceError):
            self.store.move('alice', folder['id'], name='loop', parent=folder['id'])

    def test_parent_ownership_duplicate_upload_and_recovery(self):
        folder = self.store.create_node('bob', self.b, 'folder', directory=True)
        with self.assertRaises(WorkspaceError):
            self.store.create_node('alice', self.a, 'escape', parent=folder['id'])
        first = self.store.create_node('alice', self.a, 'same.txt', content=b'one')
        second = self.store.create_node('alice', self.a, 'same.txt', content=b'two')
        self.assertNotEqual(first['name'], second['name'])
        self.store.delete_project('alice', self.a)
        with self.assertRaises(WorkspaceError):
            self.store.read('alice', first['id'])
        self.store.delete_project('alice', self.a, restore=True)
        self.assertEqual(self.store.read('alice', first['id'])[1], b'one')
        fresh = WorkspaceStore(self.temp.name)
        self.assertEqual(fresh.read('alice', second['id'])[1], b'two')

    def test_path_validation_and_archive_transaction(self):
        for name in ('..', '/etc/passwd', 'a/b', 'a\\b', '\x00x'):
            with self.assertRaises(WorkspaceError):
                self.store.create_node('alice', self.a, name)
        for unsafe in ('../escape', '/absolute', 'folder/../../escape', 'C:/windows', '..\\escape'):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as z:
                z.writestr('safe.txt', 'safe')
                z.writestr(unsafe, 'bad')
            item = self.store.create_node('alice', self.a, 'bad.zip', content=buffer.getvalue())
            before = len(self.store.nodes('alice', self.a))
            with self.assertRaises(WorkspaceError):
                self.store.extract_zip('alice', item['id'])
            self.assertEqual(len(self.store.nodes('alice', self.a)), before)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as z:
            z.writestr('paper/main.tex', 'document')
            z.writestr('paper/references.bib', 'references')
        item = self.store.create_node('alice', self.a, 'template.zip', content=buffer.getvalue())
        self.store.extract_zip('alice', item['id'])
        self.assertIn('template/paper/main.tex', [n['path'] for n in self.store.nodes('alice', self.a)])

    def test_run_snapshot_is_scoped_and_conflicting_edits_are_preserved(self):
        original = self.store.create_node('alice', self.a, 'draft.md', content=b'original')
        self.store.create_node('bob', self.b, 'private.txt', content=b'other account')
        run = begin_run(self.store, 'alice', 'chat-a')
        work = Path(run['workspace'])
        self.assertFalse((work / 'private.txt').exists())
        with self.assertRaises(WorkspaceError) as error:
            begin_run(self.store, 'alice', 'chat-a')
        self.assertEqual(error.exception.status, 409)
        self.store.edit('alice', original['id'], b'user edit', 1)
        (work / 'draft.md').write_bytes(b'agent edit')
        (work / 'report.md').write_bytes(b'generated report')
        result = finish_run(self.store, 'alice', run['id'])
        self.assertEqual(len(result['conflicts']), 1)
        self.assertEqual(self.store.read('alice', original['id'])[1], b'user edit')
        self.assertEqual(self.store.read('alice', result['conflicts'][0])[1], b'agent edit')
        self.assertIn('report.md', [n['path'] for n in self.store.nodes('alice', self.a)])
        self.assertEqual(finish_run(self.store, 'alice', run['id'])['files'], [])

    def test_history_quota_includes_deleted_files_and_other_projects(self):
        self.store.max_history_bytes = 8
        self.store.max_owner_bytes = 10
        item = self.store.create_node('alice', self.a, 'notes.txt', content=b'1234')
        self.store.edit('alice', item['id'], b'5678', 1)
        with self.assertRaises(WorkspaceError) as error:
            self.store.edit('alice', item['id'], b'9', 2)
        self.assertEqual(error.exception.status, 413)
        self.assertEqual(self.store.read('alice', item['id'])[1], b'5678')
        self.assertEqual(self.store.read('alice', item['id'], 1)[1], b'1234')
        self.store.delete_node('alice', item['id'])
        with self.assertRaises(WorkspaceError):
            self.store.create_node('alice', self.a, 'fresh.txt', content=b'x')
        other = self.store.ensure_thread('alice', 'other-quota-project')['id']
        self.store.create_node('alice', other, 'allowed.txt', content=b'12')
        with self.assertRaises(WorkspaceError):
            self.store.create_node('alice', other, 'too-much.txt', content=b'3')
        self.store.create_node('bob', self.b, 'independent.txt', content=b'1234')

    def test_failed_extract_rolls_back_metadata_and_uncommitted_version_files(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('paper/a.txt', 'first')
            archive.writestr('paper/b.txt', 'second')
        item = self.store.create_node('alice', self.a, 'package.zip', content=buffer.getvalue())
        before = {p.relative_to(self.store.blobs): p.read_bytes() for p in self.store.blobs.rglob('*') if p.is_file()}
        self.store.max_nodes = 4  # ZIP + extraction root + paper + a; b fails.
        with self.assertRaises(WorkspaceError):
            self.store.extract_zip('alice', item['id'])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM nodes WHERE project=?', (self.a,)).fetchone()[0], 1)
        after = {p.relative_to(self.store.blobs): p.read_bytes() for p in self.store.blobs.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_run_deletion_preserves_editor_changes_and_interrupted_files(self):
        item = self.store.create_node('alice', self.a, 'draft', content=b'original')
        run = begin_run(self.store, 'alice', 'chat-a')
        (Path(run['workspace']) / 'draft').unlink()
        finish_run(self.store, 'alice', run['id'], interrupted=True)
        self.assertEqual(self.store.read('alice', item['id'])[1], b'original')
        run = begin_run(self.store, 'alice', 'chat-a')
        (Path(run['workspace']) / 'draft').unlink()
        self.store.edit('alice', item['id'], b'user edit', 1)
        finish_run(self.store, 'alice', run['id'])
        self.assertEqual(self.store.read('alice', item['id'])[1], b'user edit')

    def test_interrupted_rewrite_is_not_published_and_recovery_is_owned_separate_idempotent(self):
        original = self.store.create_node('alice', self.a, 'paper.md', content=b'original')
        run = begin_run(self.store, 'alice', 'chat-a')
        work = Path(run['workspace'])
        (work / 'paper.md').write_bytes(b'partial rewrite')
        (work / 'new.txt').write_bytes(b'unfinished new output')
        with self.assertRaises(WorkspaceError):
            recover_run(self.store, 'alice', self.a, run['id'])
        result = finish_run(self.store, 'alice', run['id'], interrupted=True)
        self.assertEqual(result['files'], [])
        self.assertEqual(self.store.read('alice', original['id'])[1], b'original')
        self.assertEqual(len(self.store.nodes('alice', self.a)), 1)
        self.assertEqual(recoverable_runs(self.store, 'alice', self.a)[0]['id'], run['id'])
        for owner, project in [('bob', self.a), ('bob', self.b), ('alice', self.b)]:
            with self.assertRaises(WorkspaceError):
                recover_run(self.store, owner, project, run['id'])
        self.store.edit('alice', original['id'], b'user continued editing', 1)
        restored = recover_run(self.store, 'alice', self.a, run['id'])
        self.assertEqual(len(restored['files']), 2)
        self.assertTrue(all(n['path'].startswith('未完成文件-') for n in restored['files']))
        self.assertEqual(self.store.read('alice', original['id'])[1], b'user continued editing')
        recovered = next(n for n in restored['files'] if n['name'] == 'paper.md')
        self.assertEqual(self.store.read('alice', recovered['id'])[1], b'partial rewrite')
        self.assertEqual(recover_run(self.store, 'alice', self.a, run['id'])['files'], [])
        self.assertEqual(recoverable_runs(self.store, 'alice', self.a), [])

    def test_completed_copy_cleanup_keeps_versions_and_interrupted_recovery(self):
        item = self.store.create_node('alice', self.a, 'draft.md', content=b'original')
        run = begin_run(self.store, 'alice', 'chat-a')
        (Path(run['workspace']) / 'draft.md').write_bytes(b'finished')
        self.assertFalse(discard_completed_copy(self.store, 'alice', run['id']))
        finish_run(self.store, 'alice', run['id'])
        with self.assertRaises(WorkspaceError):
            discard_completed_copy(self.store, 'bob', run['id'])
        self.assertTrue(discard_completed_copy(self.store, 'alice', run['id']))
        self.assertFalse(Path(run['workspace']).exists())
        self.assertEqual(self.store.read('alice', item['id'])[1], b'finished')
        self.assertEqual(self.store.read('alice', item['id'], 1)[1], b'original')
        pending = begin_run(self.store, 'alice', 'chat-a')
        finish_run(self.store, 'alice', pending['id'], interrupted=True)
        self.assertFalse(discard_completed_copy(self.store, 'alice', pending['id']))
        self.assertTrue(Path(pending['workspace']).exists())

    def test_run_publication_rolls_back_as_a_batch_and_retries_without_duplicates(self):
        self.store.max_workspace_bytes = 12
        original = self.store.create_node('alice', self.a, 'draft.md', content=b'old')
        run = begin_run(self.store, 'alice', 'chat-a')
        work = Path(run['workspace'])
        (work / 'draft.md').write_bytes(b'new')
        (work / 'result.txt').write_bytes(b'result')
        # A user adds data after the snapshot. The execution output fits, but
        # its merge would exceed the live workspace quota partway through.
        concurrent = self.store.create_node('alice', self.a, 'user.txt', content=b'123456')
        with self.assertRaises(WorkspaceError) as error:
            finish_run(self.store, 'alice', run['id'])
        self.assertEqual(error.exception.status, 413)
        self.assertEqual(self.store.read('alice', original['id'])[1], b'old')
        self.assertEqual(len(self.store.versions('alice', original['id'])), 1)
        self.assertEqual({n['name'] for n in self.store.nodes('alice', self.a)}, {'draft.md', 'user.txt'})
        self.store.delete_node('alice', concurrent['id'])
        result = finish_run(self.store, 'alice', run['id'])
        self.assertEqual(len(result['files']), 2)
        edited, data = self.store.read('alice', original['id'])
        self.assertEqual((data, edited['run'], edited['thread']), (b'new', run['id'], 'chat-a'))
        self.assertEqual(len(self.store.versions('alice', original['id'])), 2)
        self.assertEqual(finish_run(self.store, 'alice', run['id'])['files'], [])

    @unittest.skipUnless(os.name == 'posix', 'Production Linux descriptor-bound traversal')
    def test_output_collection_never_follows_symlinks_hardlinks_or_pipes(self):
        run = begin_run(self.store, 'alice', 'chat-a')
        work = Path(run['workspace'])
        secret = self.store.root / 'not-mounted-secret'
        secret.write_bytes(b'PRIVATE')
        (work / 'symlink').symlink_to(secret)
        (work / 'directory-link').symlink_to(self.store.blobs, target_is_directory=True)
        os.link(secret, work / 'hardlink')
        os.mkfifo(work / 'pipe')
        (work / 'report').write_bytes(b'PUBLIC')
        files, dirs, skipped = inspect_outputs(work, max_file_bytes=100, max_workspace_bytes=1000, max_nodes=10)
        self.assertEqual(files, {'report': b'PUBLIC'})
        self.assertEqual(set(skipped), {'symlink', 'directory-link', 'hardlink', 'pipe'})


if __name__ == '__main__':
    unittest.main()
