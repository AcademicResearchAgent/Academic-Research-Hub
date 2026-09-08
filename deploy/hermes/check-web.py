"""Verify the deployed dashboard through the local SSH tunnel."""
import json
import re
import urllib.request

base='http://127.0.0.1:9119'
def get(path,headers=None):
    with urllib.request.urlopen(urllib.request.Request(base+path,headers=headers or {}),timeout=30) as response:
        assert response.status==200
        return response.read().decode()

html=get('/')
assert 'id="root"' in html
assert 'id="root"' in get('/chat')
token=re.search(r'__HERMES_SESSION_TOKEN__\s*=\s*["\']([^"\']+)',html)
assert token, 'Missing dashboard session token'
headers={'X-Hermes-Session-Token':token.group(1)}
status=json.loads(get('/api/status'))
print('Dashboard root and chat routes: OK')
print('Health:',get('/api/health'))
assets=re.findall(r'(?:src|href)="(/assets/[^"?]+)"',html)
for asset in assets: get(asset)
print('HTML asset links:',len(assets),'OK')
print('Sessions API: OK' if json.loads(get('/api/sessions',headers)) is not None else 'No response')
print('Dashboard status:', json.dumps({k:v for k,v in status.items() if k in ('version','auth_required','active_sessions','gateway_running')}))
