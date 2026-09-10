"""Real broker/UDS/Docker lifecycle checks with a synthetic SSE worker, no LLM.

The worker derives from the verified runtime image but replaces its entrypoint.
It writes fixed test text only. Production and preview services are untouched.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')
WORKER = '''import asyncio, json
from pathlib import Path
from aiohttp import web
async def health(request): return web.json_response({'status':'ok'})
async def run(request):
    body = await request.json()
    hold = body['messages'][0]['content'] == 'hold'
    Path('/workspace/draft.txt').write_text('synthetic partial' if hold else 'synthetic complete')
    response = web.StreamResponse(headers={'Content-Type':'text/event-stream'})
    await response.prepare(request)
    await response.write(b'event: fixture.started\\ndata: {"fixture_started":true}\\n\\n')
    if hold:
        while True:
            await asyncio.sleep(0.2)
            await response.write(b'event: fixture.waiting\\ndata: {}\\n\\n')
    await response.write(b'data: {"choices":[{"finish_reason":"stop"}]}\\n\\ndata: [DONE]\\n\\n')
    return response
app=web.Application()
app.router.add_get('/health',health)
app.router.add_post('/v1/chat/completions',run)
web.run_app(app,host='0.0.0.0',port=8642,access_log=None,handler_cancellation=True)
'''


async def verify(source, image):
    test_root = ROOT / 'workspace-lifecycle-checks' / secrets.token_hex(12)
    test_root.mkdir(parents=True, mode=0o700)
    sys.path.insert(0, str(source / 'overlays/open-webui'))
    from workstation_workspace.store import WorkspaceStore
    from workstation_workspace.runs import recover_run
    store = WorkspaceStore(test_root / 'store')
    project = store.ensure_thread('synthetic-owner', 'synthetic-thread')['id']
    original = store.create_node('synthetic-owner', project, 'draft.txt', content=b'synthetic original')
    other = store.ensure_thread('synthetic-other', 'synthetic-other-thread')['id']
    store.create_node('synthetic-other', other, 'draft.txt', content=b'synthetic other original')
    worker = test_root / 'fixture-worker.py'
    worker.write_text(WORKER)
    worker.chmod(0o444)
    dockerfile = test_root / 'Dockerfile'
    dockerfile.write_text('FROM ' + image + '\nCOPY fixture-worker.py /opt/fixture-worker.py\nENTRYPOINT ["/opt/venv/bin/python", "/opt/fixture-worker.py"]\n')
    tag = 'haudi-workspace-lifecycle:' + test_root.name
    with (test_root / 'fixture-build.log').open('wb') as build_log:
        subprocess.run(['docker', 'build', '--network=none', '-t', tag, str(test_root)], check=True,
                       stdout=build_log, stderr=subprocess.STDOUT)
    fixture_image = subprocess.check_output(['docker', 'image', 'inspect', tag, '--format', '{{.Id}}'], text=True).strip()
    socket = test_root / 'broker.sock'
    env = {**os.environ, 'PYTHONPATH': str(source / 'overlays/open-webui'),
           'WORKSTATION_WORKSPACE_ROOT': str(store.root), 'WORKSTATION_BROKER_SOCKET': str(socket),
           'WORKSTATION_RUNTIME_IMAGE': fixture_image}
    log = (test_root / 'broker.log').open('ab')
    process = None
    streams = []
    readers = {}
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'source_release': source.name,
              'broker_sha256': hashlib.sha256((source / 'deploy/workspaces/broker.py').read_bytes()).hexdigest(),
              'base_image': image, 'fixture_image': fixture_image, 'synthetic_worker': True,
              'external_model_called': False, 'production_changed': False, 'preview_changed': False}

    def rows():
        with store.db() as db:
            return [dict(row) for row in db.execute('SELECT id,status,project FROM runs ORDER BY created')]

    async def wait_for(predicate, label, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = await predicate()
            if result:
                return result
            await asyncio.sleep(0.2)
        raise AssertionError('Timed out: ' + label)

    async def health():
        try:
            async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket)), timeout=2) as client:
                response = await client.get('http://broker/health')
                return response.json() if response.status_code == 200 else None
        except httpx.HTTPError:
            return None

    async def start():
        nonlocal process
        process = subprocess.Popen([sys.executable, str(source / 'deploy/workspaces/broker.py')], env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        async def ready():
            assert process.poll() is None, 'Dedicated test broker exited'
            return await health()
        await wait_for(ready, 'test broker health')

    async def command(name):
        async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket)), timeout=5) as client:
            return await client.post('http://broker/' + name)

    async def open_run(hold=True, second=False):
        client = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket)), timeout=120)
        request = client.build_request('POST', 'http://broker/run', json={
            'owner': 'synthetic-other' if second else 'synthetic-owner',
            'thread': 'synthetic-other-thread' if second else 'synthetic-thread',
            'model_id': 'ws-synthetic', 'messages': [{'role': 'user', 'content': 'hold' if hold else 'complete'}],
            'runtime': {'model': 'synthetic', 'base_url': 'http://invalid.local', 'api_key': 'synthetic-no-provider-key'}})
        response = await client.send(request, stream=True)
        streams.append((response, client))
        return response, client

    async def wait_started(response):
        started = asyncio.Event()
        async def consume():
            try:
                async for line in response.aiter_lines():
                    if '"fixture_started": true' in line:
                        started.set()
            except httpx.HTTPError:
                pass  # Closing/killing the test peer deliberately ends the read.
        readers[id(response)] = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), 40)

    async def close_stream(pair):
        await pair[0].aclose()
        await pair[1].aclose()
        reader = readers.pop(id(pair[0]), None)
        if reader:
            await asyncio.wait_for(reader, 5)

    async def idle():
        state = await health()
        return state and state['requests'] == 0 and all(row['status'] != 'running' for row in rows())

    def assert_removed(run_id):
        names = subprocess.check_output(['docker', 'ps', '-a', '--format', '{{.Names}}'], text=True).splitlines()
        assert 'haudi-ws-' + run_id not in names, 'Execution container remains after cleanup'

    try:
        await start()
        active = await open_run()
        active[0].raise_for_status()
        await wait_started(active[0])
        first_run = rows()[-1]['id']
        queued = await open_run(second=True)
        queued[0].raise_for_status()
        assert (await health())['requests'] == 2 and len(rows()) == 1
        await close_stream(queued)
        async def one_request():
            state = await health()
            return state and state['requests'] == 1
        await wait_for(one_request, 'queued request cancellation')
        assert len(rows()) == 1
        report['queued_cancel_creates_no_lease'] = True
        assert (await command('drain')).json()['status'] == 'draining'
        rejected = await open_run()
        assert rejected[0].status_code == 503
        await close_stream(rejected)
        await close_stream(active)
        await wait_for(idle, 'active cancellation cleanup')
        assert_removed(first_run)
        assert rows()[0]['status'] == 'interrupted'
        assert store.read('synthetic-owner', original['id'])[1] == b'synthetic original'
        result = recover_run(store, 'synthetic-owner', project, first_run)
        assert len(result['files']) == 1
        assert store.read('synthetic-owner', result['files'][0]['id'])[1] == b'synthetic partial'
        assert store.read('synthetic-owner', original['id'])[1] == b'synthetic original'
        report.update(active_cancel_stops_container=True, partial_output_requires_explicit_recovery=True,
                      draining_rejects_new_work=True)
        assert (await command('resume')).json()['status'] == 'ok'
        complete = await open_run(hold=False)
        raw = await complete[0].aread()
        await close_stream(complete)
        assert b'workstation.files' in raw and b'[DONE]' in raw
        await wait_for(idle, 'slot reusable after cancellation')
        assert store.read('synthetic-owner', original['id'])[1] == b'synthetic complete'
        report['resume_and_subsequent_completion'] = True
        crashed = await open_run()
        await wait_started(crashed[0])
        crash_run = rows()[-1]['id']
        process.kill()
        await asyncio.to_thread(process.wait, 10)
        await close_stream(crashed)
        state = subprocess.check_output(['docker', 'inspect', 'haudi-ws-' + crash_run, '--format', '{{.State.Running}}'], text=True).strip()
        assert state == 'true', 'Crash fixture must leave a live worker for recovery to prove anything'
        await start()
        await wait_for(idle, 'restart recovers live orphan')
        assert_removed(crash_run)
        assert rows()[-1]['status'] == 'interrupted'
        reopened = WorkspaceStore(store.root)
        assert reopened.read('synthetic-owner', original['id'])[1] == b'synthetic complete'
        assert reopened.read('synthetic-owner', original['id'], 1)[1] == b'synthetic original'
        report.update(crash_restart_stops_live_orphan=True, restart_preserves_original_and_versions=True)
        graceful = await open_run()
        await wait_started(graceful[0])
        graceful_run = rows()[-1]['id']
        process.terminate()
        await asyncio.to_thread(process.wait, 45)
        await close_stream(graceful)
        assert_removed(graceful_run)
        assert rows()[-1]['status'] == 'interrupted'
        report['graceful_shutdown_recovers_active_run'] = True
        target = ROOT / 'workspace-lifecycle-verification.json'
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        for pair in streams:
            try:
                await close_stream(pair)
            except Exception:
                pass
        if process and process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 45)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 10)
        # Only exact synthetic leases created in this dedicated test database.
        for row in rows():
            subprocess.run(['docker', 'rm', '-f', 'haudi-ws-' + row['id']], capture_output=True)
        log.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-release', required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    assert os.geteuid() == 0
    source = (ROOT / 'workspace-source-releases' / args.source_release).resolve()
    assert source.parent == ROOT / 'workspace-source-releases'
    actual = subprocess.check_output(['docker', 'image', 'inspect', args.image, '--format', '{{.Id}}'], text=True).strip()
    assert actual == args.image and actual.startswith('sha256:'), 'Pin the verified runtime image ID'
    asyncio.run(verify(source, actual))


if __name__ == '__main__':
    main()
