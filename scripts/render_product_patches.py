"""Render source-level customizations from canonical product copy and locked upstream files."""
import difflib
import html
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
copy=json.loads((ROOT/'configs/workstation/research-copy.json').read_text(encoding='utf-8'))
lock=json.loads((ROOT/'sources.lock.json').read_text(encoding='utf-8'))

def original(project,path):
    spec=lock['sources'][project]
    return subprocess.check_output(['git','-C',str(ROOT/spec['directory']),'show',spec['commit']+':'+path]).decode('utf-8')

def once(text,old,new):
    assert text.count(old)==1,'Upstream structure changed: '+old[:90]
    return text.replace(old,new)

def emit(project,changes):
    parts=[]
    for path,new in changes.items():
        old='' if path=='src/lib/utils/screen-capture.js' else original(project,path)
        assert old!=new,path+' has no changes'
        parts.extend(difflib.unified_diff(old.splitlines(keepends=True),new.splitlines(keepends=True),fromfile='a/'+path if old else '/dev/null',tofile='b/'+path))
    target=ROOT/lock['sources'][project]['patches'][0]
    target.write_text(''.join(parts),encoding='utf-8',newline='\n')
    print(project+': rendered '+str(len(changes))+' source file changes')

changes={}
path='src/routes/auth/+page.svelte'
s=original('open-webui',path)
s=once(s,'$i18n.t(`Sign in to {{WEBUI_NAME}}`, { WEBUI_NAME: $WEBUI_NAME })',
       '$i18n.t('+json.dumps(copy['login_title'],ensure_ascii=False)+')')
s=once(s,"$i18n.t('Email')","$i18n.t('本站科研账号（邮箱格式）')")
s=once(s,"$i18n.t('Enter Your Email')","$i18n.t('请输入本站科研账号')")
s=once(s,'autocomplete="email"','autocomplete="username" aria-describedby="haudi-local-account-help"')
pattern=r'(<div class=" text-2xl font-normal">.*?\{/if\})(\s*</div>)'
addition='\n<p id="haudi-research-purpose" class="mt-2 text-sm text-gray-500">'+html.escape(copy['tagline'])+'</p>\n<p id="haudi-local-account-help" class="mt-2 text-xs text-gray-500">'+html.escape(copy['account_help'])+'</p>'
s,n=re.subn(pattern,lambda m:m[1]+addition+m[2],s,flags=re.S)
assert n==1
changes[path]=s
path='src/lib/components/OnBoarding.svelte'
s=original('open-webui',path)
s,n=re.subn(r'(?m)^(\s*)Open WebUI(\s*)$',lambda m:m[1]+copy['app_name']+m[2],s)
assert n==1
changes[path]=s
for path in ('src/routes/+layout.svelte','src/lib/components/channel/Channel.svelte'):
    changes[path]=original('open-webui',path).replace('/ Open WebUI','/ '+copy['app_name'])
path='src/app.html'
changes[path]=once(original('open-webui',path),'<title>Open WebUI</title>','<title>'+html.escape(copy['app_name'])+'</title>')
path='backend/open_webui/env.py'
changes[path]=once(original('open-webui',path),"if WEBUI_NAME != 'Open WebUI':\n    WEBUI_NAME += ' (Open WebUI)'\n",'')
path='src/lib/i18n/locales/zh-CN/translation.json'
locale=json.loads(original('open-webui',path))
for key,value in locale.items():
    if not isinstance(value,str):continue
    if value in copy['locale_replacements']:value=copy['locale_replacements'][value][0]
    for pattern,replacement in copy['locale_term_patterns'].items():value=re.sub(pattern,replacement,value)
    locale[key]=value
changes[path]=json.dumps(locale,ensure_ascii=False,indent='\t')+'\n'
capture=(ROOT/'overlays/open-webui/screen-capture.js').read_text(encoding='utf-8')
changes['src/lib/utils/screen-capture.js']=capture
for path in ('src/lib/components/chat/MessageInput.svelte','src/lib/components/channel/MessageInput.svelte'):
    s=original('open-webui',path)
    s=once(s,'<script lang="ts">','<script lang="ts">\n\timport { captureScreenshot } from "$lib/utils/screen-capture.js";')
    start=s.index('\tconst screenCaptureHandler = async () => {')
    end=s.index('\n\t};',start)+len('\n\t};')
    s=s[:start]+'\tconst screenCaptureHandler = () => captureScreenshot(inputFilesHandler, toast);'+s[end:]
    changes[path]=s
emit('open-webui',changes)
path='agent/prompt_builder.py'
s=once(original('hermes-agent',path),'You are Hermes Agent, built by Nous Research. ',
       'You are the research assistant in the scientific research workstation. ')
assert s.count('You run on Hermes Agent (by Nous Research). ')==2
s=s.replace('You run on Hermes Agent (by Nous Research). ','')
emit('hermes-agent',{path:s})
