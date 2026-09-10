"""Initial cutover failure boundaries with real SQLite/files and service doubles."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(os.name == 'nt', 'The deployment controller uses Linux service/locking semantics')
class CutoverFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        path = ROOT / 'deploy/workspaces/production-cutover.py'
        spec = importlib.util.spec_from_file_location('cutover_failure_test', path)
        self.cutover = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cutover)
        self.control = self.cutover.control
        self.systemd = self.root / 'systemd'
        self.systemd.mkdir()
        for label in ('openwebui/data', 'state', 'workspace', 'workspace-production-plans'):
            (self.root / label).mkdir(parents=True)
        for relative in ('openwebui/data/webui.db', 'state/state.db'):
            with sqlite3.connect(self.root / relative) as db:
                db.execute('CREATE TABLE retained(value TEXT)')
                db.execute("INSERT INTO retained VALUES ('original')")
        (self.root / 'workspace/original.txt').write_text('retained original')
        self.plan = self.root / 'workspace-production-plans/fixture.json'
        self.plan.write_text(json.dumps({'script_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'source_release': 'synthetic', 'ui': {'image': 'sha256:' + 'a' * 64},
            'worker_image': 'sha256:' + 'b' * 64}))
        (self.root / 'workspace-history-browser-verification.json').write_text(json.dumps({
            'passed': True, 'source_release': 'synthetic', 'preview_image': 'sha256:' + 'a' * 64}))
        self.commands = []
        self.migration_error = False
        self.health_error = False
        original_load = self.cutover.load
        def load(name, path):
            if name == 'production_migration_batch':
                return SimpleNamespace(migrate_batch=self.migrate)
            return original_load(name, path)
        overrides = [(self.cutover, 'ROOT', self.root), (self.control, 'ROOT', self.root),
                     (self.cutover, 'SYSTEMD', self.systemd),
                     (self.cutover, 'require_legacy_baseline', lambda: None),
                     (self.cutover, 'source_directory', lambda release: ROOT),
                     (self.cutover, 'verify_preview_source', lambda *args: None),
                     (self.cutover, 'legacy_work', lambda: {'active_agents': 0}),
                     (self.cutover, 'CGROUP_ROOT', self.root / 'cgroup'),
                     (self.cutover, 'legacy_listener_closed', lambda: True),
                     (self.cutover, 'load', load), (self.control, 'command', self.command),
                     (self.control, 'resume_broker', lambda config: None),
                     (self.control, 'start_ui', lambda config, image: self.commands.append(('start-new-ui',))),
                     (self.control, 'health', self.health),
                     (self.cutover.subprocess, 'run', self.cleanup_command)]
        for obj, name, value in overrides:
            override = patch.object(obj, name, value)
            override.start()
            self.addCleanup(override.stop)

    def command(self, *args):
        self.commands.append(args)
        if args[:2] == ('systemctl', 'show'):
            return 'ActiveState=failed\nMainPID=0\nControlGroup='
        if args[:2] == ('docker', 'ps'):
            return 'haudi-openwebui'
        return ''

    def cleanup_command(self, args, **kwargs):
        self.commands.append(tuple(args))
        return SimpleNamespace(returncode=0)

    def health(self, config):
        if self.health_error:
            raise RuntimeError('synthetic new UI health failure')

    def migrate(self, native, agent, shared, uploads, store, reports):
        project = store.ensure_thread('synthetic-owner', 'synthetic-thread')
        self.new_file = store.create_node('synthetic-owner', project['id'], 'new-result.txt', content=b'new isolated data')
        with sqlite3.connect(native) as db:
            db.execute("INSERT INTO retained VALUES ('new isolated message')")
        if self.migration_error:
            raise RuntimeError('synthetic failure after first isolated write')
        return {'synthetic_migration': True}

    def event(self):
        records = list((self.root / 'workspace-production-backups').glob('*/cutover-event.json'))
        self.assertEqual(len(records), 1)
        return json.loads(records[0].read_text())

    def assert_protected(self):
        self.assertEqual(self.event()['phase'], 'maintenance')
        self.assertTrue((self.root / 'workspace-production.json').exists())
        guard = self.systemd / (self.cutover.LEGACY_SERVICE + '.d/workstation-workspace-cutover.conf')
        self.assertIn('ConditionPathExists=!' + str(self.root / 'workspace-production.json'), guard.read_text())
        self.assertIn(('systemctl', 'disable', self.cutover.LEGACY_SERVICE), self.commands)
        self.assertNotIn(('systemctl', 'start', self.cutover.LEGACY_SERVICE), self.commands)
        self.assertNotIn(('docker', 'start', 'haudi-openwebui'), self.commands)
        with sqlite3.connect(self.root / 'openwebui/data/webui.db') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM retained').fetchone()[0], 2)
        self.assertEqual((self.root / 'workspace/original.txt').read_text(), 'retained original')
        from workstation_workspace.store import WorkspaceStore
        store = WorkspaceStore(self.root / 'workspace-production-store')
        self.assertEqual(store.read('synthetic-owner', self.new_file['id'])[1], b'new isolated data')

    def test_backup_failure_restores_intake_before_any_isolated_write(self):
        with patch.object(self.cutover.shutil, 'copytree', side_effect=OSError('synthetic full disk')):
            with self.assertRaises(OSError):
                self.cutover.apply(self.plan)
        self.assertEqual(self.event()['phase'], 'aborted_before_migration')
        self.assertIn(('systemctl', 'start', self.cutover.LEGACY_SERVICE), self.commands)
        self.assertIn(('docker', 'start', 'haudi-openwebui'), self.commands)
        self.assertFalse((self.root / 'workspace-production-store').exists())
        self.assertFalse((self.root / 'workspace-production.json').exists())

    def test_failed_exit_state_is_accepted_only_when_no_processes_or_listener_remain(self):
        self.cutover.assert_legacy_stopped()
        with patch.object(self.cutover, 'legacy_listener_closed', lambda: False):
            with self.assertRaises(AssertionError):
                self.cutover.assert_legacy_stopped()
        with patch.object(self.control, 'command', lambda *args: 'ActiveState=failed\nMainPID=123\nControlGroup='):
            with self.assertRaises(AssertionError):
                self.cutover.assert_legacy_stopped()
        directory = self.root / 'cgroup/system.slice' / self.cutover.LEGACY_SERVICE
        directory.mkdir(parents=True)
        (directory / 'cgroup.procs').write_text('456\n')
        with patch.object(self.control, 'command', lambda *args: 'ActiveState=failed\nMainPID=0\nControlGroup=/system.slice/' + self.cutover.LEGACY_SERVICE):
            with self.assertRaises(AssertionError):
                self.cutover.assert_legacy_stopped()

    def test_partial_migration_retains_new_data_and_never_reopens_shared_agent(self):
        self.migration_error = True
        with self.assertRaises(RuntimeError):
            self.cutover.apply(self.plan)
        self.assert_protected()
        self.assertEqual(self.event()['failed_step'], 'migrating')

    def test_new_ui_failure_retains_new_data_stops_intake_and_keeps_legacy_disabled(self):
        self.health_error = True
        with self.assertRaises(RuntimeError):
            self.cutover.apply(self.plan)
        self.assert_protected()
        self.assertIn(('start-new-ui',), self.commands)
        self.assertIn(('docker', 'stop', '--time', '30', 'haudi-openwebui'), self.commands)
        self.assertIn(('systemctl', 'stop', 'haudi-workspace-broker-production.service'), self.commands)


if __name__ == '__main__':
    unittest.main()
