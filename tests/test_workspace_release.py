"""Release failure recovery with real persistent files/SQLite and service doubles.

Real container rollback and browser behavior are covered by the server roundtrip
verifier. These tests inject failures that should not be induced on user data.
"""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OLD = 'sha256:' + 'a' * 64
TARGET = 'sha256:' + 'b' * 64


@unittest.skipUnless(sys.platform == 'linux', 'Deployment release control uses Linux flock')
class ReleaseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        spec = importlib.util.spec_from_file_location('release_fixture', ROOT / 'deploy/workspaces/release-control.py')
        self.control = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.control)
        self.control.ROOT = self.root
        self.config = self.control.configuration('preview')
        for path in (self.config['data'], self.config['workspace']):
            path.mkdir(parents=True)
        self.native = self.config['data'] / 'webui.db'
        with sqlite3.connect(self.native) as db:
            db.execute('CREATE TABLE messages(content TEXT)')
            db.execute('INSERT INTO messages VALUES (?)', ('existing message',))
        with sqlite3.connect(self.config['workspace'] / 'workspaces.db') as db:
            db.execute('CREATE TABLE runs(id TEXT, status TEXT)')
        self.file = self.config['workspace'] / 'new-file.txt'
        self.file.write_text('file created after fallback checkpoint')
        self.current = {'scope': 'preview', 'ui': {'image': OLD},
                        'broker': {'source_release': 'fixture'}, 'unit_sha256': 'fixture',
                        'schemas': self.control.schemas(self.config)}
        self.config['ui_record'].write_text(json.dumps(self.current['ui']))
        checkpoint_dir = self.root / 'workspace-release-checkpoints'
        checkpoint_dir.mkdir()
        self.checkpoint = checkpoint_dir / 'fallback.json'
        self.checkpoint.write_text(json.dumps({**self.current, 'ui': {'image': TARGET}}))
        self.destination = self.root / 'workspace-release-backups' / 'fixture'
        self.destination.mkdir(parents=True)
        self.name = self.config['name']
        self.containers = {self.name: {'image': OLD, 'running': True}}
        self.service_running = True
        self.draining = False
        self.health_calls = 0
        self.startup = lambda: None
        self.fail_target_health = False
        for attr, replacement in (('validate', lambda config: self.current),
                                  ('command', self.command), ('broker', self.broker),
                                  ('start_ui', self.start_ui), ('health', self.health)):
            override = patch.object(self.control, attr, replacement)
            override.start()
            self.addCleanup(override.stop)

    def command(self, *args):
        if args[:3] == ('docker', 'image', 'inspect'):
            return args[3]
        if args[:2] == ('docker', 'ps'):
            names = self.containers if '-a' in args else {n: value for n, value in self.containers.items() if value['running']}
            # Only worker containers carry the managed label.
            if '--filter' in args:
                return ''
            return '\n'.join(names)
        if args[:2] == ('docker', 'stop'):
            self.containers[args[-1]]['running'] = False
            return args[-1]
        if args[:2] == ('docker', 'start'):
            self.containers[args[-1]]['running'] = True
            return args[-1]
        if args[:2] == ('docker', 'rename'):
            assert args[3] not in self.containers
            self.containers[args[3]] = self.containers.pop(args[2])
            return ''
        if args[0] == 'systemctl':
            self.service_running = args[1] == 'start'
            return ''
        raise AssertionError('Unexpected service command')

    def broker(self, config, method, path):
        if path == '/drain':
            self.draining = True
        if path == '/resume':
            self.draining = False
        return {'status': 'draining' if self.draining else 'ok', 'requests': 0}

    def start_ui(self, config, image):
        self.containers[self.name] = {'image': image, 'running': True}
        self.startup()

    def health(self, config):
        self.health_calls += 1
        if self.fail_target_health and self.containers[self.name]['image'] == TARGET:
            raise RuntimeError('Synthetic target startup failure')

    def switch(self):
        return self.control.switch(self.config, self.checkpoint, OLD, self.destination)

    def report(self):
        return json.loads((self.destination / 'release-event.json').read_text())

    def test_failed_target_preserves_new_writes_and_restores_previous_service(self):
        def startup():
            self.file.write_text('new write made before target failed')
            with sqlite3.connect(self.native) as db:
                db.execute('INSERT INTO messages VALUES (?)', ('new message made before target failed',))
        self.startup = startup
        self.fail_target_health = True
        with self.assertRaises(RuntimeError):
            self.switch()
        self.assertEqual(self.containers[self.name], {'image': OLD, 'running': True})
        self.assertTrue(self.service_running)
        self.assertFalse(self.draining)
        self.assertEqual(self.file.read_text(), 'new write made before target failed')
        with sqlite3.connect(self.native) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM messages').fetchone()[0], 2)
        self.assertEqual((self.destination / 'workspace/new-file.txt').read_text(), 'file created after fallback checkpoint')
        self.assertEqual(self.report()['recovery'], 'previous_release_restored_with_current_data')
        self.assertIs(self.report()['data_restore_performed'], False)

    def test_schema_change_stays_in_maintenance_and_keeps_changed_database(self):
        def startup():
            with sqlite3.connect(self.native) as db:
                db.execute('CREATE TABLE incompatible_change(value TEXT)')
                db.execute('INSERT INTO incompatible_change VALUES (?)', ('retained',))
        self.startup = startup
        with self.assertRaises(AssertionError):
            self.switch()
        self.assertFalse(self.service_running)
        self.assertFalse(any(item['running'] for item in self.containers.values()))
        self.assertEqual(self.report()['recovery'], 'maintenance_schema_changed_preserve_all_data')
        with sqlite3.connect(self.native) as db:
            self.assertEqual(db.execute('SELECT value FROM incompatible_change').fetchone()[0], 'retained')
        self.assertEqual(self.file.read_text(), 'file created after fallback checkpoint')

    def test_backup_failure_resumes_existing_service_without_replacing_data(self):
        with patch.object(self.control, 'backup', side_effect=OSError('Synthetic disk failure')):
            with self.assertRaises(OSError):
                self.switch()
        self.assertEqual(self.containers, {self.name: {'image': OLD, 'running': True}})
        self.assertTrue(self.service_running)
        self.assertFalse(self.draining)
        self.assertEqual(self.file.read_text(), 'file created after fallback checkpoint')
        self.assertEqual(self.report()['recovery'], 'previous_release_restored_with_current_data')


if __name__ == '__main__':
    unittest.main()
