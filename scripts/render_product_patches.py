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
        is_new=(path in ('src/lib/utils/screen-capture.js','src/lib/components/chat/ModelSelector/ModelKeyDialog.svelte',
                         'gateway/workstation_runtime.py','gateway/workstation_catalog.json')
                or path.startswith('backend/open_webui/workstation_models/'))
        old='' if is_new else original(project,path)
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
changes['src/lib/components/chat/ModelSelector/ModelKeyDialog.svelte']=(ROOT/'overlays/open-webui/ModelKeyDialog.svelte').read_text(encoding='utf-8')
path='src/lib/components/chat/ModelSelector/Selector.svelte'
s=original('open-webui',path)
s=once(s,'<script lang="ts">','<script lang="ts">\n\timport ModelKeyDialog from "./ModelKeyDialog.svelte";\n\tlet showModelKeys = false;\n\tlet pendingModel = "";')
s=once(s,'const selectItem = (item, index: number) => {','const applyItem = (item, index: number) => {')
selection='''
    const selectItem = async (item: (typeof items)[number], index: number) => {
        if (item.value.startsWith('ws-') && !(compareEnabled && selectedValues.includes(item.value))) {
            try {
                const response = await fetch('/api/workstation/models/' + encodeURIComponent(item.value) + '/activate', {
                    method: 'POST', headers: {Authorization: `Bearer ${localStorage.token}`}
                });
                if (response.status === 428) { pendingModel = item.value; show = false; showModelKeys = true; return; }
                if (!response.ok) { const result = await response.json(); toast.error(typeof result.detail === 'string' ? result.detail : '模型验证失败'); return; }
            } catch { toast.error('模型连接失败，请重试。'); return; }
        }
        applyItem(item, index);
    };
'''
s=once(s,'</script>',selection+'\n</script>\n{#if showModelKeys}<ModelKeyDialog bind:show={showModelKeys} modelId={pendingModel} on:ready={(event) => { const item = items.find(i => i.value === event.detail); if (item) applyItem(item, items.indexOf(item)); }} />{/if}')
changes[path]=s
path='src/lib/components/chat/ModelSelector.svelte'
s=original('open-webui',path)
s=once(s,'<script lang="ts">','<script lang="ts">\n\timport ModelKeyDialog from "./ModelSelector/ModelKeyDialog.svelte";\n\tlet showModelKeys = false;')
s=once(s,'</script>','</script>\n{#if showModelKeys}<ModelKeyDialog bind:show={showModelKeys} modelId={selectedModels[0]} on:ready={(event) => { selectedModels = [event.detail]; }} />{/if}')
s+='\n<button type="button" class="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-white px-2 py-1" aria-label="管理模型 API Key" on:click={() => { showModelKeys = true; }}>模型密钥</button>\n'
changes[path]=s
for p in (ROOT/'overlays/open-webui/workstation_models').glob('*.py'):
    changes['backend/open_webui/workstation_models/'+p.name]=p.read_text(encoding='utf-8')
catalog_text=(ROOT/'configs/workstation/model-catalog.json').read_text(encoding='utf-8')
changes['backend/open_webui/workstation_models/catalog.json']=catalog_text
path='backend/open_webui/main.py'
s=original('open-webui',path)
s=once(s,"app.include_router(ollama.router, prefix='/ollama', tags=['ollama'])",
       "from open_webui.workstation_models.router import router as workstation_models_router\napp.include_router(workstation_models_router, prefix='/api/workstation', tags=['workstation'])\n\napp.include_router(ollama.router, prefix='/ollama', tags=['ollama'])")
changes[path]=s
path='backend/open_webui/utils/chat.py'
s=original('open-webui',path)
s=once(s,"        # Arena model — sub-model was already resolved by process_chat_payload.",
       "        if model_id.startswith('ws-'):\n            from open_webui.workstation_models.router import generate_chat\n            return await generate_chat(request, form_data, user)\n\n        # Arena model — sub-model was already resolved by process_chat_payload.")
changes[path]=s
emit('open-webui',changes)
path='agent/prompt_builder.py'
s=once(original('hermes-agent',path),'You are Hermes Agent, built by Nous Research. ',
       'You are the research assistant in the scientific research workstation. ')
assert s.count('You run on Hermes Agent (by Nous Research). ')==2
s=s.replace('You run on Hermes Agent (by Nous Research). ','')
agent_changes={path:s}
agent_changes['gateway/workstation_runtime.py']=(ROOT/'overlays/hermes-agent/workstation_runtime.py').read_text(encoding='utf-8')
agent_changes['gateway/workstation_catalog.json']=catalog_text
path='gateway/platforms/api_server_openai_routes.py'
s=original('hermes-agent',path)
s=once(s,'        route = self._resolve_route(model_alias)',
       '''        token = body.pop('_workstation_runtime', None)
        if token is not None:
            from gateway.workstation_runtime import decode_route
            try:
                return decode_route(token, self._expected_api_key(), gateway_session_key), {}, None
            except Exception:
                return None, {}, _error_response('Invalid workstation model authorization', 403)
        route = self._resolve_route(model_alias)''')
s=once(s,'            session_id = _derive_chat_session_id(system_prompt, first_user)',
       '''            scoped_prompt = (system_prompt or '') + ('\\nWorkstation session: ' + gateway_session_key if body.get('_workstation_runtime') and gateway_session_key else '')
            session_id = _derive_chat_session_id(scoped_prompt, first_user)''')
agent_changes[path]=s
path='gateway/platforms/api_server.py'
s=original('hermes-agent',path)
s=once(s,'            runtime_kwargs = _resolve_runtime_agent_kwargs()',
       '            runtime_kwargs = {} if route and route.get("_workstation") else _resolve_runtime_agent_kwargs()')
s=once(s,'        request_model = _clean_request_string(requested_model)\n        request_provider = _clean_request_string(requested_provider)\n        route_cfg = route if isinstance(route, dict) else {}',
       '''        from gateway.workstation_runtime import apply_runtime
        workstation_model = apply_runtime(route, runtime_kwargs)
        if workstation_model:
            return workstation_model, None, None, None
        request_model = _clean_request_string(requested_model)
        request_provider = _clean_request_string(requested_provider)
        route_cfg = route if isinstance(route, dict) else {}''')
s=once(s,'"fallback_model": None if confirmed_runtime_lock else GatewayRunner._load_fallback_model(),',
       '"fallback_model": None if confirmed_runtime_lock or (route and route.get("_workstation")) else GatewayRunner._load_fallback_model(),')
agent_changes[path]=s
emit('hermes-agent',agent_changes)
