"""Private Unix-socket broker for one-workspace execution containers.

The UI authenticates the user and native chat before calling this socket. Only
the socket is mounted into the UI; no Docker socket enters either UI or agent.
"""
import asyncio
import base64
from contextlib import suppress
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

from aiohttp import web
from cryptography.fernet import Fernet
import httpx

from workstation_workspace.store import WorkspaceStore, WorkspaceError
from workstation_workspace.runs import begin_run, finish_run, fail_run, discard_completed_copy


ROOT = Path(os.environ['WORKSTATION_WORKSPACE_ROOT']).resolve()
SOCKET = Path(os.environ['WORKSTATION_BROKER_SOCKET'])
IMAGE = os.environ['WORKSTATION_RUNTIME_IMAGE']
NETWORK = 'haudi-workspace-isolated'
STORE = WorkspaceStore(ROOT)
CAPACITY = asyncio.Semaphore(1)
DRAINING = False
REQUESTS = set()


def docker(*args, timeout=120, env=None):
    # The broker is already a root service. A sudo wrapper would journal the
    # full command line; never put a run token into command arguments.
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout,
                            env=None if env is None else {**os.environ, **env})
    if result.returncode:
        # Docker stderr can contain host paths, env values or command arguments.
        raise RuntimeError('隔离运行器操作失败。')
    return result.stdout.strip()


def start_container(run, key):
    name = 'haudi-ws-' + run['id']
    directory = Path(run['workspace']).resolve()
    if directory != ROOT / 'runs' / run['id'] / 'workspace':
        raise RuntimeError('运行目录无效。')
    # The trusted UI owns immutable storage as root. Only this fresh execution
    # copy is writable by the container's unprivileged UID; never chown storage.
    for current, dirs, files in os.walk(directory, followlinks=False):
        os.chown(current, 1000, 1000)
        for filename in files:
            os.chown(Path(current) / filename, 1000, 1000, follow_symlinks=False)
    docker('run', '-d', '--name', name, '--label', 'haudi.workspace.managed=true',
           '--read-only', '--user', '1000:1000', '--cap-drop', 'ALL',
           '--security-opt', 'no-new-privileges:true', '--pids-limit', '192',
           '--memory', '1024m', '--memory-swap', '1536m', '--cpus', '2',
           '--network', NETWORK, '-p', '127.0.0.1::8642',
           '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m,mode=1777',
           '--tmpfs', '/state:rw,nosuid,nodev,size=192m,uid=1000,gid=1000,mode=700',
           '--mount', f'type=bind,src={directory},dst=/workspace',
           '--env', 'WORKSTATION_RUN_KEY',
           '--log-opt', 'max-size=5m', '--log-opt', 'max-file=1', IMAGE,
           env={'WORKSTATION_RUN_KEY': key})
    port = docker('inspect', name, '--format', '{{(index (index .NetworkSettings.Ports "8642/tcp") 0).HostPort}}')
    if not port.isdigit():
        raise RuntimeError('隔离运行器未获得有效监听端口。')
    return name, int(port)


def stop_container(name):
    # A successful stop/kill is followed by an authoritative stopped-state
    # check before any host process inspects the agent-controlled directory.
    result = subprocess.run(['docker', 'inspect', name, '--format', '{{.State.Running}}'], capture_output=True, text=True)
    if result.returncode:
        # Missing only if the exact managed name is absent from Docker's list.
        if name in docker('ps', '-a', '--format', '{{.Names}}').splitlines():
            raise RuntimeError('无法确认运行器状态。')
        return
    if result.stdout.strip() == 'true':
        docker('stop', '--time', '3', name)
    if docker('inspect', name, '--format', '{{.State.Running}}') != 'false':
        raise RuntimeError('运行器仍在写入。')


def remove_container(name):
    stop_container(name)
    # Exact known container only, never remove volumes/workspace data.
    result = subprocess.run(['docker', 'rm', name], capture_output=True)
    if result.returncode and name in docker('ps', '-a', '--format', '{{.Names}}').splitlines():
        raise RuntimeError('运行器尚未移除，保留执行副本。')


def retain_failure_diagnostic(name, run_id, private_values):
    """Keep bounded, redacted startup evidence outside every agent mount."""
    inspected = subprocess.run(['docker', 'inspect', name], capture_output=True, text=True, timeout=15)
    if inspected.returncode:
        return
    detail = json.loads(inspected.stdout)[0]
    sensitive = list(private_values)
    for value in detail.get('Config', {}).get('Env', []):
        variable, _, content = value.partition('=')
        if any(word in variable.upper() for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
            sensitive.append(content)
    logs = subprocess.run(['docker', 'logs', '--tail', '120', name], capture_output=True, text=True, timeout=15)
    output = json.dumps({'state': detail.get('State'), 'logs': (logs.stdout + logs.stderr)[-100000:]}, ensure_ascii=False)
    for value in sensitive:
        if value:
            output = output.replace(value, '[REDACTED]')
    directory = ROOT / 'diagnostics'
    directory.mkdir(exist_ok=True, mode=0o700)
    target = directory / (run_id + '.json')
    target.write_text(output)
    target.chmod(0o600)


def envelope(key, payload, scope):
    cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256((key + '/workstation-runtime/v1').encode()).digest()))
    return cipher.encrypt(json.dumps({**payload, 'scope': scope}).encode()).decode()


def event(name, data):
    return ('event: ' + name + '\ndata: ' + json.dumps(data, ensure_ascii=False) + '\n\n').encode()


async def health(request):
    return web.json_response({'status': 'draining' if DRAINING else 'ok', 'requests': len(REQUESTS)})


@web.middleware
async def intake(request, handler):
    if request.path != '/run':
        return await handler(request)
    if DRAINING:
        return web.json_response({'error': '科研运行器正在维护，请稍后重试。'}, status=503)
    task = asyncio.current_task()
    REQUESTS.add(task)
    try:
        return await handler(request)
    finally:
        REQUESTS.discard(task)


async def drain(request):
    global DRAINING
    DRAINING = True
    return await health(request)


async def resume(request):
    global DRAINING
    DRAINING = False
    return await health(request)


async def shutdown(app):
    global DRAINING
    DRAINING = True
    tasks = list(REQUESTS)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def execute(request):
    body = await request.json()
    # Authenticate the requested thread against the workspace database even
    # though the Unix peer is trusted; a spoofed task cannot redirect a run.
    owner, thread = body.get('owner'), body.get('thread')
    try:
        await asyncio.to_thread(STORE.project_for_thread, owner, thread)
    except WorkspaceError as error:
        return web.json_response({'error': str(error)}, status=error.status)
    runtime = body.get('runtime', {})
    if not all(isinstance(runtime.get(k), str) for k in ('model', 'base_url', 'api_key')):
        return web.json_response({'error': '缺少有效模型配置。'}, status=400)
    response = web.StreamResponse(headers={'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache'})
    await response.prepare(request)
    run = container = None
    completed = False
    capacity = False
    finish_reason = None
    run_task = start_task = finish_task = None
    try:
        waiter = asyncio.create_task(CAPACITY.acquire())
        try:
            while not waiter.done():
                done, _ = await asyncio.wait({waiter}, timeout=8)
                if not done:
                    await response.write(event('workstation.status', {'description': '正在等待可用的科研运行资源'}))
            await waiter
            capacity = True
        except BaseException:
            if waiter.done() and not waiter.cancelled() and waiter.exception() is None:
                CAPACITY.release()
            waiter.cancel()
            with suppress(asyncio.CancelledError):
                await waiter
            raise
        # Cancelling an await does not stop its worker thread. Retain and join
        # every mutating operation before cleanup, including its return value.
        run_task = asyncio.create_task(asyncio.to_thread(begin_run, STORE, owner, thread))
        run = await asyncio.shield(run_task)
        await response.write(event('workstation.status', {'description': '正在准备当前项目的独立工作区'}))
        key = secrets.token_urlsafe(40)
        container = 'haudi-ws-' + run['id']
        start_task = asyncio.create_task(asyncio.to_thread(start_container, run, key))
        _, port = await asyncio.shield(start_task)
        url = f'http://127.0.0.1:{port}'
        async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=5), trust_env=False) as client:
            for attempt in range(90):
                try:
                    ready = await client.get(url + '/health', timeout=2)
                    if ready.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if attempt % 8 == 0:
                    await response.write(event('workstation.status', {'description': '正在启动隔离的科研助手'}))
                await asyncio.sleep(1)
            else:
                raise RuntimeError('科研运行器启动超时。')
            scope = 'ws-' + hashlib.sha256(json.dumps([owner, run['project'], thread, runtime['model']]).encode()).hexdigest()[:48]
            payload = {'model': body.get('model_id'), 'messages': body.get('messages', []),
                       'stream': True, '_workstation_runtime': envelope(key, runtime, scope)}
            async with client.stream('POST', url + '/v1/chat/completions', json=payload,
                                     headers={'Authorization': 'Bearer ' + key, 'X-Hermes-Session-Key': scope}) as upstream:
                if upstream.status_code != 200:
                    raise RuntimeError('科研助手未接受当前模型请求。')
                name, data = '', []
                async for line in upstream.aiter_lines():
                    if line.startswith('event:'):
                        name = line[6:].strip()
                    elif line.startswith('data:'):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        raw = '\n'.join(data)
                        data = []
                        if raw == '[DONE]':
                            completed = True
                            break
                        parsed = json.loads(raw)
                        for choice in parsed.get('choices', []):
                            if choice.get('finish_reason'):
                                finish_reason = choice['finish_reason']
                        await response.write(event(name or 'message', parsed))
                        name = ''
        await asyncio.to_thread(stop_container, container)
        finish_task = asyncio.create_task(asyncio.to_thread(finish_run, STORE, owner, run['id'],
                                        interrupted=not completed or finish_reason in {'error', 'length', 'content_filter'}))
        result = await asyncio.shield(finish_task)
        await response.write(event('workstation.files', {'project': run['project'], **result}))
        if not completed:
            raise RuntimeError('生成连接中断，已保留可恢复文件。')
        await response.write(b'data: [DONE]\n\n')
    except (ConnectionResetError, asyncio.CancelledError):
        raise
    except Exception as error:
        print(json.dumps({'event': 'run_failed', 'run': run['id'] if run else None,
                          'category': type(error).__name__}), flush=True)
        with suppress(ConnectionResetError, RuntimeError):
            await response.write(event('message', {'error': {'message': '科研任务未完成，请重试；已保存的项目文件不会丢失。'}}))
            await response.write(b'data: [DONE]\n\n')
    finally:
        async def cleanup():
            nonlocal run
            if run_task:
                with suppress(Exception):
                    run = await run_task
            # A delayed Docker launch must settle before stop/inspect; otherwise
            # it could create a new container after cleanup reported success.
            for operation in (start_task, finish_task):
                if operation:
                    with suppress(Exception):
                        await operation
            safe_to_read = container is None
            if container:
                try:
                    await asyncio.to_thread(stop_container, container)
                    safe_to_read = True
                except Exception:
                    safe_to_read = False
            if run and safe_to_read:
                try:
                    await asyncio.to_thread(finish_run, STORE, owner, run['id'], interrupted=True)
                except Exception:
                    await asyncio.to_thread(fail_run, STORE, owner, run['id'])
            if container and safe_to_read:
                if not completed:
                    with suppress(Exception):
                        await asyncio.to_thread(retain_failure_diagnostic, container, run['id'], [runtime.get('api_key', '')])
                await asyncio.to_thread(remove_container, container)
                if run:
                    await asyncio.to_thread(discard_completed_copy, STORE, owner, run['id'])
        cleanup_task = asyncio.create_task(cleanup())
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            await cleanup_task
            raise
        finally:
            # A failed filesystem cleanup must not permanently consume the
            # execution slot. The stopped copy remains available for recovery.
            if capacity:
                CAPACITY.release()
    return response


async def startup(app):
    # Disable peer-to-peer connectivity; host service ports remain loopback only.
    networks = await asyncio.to_thread(docker, 'network', 'ls', '--format', '{{.Name}}')
    if NETWORK not in networks.splitlines():
        await asyncio.to_thread(docker, 'network', 'create', '--driver', 'bridge',
            '--opt', 'com.docker.network.bridge.enable_icc=false', NETWORK)
    detail = json.loads(await asyncio.to_thread(docker, 'network', 'inspect', NETWORK))[0]
    if detail.get('Options', {}).get('com.docker.network.bridge.enable_icc') != 'false':
        raise RuntimeError('运行网络未配置隔离。')
    # Recover exact known leases after a broker restart. Stale DB rows alone do
    # not prove a process stopped: inspect/stop Docker before collecting files.
    containers = set((await asyncio.to_thread(docker, 'ps', '-a', '--filter',
                      'label=haudi.workspace.managed=true', '--format', '{{.Names}}')).splitlines())
    with STORE.db() as db:
        known = [dict(r) for r in db.execute('SELECT r.id,r.status,p.owner FROM runs r JOIN projects p ON p.id=r.project')]
    for run in known:
        name = 'haudi-ws-' + run['id']
        if run['status'] == 'running' or name in containers:
            await asyncio.to_thread(stop_container, name)
            if run['status'] == 'running':
                try:
                    await asyncio.to_thread(finish_run, STORE, run['owner'], run['id'], interrupted=True)
                except Exception:
                    await asyncio.to_thread(fail_run, STORE, run['owner'], run['id'])
            await asyncio.to_thread(remove_container, name)
        # A crash after committing output but before removing its container or
        # copy must not leave them indefinitely. Only this store's exact run
        # IDs are handled; incomplete copies remain available for recovery.
        if run['status'] == 'completed':
            await asyncio.to_thread(discard_completed_copy, STORE, run['owner'], run['id'])


if __name__ == '__main__':
    SOCKET.parent.mkdir(parents=True, exist_ok=True)
    app = web.Application(client_max_size=20 * 1024 * 1024, middlewares=[intake])
    app.router.add_get('/health', health)
    app.router.add_post('/run', execute)
    app.router.add_post('/drain', drain)
    app.router.add_post('/resume', resume)
    app.on_startup.append(startup)
    app.on_shutdown.append(shutdown)
    # Private parent directory is shared only with the trusted UI backend.
    web.run_app(app, path=str(SOCKET), access_log=None, handler_cancellation=True)
