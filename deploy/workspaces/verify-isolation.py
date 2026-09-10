"""Real container filesystem and peer-network checks with synthetic data only.

Uses the exact broker container launcher. No provider key is loaded and no LLM
request is made. MCP/plugin functional checks remain separate.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-release', required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    assert os.geteuid() == 0
    source = (ROOT / 'workspace-source-releases' / args.source_release).resolve()
    assert source.parent == ROOT / 'workspace-source-releases'
    test_root = ROOT / 'workspace-isolation-checks' / secrets.token_hex(12)
    test_root.mkdir(parents=True, mode=0o700)
    sys.path.insert(0, str(source / 'overlays/open-webui'))
    os.environ.update(WORKSTATION_WORKSPACE_ROOT=str(test_root), WORKSTATION_BROKER_SOCKET=str(test_root / 'unused.sock'), WORKSTATION_RUNTIME_IMAGE=args.image)
    spec = importlib.util.spec_from_file_location('isolated_broker', source / 'deploy/workspaces/broker.py')
    broker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(broker)
    from workstation_workspace.runs import begin_run, finish_run
    store = broker.STORE
    first = store.ensure_thread('isolation-a', 'isolation-thread-a')['id']
    second = store.ensure_thread('isolation-b', 'isolation-thread-b')['id']
    same_owner = store.ensure_thread('isolation-a', 'isolation-other-project')['id']
    store.create_node('isolation-a', first, 'input-a.txt', content=b'Synthetic A only')
    private = store.create_node('isolation-b', second, 'input-b.txt', content=b'Synthetic B only')
    other_project = store.create_node('isolation-a', same_owner, 'other-project.txt', content=b'Synthetic other project')
    runs, containers = [], []
    try:
        for owner, thread in [('isolation-a', 'isolation-thread-a'), ('isolation-b', 'isolation-thread-b')]:
            run = begin_run(store, owner, thread)
            runs.append((owner, run))
            containers.append('haudi-ws-' + run['id'])
            name, port = broker.start_container(run, secrets.token_urlsafe(32))
            assert name == containers[-1]
        a, b = containers
        details = [json.loads(broker.docker('inspect', name))[0] for name in containers]
        for detail, (_, run) in zip(details, runs):
            config = detail['HostConfig']
            assert config['ReadonlyRootfs'] and config['CapDrop'] == ['ALL']
            assert 'no-new-privileges:true' in config['SecurityOpt']
            assert detail['Config']['User'] == '1000:1000'
            mounts = [m for m in detail['Mounts'] if m['Type'] == 'bind']
            assert len(mounts) == 1 and mounts[0]['Destination'] == '/workspace' and mounts[0]['Source'] == run['workspace']
        peer = details[1]['NetworkSettings']['Networks'][broker.NETWORK]['IPAddress']
        subprocess.run(['docker', 'exec', '-d', '--user', '1000:1000', b, '/opt/venv/bin/python', '-m', 'http.server', '8787', '--bind', '0.0.0.0', '--directory', '/workspace'], check=True)
        with httpx.Client(timeout=2, trust_env=False) as client:
            response = None
            for _ in range(20):
                try:
                    response = client.get('http://' + peer + ':8787/input-b.txt')
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.5)
            assert response is not None and response.content == b'Synthetic B only', 'Peer fixture server must be reachable from its trusted host'
        target = str(store.blobs / private['id'] / '1')
        code = '''
import json,os,pathlib,socket
from tools.file_tools import read_file_tool
target=TARGET
def unreadable(path):
 try:pathlib.Path(path).read_bytes();return False
 except OSError:return True
root_readonly=False
try:pathlib.Path('/opt/hermes/forbidden-write').write_text('test')
except OSError:root_readonly=True
pathlib.Path('/workspace/escape-link').symlink_to(target)
pathlib.Path('/workspace/produced.txt').write_text('Synthetic output from isolated terminal')
pathlib.Path('/tmp/temporary-write').write_text('permitted')
status=pathlib.Path('/proc/self/status').read_text()
try:
 connection=socket.create_connection((PEER,8787),timeout=2);connection.close();peer_blocked=False
except OSError:peer_blocked=True
result={'uid':os.getuid(),'host_version_unreadable':unreadable(target),'same_user_other_project_unreadable':unreadable(OTHER_TARGET),'other_project_absent':not pathlib.Path('/workspace/input-b.txt').exists(),
 'symlink_cannot_escape':unreadable('/workspace/escape-link'),'root_readonly':root_readonly,'docker_socket_absent':not pathlib.Path('/var/run/docker.sock').exists(),
 'peer_blocked':peer_blocked,'capabilities_dropped':'CapEff:\\t0000000000000000' in status,'no_new_privileges':'NoNewPrivs:\\t1' in status,
 'file_tool_own_read':'Synthetic A only' in read_file_tool('/workspace/input-a.txt'),
 'file_tool_host_denied':bool(json.loads(read_file_tool(target)).get('error'))}
print('ISOLATION_RESULT='+json.dumps(result))
'''.replace('OTHER_TARGET', repr(str(store.blobs / other_project['id'] / '1'))).replace('TARGET', repr(target)).replace('PEER', repr(peer))
        output = broker.docker('exec', '--user', '1000:1000', a, '/opt/venv/bin/python', '-c', code)
        result = json.loads(next(line.split('=', 1)[1] for line in output.splitlines() if line.startswith('ISOLATION_RESULT=')))
        assert result['uid'] == 1000 and all(value for key, value in result.items() if key != 'uid'), result
        for name in containers:
            broker.stop_container(name)
        for owner, run in runs:
            collected = finish_run(store, owner, run['id'])
            if owner == 'isolation-a':
                assert 'produced.txt' in [f['name'] for f in collected['files']]
                assert 'escape-link' in collected['skipped']
        report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'checks': result,
                  'image': args.image, 'source_release': args.source_release, 'actual_broker_launcher': True,
                  'llm_called': False, 'scope': 'Container boundary, terminal, file tool, artifact collector and peer network. MCP/plugin functional calls are separate.'}
        (ROOT / 'workspace-isolation-verification.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
    finally:
        for name in containers:
            broker.remove_container(name)
        for owner, run in runs:
            finish_run(store, owner, run['id'], interrupted=True)


if __name__ == '__main__':
    main()
