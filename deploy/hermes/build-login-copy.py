"""Build a reproducible login-copy overlay for the pinned Open WebUI 0.11.3 image.

Run on the deployment server. Only public frontend assets are read from Docker.
Account data, authentication logic, branding assets and model settings are untouched.
"""
import hashlib
from pathlib import Path
import subprocess

ROOT = Path('/home/ubuntu/haudi-hermes/openwebui')
BASE = 'ghcr.io/open-webui/open-webui:haudi-pinned'
EXPECTED = 'sha256:6f1a2ca9afd03aad68621e97032e0ce6b92d14298e4d392186e7e9f1e98b9922'
TAG = 'haudi-openwebui:0.11.3-login-v1'
AUTH = '_app/immutable/nodes/52.D9R2snhE.js'
ENTRY = '_app/immutable/entry/app.DQIqq9im.js'

def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout

assert run('sudo','docker','image','inspect',BASE,'--format','{{.Id}}').strip() == EXPECTED, 'Upstream image changed; inspect the new assets before adapting this patch.'
overlay = ROOT / 'login-customization'
overlay.mkdir(exist_ok=True)

def read_asset(path):
    original=overlay/'original'/path
    if original.exists():
        return original.read_text()
    contents=run('sudo','docker','exec','haudi-openwebui','cat','/app/build/'+path)
    original.parent.mkdir(parents=True,exist_ok=True)
    original.write_text(contents)
    return contents

def replace_once(text, old, new):
    assert text.count(old) == 1, 'Unexpected frontend structure: '+old[:80]
    return text.replace(old,new)

auth = read_asset(AUTH)
auth = replace_once(auth, 'c().t("Sign in to {{WEBUI_NAME}}",{WEBUI_NAME:R()})', 'c().t("登录 Hermes 工作台")')
auth = replace_once(auth, 'c().t("Email")', 'c().t("本站账号（邮箱格式）")')
auth = replace_once(auth, 'c().t("Enter Your Email")', 'c().t("输入本站账号，而非 Open WebUI 官网账号")')
auth = replace_once(auth,
    'class=" text-2xl font-normal"><!></div>',
    'class=" text-2xl font-normal"><!><p id="haudi-local-account-help" style="font-size:14px;line-height:1.7;margin:12px 0 0;color:#6b7280">账号由本服务器管理，无需注册 Open WebUI 官网账号。邮箱仅作为本站登录名。</p></div>')
auth = replace_once(auth, 'autocomplete="email" name="email"', 'autocomplete="username" name="email" aria-describedby="haudi-local-account-help"')
new_auth = AUTH.replace('.js', '.haudi-'+hashlib.sha256(auth.encode()).hexdigest()[:10]+'.js')
# The component also names its own file for Vite preload bookkeeping.
auth = auth.replace(Path(AUTH).name, Path(new_auth).name)
entry = read_asset(ENTRY)
assert Path(AUTH).name in entry
entry = entry.replace(Path(AUTH).name,Path(new_auth).name)
new_entry = ENTRY.replace('.js','.haudi-'+hashlib.sha256(entry.encode()).hexdigest()[:10]+'.js')
index = read_asset('index.html')
assert Path(ENTRY).name in index
index = index.replace(Path(ENTRY).name,Path(new_entry).name)

for name, contents in {new_auth:auth,new_entry:entry,'index.html':index}.items():
    target=overlay/'build'/name
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(contents)
    if name.endswith('.js'):
        run('/home/ubuntu/haudi-hermes/runtime/node/bin/node','--check',str(target))
(overlay/'Dockerfile').write_text('FROM '+BASE+'\nCOPY build/ /app/build/\nLABEL haudi.login-copy="v1"\n')
subprocess.run(['sudo','docker','build','--network=none','--pull=false','-t',TAG,str(overlay)],check=True)
(ROOT/'login-image.txt').write_text(run('sudo','docker','image','inspect',TAG,'--format','{{.Id}}').strip()+'\n')
print('Login copy image built:',TAG)
