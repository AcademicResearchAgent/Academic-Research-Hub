"""Build the pinned Open WebUI frontend with MainTask research-workstation copy."""
from collections import deque
import ast
import html
import json
from pathlib import Path
import re
import subprocess

DEPLOY=Path('/home/ubuntu/haudi-hermes')
ROOT=DEPLOY/'openwebui'
BASE='ghcr.io/open-webui/open-webui:haudi-pinned'
EXPECTED='sha256:6f1a2ca9afd03aad68621e97032e0ce6b92d14298e4d392186e7e9f1e98b9922'
REVISION='haudi-research-v4'
TAG='haudi-openwebui:0.11.3-research-v4'
copy=json.loads((DEPLOY/'research-copy.json').read_text())
work=ROOT/'research-customization'
original=work/'original'
context=work/'context-v4'

def run(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True).stdout

assert run('sudo','docker','image','inspect',BASE,'--format','{{.Id}}').strip()==EXPECTED
work.mkdir(exist_ok=True)
if not (original/'index.html').exists():
    original.mkdir(exist_ok=True)
    source=run('sudo','docker','create',BASE).strip()
    try:
        run('sudo','docker','cp',source+':/app/build/_app',str(original/'_app'))
        run('sudo','docker','cp',source+':/app/build/index.html',str(original/'index.html'))
        run('sudo','chown','-R','ubuntu:ubuntu',str(original))
    finally:
        run('sudo','docker','rm',source)

if not (original/'env.py').exists():
    source=run('sudo','docker','create',BASE).strip()
    try:
        run('sudo','docker','cp',source+':/app/backend/open_webui/env.py',str(original/'env.py'))
        run('sudo','chown','ubuntu:ubuntu',str(original/'env.py'))
    finally:
        run('sudo','docker','rm',source)

assets={p.relative_to(original).as_posix():p.read_text() for p in (original/'_app'/'immutable').rglob('*.js') if p.is_file()}
auth_path='_app/immutable/nodes/52.D9R2snhE.js'
locale_path='_app/immutable/chunks/CiT7BZod.js'

def once(text,old,new):
    assert text.count(old)==1, 'Upstream copy structure changed: '+old[:70]
    return text.replace(old,new)

def literal(value):
    return json.dumps(value,ensure_ascii=False)

auth=assets[auth_path]
auth=once(auth,'uppercase opacity-35">Open WebUI</div>',
          'uppercase opacity-35">'+html.escape(copy['app_name'])+'</div>')
auth=once(auth,'c().t("Sign in to {{WEBUI_NAME}}",{WEBUI_NAME:R()})','c().t('+literal(copy['login_title'])+')')
auth=once(auth,'c().t("Email")','c().t("本站科研账号（邮箱格式）")')
auth=once(auth,'c().t("Enter Your Email")','c().t("请输入本站科研账号")')
description=(
    '<p id="haudi-research-purpose" style="font-size:14px;line-height:1.7;margin:10px 0 0;color:#6b7280">'+html.escape(copy['tagline'])+'</p>'
    '<p id="haudi-local-account-help" style="font-size:12px;line-height:1.7;margin:8px 0 0;color:#6b7280">'+html.escape(copy['account_help'])+'</p>'
)
auth=once(auth,'class=" text-2xl font-normal"><!></div>','class=" text-2xl font-normal"><!>'+description+'</div>')
auth=once(auth,'autocomplete="email" name="email"','autocomplete="username" name="email" aria-describedby="haudi-local-account-help"')
assets[auth_path]=auth

locale=assets[locale_path]
for old,(new,count) in copy['locale_replacements'].items():
    assert locale.count(literal(old))==count, 'Unexpected locale value: '+old
    locale=locale.replace(literal(old),literal(new))
for pattern,replacement in copy['locale_term_patterns'].items():
    locale=re.sub(pattern,replacement,locale)
assets[locale_path]=locale

# Replace fixed channel and notification titles. Keep upstream copyright,
# licensing notices, URLs and technical identifiers intact.
changed={auth_path,locale_path}
capture=(DEPLOY/'screen-capture.js').read_text().split('export ',1)[1].strip()
for path,handler,on_files,toast in (
    ('_app/immutable/chunks/CS9gMiwt.js','Fs','li','ft'),
    ('_app/immutable/nodes/26.CMnsDULe.js','F','m','Qe'),
):
    text=assets[path]
    regex=re.escape(handler)+r'=async\(\)=>\{try\{const .*?catch\([A-Za-z0-9_$]+\)\{\}\}'
    matches=list(re.finditer(regex,text))
    assert len(matches)==1 and 'getDisplayMedia' in matches[0].group(), 'Capture bundle changed'
    assets[path]=text[:matches[0].start()]+handler+'=()=>('+capture+')('+on_files+','+toast+')'+text[matches[0].end():]
    changed.add(path)
for path,text in assets.items():
    if '/ Open WebUI' in text and '/nodes/' in path:
        assets[path]=text.replace('/ Open WebUI','/ '+copy['app_name'])
        changed.add(path)

# This deployment has six registered users and disabled signup. The pinned
# release LICENSE section 4(a) permits branding changes for <=50 end users.
env=(original/'env.py').read_text()
env=once(env,"if WEBUI_NAME != 'Open WebUI':\n    WEBUI_NAME += ' (Open WebUI)'\n",'')
ast.parse(env)
context.mkdir(parents=True,exist_ok=True)
(context/'env.py').write_text(env)

# Rename changed bundles and their importing parents so existing browser caches
# cannot silently keep old translations. Preserve all upstream assets in the base.
by_name={Path(path).name:path for path in assets}
assert len(by_name)==len(assets), 'Ambiguous asset filenames'
pattern=re.compile(r'[A-Za-z0-9_.-]+\.js')
parents={path:set() for path in assets}
for path,text in assets.items():
    for name in set(pattern.findall(text)) & by_name.keys():
        parents[by_name[name]].add(path)
queue=deque(changed)
while queue:
    for parent in parents[queue.popleft()]:
        if parent not in changed:
            changed.add(parent)
            queue.append(parent)
renamed={Path(path).name:Path(path).name[:-3]+'.'+REVISION+'.js' for path in changed}
def rewrite(text):
    return pattern.sub(lambda m:renamed.get(m.group(),m.group()),text)
for path in sorted(changed):
    target=context/'build'/Path(path).with_name(renamed[Path(path).name])
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(rewrite(assets[path]))
    run(str(DEPLOY/'runtime/node/bin/node'),'--check',str(target))
index=rewrite((original/'index.html').read_text())
index,n=re.subn(r'<title>[^<]*</title>','<title>'+html.escape(copy['app_name'])+'</title>',index)
assert n==1, 'Unexpected HTML title'
(context/'build'/'index.html').write_text(index)
(context/'Dockerfile').write_text('FROM '+BASE+'\nCOPY build/ /app/build/\nCOPY env.py /app/backend/open_webui/env.py\n')
(work/'changed-assets.json').write_text(json.dumps(sorted(changed),indent=2))
print('Research login, navigation and input copy prepared; refreshed assets:',len(changed),flush=True)
subprocess.run(['sudo','docker','build','--network=none','--pull=false','-t',TAG,str(context)],check=True)
(ROOT/'research-image.txt').write_text(run('sudo','docker','image','inspect',TAG,'--format','{{.Id}}').strip()+'\n')
print('Research workstation image built:',TAG,flush=True)
