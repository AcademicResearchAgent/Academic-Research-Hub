"""Cancellation races at real storage boundaries; Docker/provider calls are doubles.

These are deterministic fault-injection checks, not container isolation evidence.
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'overlays/open-webui'))


class Response:
    def __init__(self, **kwargs):
        self.events = []

    async def prepare(self, request):
        pass

    async def write(self, value):
        self.events.append(value)


class Request:
    path = '/run'

    async def json(self):
        return {'owner': 'synthetic-owner', 'thread': 'synthetic-thread',
                'model_id': 'ws-test', 'messages': [],
                'runtime': {'model': 'synthetic', 'base_url': 'http://invalid.local', 'api_key': 'synthetic-only'}}


class Upstream:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def aiter_lines(self):
        for line in ['data: ' + json.dumps({'choices': [{'finish_reason': 'stop'}]}), '', 'data: [DONE]', '']:
            yield line


class Client(Upstream):
    def __init__(self, **kwargs):
        pass

    async def get(self, *args, **kwargs):
        return Upstream()

    def stream(self, *args, **kwargs):
        return Upstream()


class BrokerCancellationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.dict(os.environ, WORKSTATION_WORKSPACE_ROOT=self.temp.name,
                        WORKSTATION_BROKER_SOCKET=str(Path(self.temp.name) / 'unused.sock'),
                        WORKSTATION_RUNTIME_IMAGE='unused-test-image'):
            spec = importlib.util.spec_from_file_location('test_workspace_broker_module', ROOT / 'deploy/workspaces/broker.py')
            self.broker = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.broker)
        self.project = self.broker.STORE.ensure_thread('synthetic-owner', 'synthetic-thread')['id']

    async def cancellation_at(self, boundary):
        broker = self.broker
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        operations = []
        original = getattr(broker, boundary)

        def delayed(*args, **kwargs):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(10):
                raise TimeoutError('Test did not release the operation')
            if boundary == 'start_container':
                operations.append('start-settled')
                Path(args[0]['workspace'], 'pending.txt').write_text('synthetic pending output')
                return 'haudi-ws-' + args[0]['id'], 12345
            return original(*args, **kwargs)

        def start(run, key):
            Path(run['workspace'], 'pending.txt').write_text('synthetic pending output')
            return 'haudi-ws-' + run['id'], 12345

        with patch.object(broker.web, 'StreamResponse', Response), \
             patch.object(broker.httpx, 'AsyncClient', Client), \
             patch.object(broker, 'start_container', start), \
             patch.object(broker, 'stop_container', lambda name: operations.append('stop')), \
             patch.object(broker, 'remove_container', lambda name: operations.append('remove')), \
             patch.object(broker, 'retain_failure_diagnostic', lambda *args: None), \
             patch.object(broker, boundary, delayed):
            task = asyncio.create_task(broker.execute(Request()))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                task.cancel()
                await asyncio.sleep(0.03)
                self.assertFalse(task.done(), 'Cleanup must join a still-running mutation')
                if boundary == 'start_container':
                    self.assertNotIn('stop', operations, 'Stop must not precede a delayed launch')
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        with broker.STORE.db() as db:
            runs = [dict(row) for row in db.execute('SELECT * FROM runs')]
        self.assertEqual(len(runs), 1)
        self.assertNotEqual(runs[0]['status'], 'running')
        if boundary == 'start_container':
            self.assertLess(operations.index('start-settled'), operations.index('stop'))
            self.assertIn('remove', operations)
            # Interrupted output remains private and recoverable; not published.
            self.assertTrue((Path(self.temp.name) / 'runs' / runs[0]['id'] / 'workspace' / 'pending.txt').exists())
            self.assertEqual(broker.STORE.nodes('synthetic-owner', self.project), [])
        await asyncio.wait_for(broker.CAPACITY.acquire(), 0.2)
        self.assertTrue(broker.CAPACITY.locked(), 'Exactly one slot must be returned')
        broker.CAPACITY.release()

    async def test_cancel_during_snapshot_joins_and_recovers_new_lease(self):
        await self.cancellation_at('begin_run')

    async def test_cancel_during_container_launch_waits_then_stops(self):
        await self.cancellation_at('start_container')

    async def test_cancel_during_publish_joins_before_cleanup(self):
        await self.cancellation_at('finish_run')

    async def test_drain_rejects_new_work_and_resume_restores_intake(self):
        broker = self.broker
        response = await broker.drain(Request())
        self.assertEqual(json.loads(response.text), {'status': 'draining', 'requests': 0})

        async def handler(request):
            self.assertEqual(len(broker.REQUESTS), 1)
            return 'accepted'

        self.assertEqual((await broker.intake(Request(), handler)).status, 503)
        await broker.resume(Request())
        self.assertEqual(await broker.intake(Request(), handler), 'accepted')
        self.assertEqual(len(broker.REQUESTS), 0)

    async def test_restart_reclaims_committed_copy_without_republishing_or_touching_other_store(self):
        broker = self.broker
        complete = broker.begin_run(broker.STORE, 'synthetic-owner', 'synthetic-thread')
        Path(complete['workspace'], 'result.txt').write_text('already committed')
        broker.finish_run(broker.STORE, 'synthetic-owner', complete['id'])
        partial = broker.begin_run(broker.STORE, 'synthetic-owner', 'synthetic-thread')
        Path(partial['workspace'], 'partial.txt').write_text('private incomplete output')
        broker.finish_run(broker.STORE, 'synthetic-owner', partial['id'], interrupted=True)
        before = broker.STORE.nodes('synthetic-owner', self.project)
        stopped, removed = [], []
        foreign = 'haudi-ws-' + 'f' * 32
        def docker(*args):
            if args[:2] == ('network', 'ls'):
                return broker.NETWORK
            if args[:2] == ('network', 'inspect'):
                return json.dumps([{'Options': {'com.docker.network.bridge.enable_icc': 'false'}}])
            if args[:2] == ('ps', '-a'):
                return '\n'.join(['haudi-ws-' + complete['id'], 'haudi-ws-' + partial['id'], foreign])
            raise AssertionError('Unexpected Docker operation')
        with patch.object(broker, 'docker', docker), \
             patch.object(broker, 'stop_container', stopped.append), \
             patch.object(broker, 'remove_container', removed.append):
            await broker.startup(None)
        expected = {'haudi-ws-' + complete['id'], 'haudi-ws-' + partial['id']}
        self.assertEqual(set(stopped), expected)
        self.assertEqual(set(removed), expected)
        self.assertFalse(Path(complete['workspace']).exists())
        self.assertTrue(Path(partial['workspace'], 'partial.txt').exists())
        self.assertEqual(broker.STORE.nodes('synthetic-owner', self.project), before)


if __name__ == '__main__':
    unittest.main()
