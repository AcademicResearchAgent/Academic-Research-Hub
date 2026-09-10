"""Verify the deployed preview cannot route legacy/direct requests outside broker."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')


def main():
    fixture = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    with httpx.Client(base_url='http://127.0.0.1:9120', timeout=30, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: fixture[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        client.get('/api/models').raise_for_status()
        response = client.post('/api/chat/completions', json={'model': 'hermes-agent', 'stream': False,
                               'chat_id': fixture['thread'], 'messages': [{'role': 'user', 'content': 'Synthetic routing boundary check'}]})
        assert response.status_code == 400 and '旧模型入口已停用' in response.text, 'Legacy route not rejected by the workspace gate'
    # Exercise the entire deployed routing function with direct=True. Compile
    # its original AST so importing the whole WebUI cannot start DB migrations.
    code = '''import ast,asyncio,__future__,logging
from pathlib import Path
from types import SimpleNamespace
from fastapi import HTTPException
source=Path('/app/backend/open_webui/utils/chat.py').read_text()
function=next(n for n in ast.parse(source).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='generate_chat_completion')
module=ast.Module(body=[function],type_ignores=[])
namespace={'log':logging.getLogger('gate-check'),'BYPASS_MODEL_ACCESS_CONTROL':False,'HTTPException':HTTPException}
exec(compile(module,'deployed-chat-routing','exec',flags=__future__.annotations.compiler_flag),namespace)
model={'id':'ws-deepseek-v4-pro'}
request=SimpleNamespace(state=SimpleNamespace(direct=True,model=model),app=SimpleNamespace(state=SimpleNamespace(MODELS={model['id']:model})))
try:
 asyncio.run(namespace['generate_chat_completion'](request,{'model':model['id'],'messages':[]},SimpleNamespace(id='synthetic',role='user')))
 raise AssertionError('Direct route was not blocked')
except HTTPException as error:
 assert error.status_code==400 and '旧模型入口已停用' in error.detail
print('DIRECT_ROUTE_REJECTED')
'''
    result = subprocess.run(['sudo', 'docker', 'exec', '-i', 'haudi-openwebui-workspace-preview', 'python', '-'], input=code, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0 and 'DIRECT_ROUTE_REJECTED' in result.stdout, result.stderr[-1000:]
    image = subprocess.check_output(['sudo', 'docker', 'inspect', 'haudi-openwebui-workspace-preview', '--format', '{{.Image}}'], text=True).strip()
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'image': image,
              'legacy_model_rejected_over_authenticated_http': True,
              'direct_connection_rejected_by_deployed_function': True,
              'llm_called': False, 'scope': 'Legacy chat endpoint and direct routing function. Production legacy service shutdown remains part of cutover.'}
    (ROOT / 'workspace-execution-gate-verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
