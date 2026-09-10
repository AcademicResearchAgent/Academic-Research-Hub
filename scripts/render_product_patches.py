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
                         'src/lib/components/chat/ModelSelector/ModelAvailability.ts',
                         'src/lib/components/chat/ModelSelector/DefaultModel.js',
                         'gateway/workstation_runtime.py','gateway/workstation_catalog.json','gateway/workstation_activity.py',
                         'src/lib/components/chat/Messages/ResponseMessage/ResearchActivity.svelte')
                or path.startswith('backend/open_webui/workstation_models/')
                or path.startswith('backend/open_webui/workstation_workspace/')
                or path.startswith('src/lib/components/workspaces/'))
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
    if path == 'src/lib/components/chat/MessageInput.svelte':
        s=once(s, 'id="send-message-button"', 'id="send-message-button" aria-label="发送消息"')
    changes[path]=s
changes['src/lib/components/chat/ModelSelector/ModelKeyDialog.svelte']=(ROOT/'overlays/open-webui/ModelKeyDialog.svelte').read_text(encoding='utf-8')
changes['src/lib/components/chat/ModelSelector/ModelAvailability.ts']=(ROOT/'overlays/open-webui/ModelAvailability.ts').read_text(encoding='utf-8')
changes['src/lib/components/chat/ModelSelector/DefaultModel.js']=(ROOT/'overlays/open-webui/DefaultModel.js').read_text(encoding='utf-8')
path='src/lib/components/chat/Chat.svelte'
s=original('open-webui',path)
s=once(s,'<script lang="ts">','''<script lang="ts">
    import { findFirstAvailableModel, restoreWorkstationModels } from './ModelSelector/DefaultModel.js';
    let workstationDefaultManaged = true;
    let workstationDefaultController: AbortController | null = null;
    let workstationDefaultVersion = 0;
    let workstationDefaultNotice = '';
    onDestroy(() => workstationDefaultController?.abort());
    // Manual selection wins over an in-flight automatic choice.
    $: if (workstationDefaultController && selectedModels.some(Boolean)) {
        workstationDefaultController.abort();
        workstationDefaultController = null;
        workstationDefaultNotice = '';
    }
    async function selectWorkstationDefault() {
        workstationDefaultController?.abort();
        const controller = new AbortController();
        const defaultVersion = workstationDefaultVersion;
        const defaultOwner = $user?.id;
        const defaultHistory = history;
        workstationDefaultController = controller;
        workstationDefaultNotice = '正在检测并选择可用模型…';
        try {
            const result = await findFirstAvailableModel(getAvailableModelIds(), controller.signal);
            if (controller.signal.aborted || workstationDefaultController !== controller ||
                defaultVersion !== workstationDefaultVersion || defaultOwner !== $user?.id || defaultHistory !== history ||
                chatIdProp || history.currentId || selectedModels.some(Boolean)) return;
            selectedModels = [result.modelId || ''];
            workstationDefaultNotice = result.modelId ? '' : result.failed
                ? '模型检测失败，请手动选择模型或稍后重试。'
                : '当前没有可用模型，请在“模型密钥”中配置 API Key 或检查余额与权限。';
            if (result.modelId && !history.currentId) await setDefaults();
        } catch (error) {
            if (!controller.signal.aborted && defaultVersion === workstationDefaultVersion && defaultOwner === $user?.id)
                workstationDefaultNotice = '模型检测失败，请手动选择模型或稍后重试。';
        } finally {
            if (workstationDefaultController === controller) workstationDefaultController = null;
        }
    }''')
s=once(s,"\t\t\tchatIdProp === '' &&", "\t\t\tchatIdProp === '' && !workstationDefaultManaged &&")
s=once(s,'if (folder?.data?.model_ids && !equal(selectedModels, folder.data.model_ids)) {',
       'if (!workstationDefaultManaged && folder?.data?.model_ids && !equal(selectedModels, folder.data.model_ids)) {')
s=once(s,"\t\tconsole.log('initNewChat');", '''        const workstationDraftVersion = ++workstationDefaultVersion;
        workstationDefaultController?.abort();
        workstationDefaultController = null;
        workstationDefaultNotice = '';
        workstationDefaultManaged = !($page.url.searchParams.get('models') || $page.url.searchParams.get('model'));
        console.log('initNewChat');''')
s=once(s,"\t\t} else {\n\t\t\tif ($selectedFolder?.data?.model_ids) {", '''        } else if (workstationDefaultManaged) {
            selectedModels = [''];
            sessionStorage.removeItem('selectedModels');
        } else {
            if ($selectedFolder?.data?.model_ids) {''')
s=once(s,"\t\t// Ensure at least one model is selected\n\t\tif (selectedModels.length === 0 || (selectedModels.length === 1 && selectedModels[0] === '')) {",
       "\t\t// Explicit model links retain upstream fallback; ordinary new chats require a successful probe.\n\t\tif (!workstationDefaultManaged && (selectedModels.length === 0 || (selectedModels.length === 1 && selectedModels[0] === ''))) {")
s=once(s,'\t\t// Consume one-shot desktop event', '''        if (workstationDefaultManaged) {
            await selectWorkstationDefault();
            if (workstationDraftVersion !== workstationDefaultVersion || chatIdProp) return;
        }

        // Consume one-shot desktop event''')
s=once(s,'\tconst loadChat = async () => {', '''    const loadChat = async () => {
        workstationDefaultVersion++;
        workstationDefaultController?.abort();
        workstationDefaultController = null;
        workstationDefaultNotice = '';
        workstationDefaultManaged = false;''')
s=once(s,'\tconst initEmbeddedDraft = async () => {', '''    const initEmbeddedDraft = async () => {
        workstationDefaultVersion++;
        workstationDefaultController?.abort();
        workstationDefaultController = null;
        workstationDefaultManaged = true;
        selectedModels = [''];''')
s=once(s,'\t\tawait setDefaults();\n\t\tloading = false;\n\t\tawait tick();',
       '\t\tawait setDefaults();\n\t\tloading = false;\n\t\tawait tick();\n        await selectWorkstationDefault();')
s=once(s,'<div id="chat-pane" class="flex flex-col flex-auto z-10 w-full @container overflow-auto">', '''<div id="chat-pane" class="flex flex-col flex-auto z-10 w-full @container overflow-auto">
                        {#if workstationDefaultNotice && !history.currentId && !chatIdProp && !selectedModels.some(Boolean)}
                            <p role="status" class="px-4 py-2 text-center text-sm text-gray-500">{workstationDefaultNotice}</p>
                        {/if}''')
changes[path]=s
path='src/lib/components/chat/ModelSelector/Selector.svelte'
s=original('open-webui',path)
s=once(s,'<script lang="ts">','''<script lang="ts">
    import ModelKeyDialog from "./ModelKeyDialog.svelte";
    import { refreshAvailability, type Availability } from './ModelAvailability';
    import { onDestroy } from 'svelte';
    let showModelKeys = false;
    let pendingModel = '';
    let activatingModel = '';
    let modelAvailability: Record<string, Availability> = {};
    let availabilityController: AbortController | null = null;
    function syncAvailability(open: boolean) {
        availabilityController?.abort();
        availabilityController = null;
        if (!open) return;
        const controller = new AbortController();
        availabilityController = controller;
        refreshAvailability((states) => { modelAvailability = states; }, controller.signal).catch((error) => {
            if (controller.signal.aborted) return;
            modelAvailability = Object.fromEntries(items.filter(i => i.value.startsWith('ws-')).map(i =>
                [i.value, {state: 'error', detail: error.message}]));
        });
    }
    $: syncAvailability(show);
    onDestroy(() => availabilityController?.abort());''')
s=once(s,'<ModelItem\n','<ModelItem\n                                        availability={modelAvailability[item.value]}\n')
s=once(s,'const selectItem = (item, index: number) => {','const applyItem = (item, index: number) => {')
selection='''
    const selectItem = async (item: (typeof items)[number], index: number) => {
        if (activatingModel) return;
        if (item.value.startsWith('ws-') && !(compareEnabled && selectedValues.includes(item.value))) {
            activatingModel = item.value;
            try {
                const response = await fetch('/api/workstation/models/' + encodeURIComponent(item.value) + '/activate', {
                    method: 'POST', headers: {Authorization: `Bearer ${localStorage.token}`}
                });
                if (response.status === 428) { pendingModel = item.value; show = false; showModelKeys = true; return; }
                if (!response.ok) { const result = await response.json(); toast.error(typeof result.detail === 'string' ? result.detail : '模型验证失败'); return; }
            } catch { toast.error('模型连接失败，请重试。'); return; }
            finally { activatingModel = ''; }
        }
        applyItem(item, index);
    };
'''
s=once(s,'</script>',selection+'\n</script>\n{#if showModelKeys}<ModelKeyDialog bind:show={showModelKeys} modelId={pendingModel} on:ready={(event) => { const item = items.find(i => i.value === event.detail); if (item) applyItem(item, items.indexOf(item)); }} />{/if}')
changes[path]=s
path='src/lib/components/chat/ModelSelector/ModelItem.svelte'
s=original('open-webui',path)
s=once(s,'<script lang="ts">','''<script lang="ts">
    import { statusLabel, type Availability } from './ModelAvailability';
    export let availability: Availability | undefined = undefined;''')
s=once(s,'\t\t\t<div class="flex shrink-0 items-center gap-1.5">',
       '\t\t\t{#if !item.value.startsWith("ws-")}\n\t\t\t<div class="flex shrink-0 items-center gap-1.5">')
s=once(s,'\t\t\t</div>\n\t\t</div>\n\t</div>\n\n\t<div class="ml-auto',
       '\t\t\t</div>\n            {/if}\n\t\t</div>\n\t</div>\n\n\t<div class="ml-auto')
s=once(s,'\t\t{#if !selectionOnly && $user?.role', '''        {#if item.value.startsWith('ws-')}
            <span title={availability?.detail || '按当前账号和接入区域检测，结果短时缓存。'}
                data-model-availability={availability?.state || 'checking'}
                class="shrink-0 text-xs"
                class:text-green-600={availability?.state === 'available'}
                class:text-red-600={availability?.state === 'unavailable'}
                class:text-gray-500={availability?.state !== 'available' && availability?.state !== 'unavailable'}
            >{statusLabel(availability)}</span>
        {/if}
        {#if !selectionOnly && $user?.role''')
changes[path]=s
path='src/lib/components/chat/ModelSelector.svelte'
s=original('open-webui',path)
s=once(s,'<script lang="ts">','<script lang="ts">\n\timport ModelKeyDialog from "./ModelSelector/ModelKeyDialog.svelte";\n\tlet showModelKeys = false;')
s=once(s,'</script>','</script>\n{#if showModelKeys}<ModelKeyDialog bind:show={showModelKeys} modelId={selectedModels[0]} on:ready={(event) => { selectedModels = [event.detail]; }} />{/if}')
s+='\n<button type="button" class="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-white px-2 py-1" aria-label="管理模型 API Key" on:click={() => { showModelKeys = true; }}>模型密钥</button>\n'
changes[path]=s
for p in (ROOT/'overlays/open-webui/workstation_models').glob('*.py'):
    changes['backend/open_webui/workstation_models/'+p.name]=p.read_text(encoding='utf-8')
path='backend/open_webui/routers/files.py'
s=original('open-webui',path)
s=once(s,"@router.post('/', response_model=FileModelResponse)","@router.post('/', response_model=FileModelResponse, response_model_exclude={'path'})")
s=once(s,"@router.get('/', response_model=FileListResponse)","@router.get('/', response_model=FileListResponse, response_model_exclude={'items': {'__all__': {'path'}}})")
s=once(s,"@router.get('/search', response_model=list[FileModelResponse])","@router.get('/search', response_model=list[FileModelResponse], response_model_exclude={'__all__': {'path'}})")
s=once(s,"@router.get('/{id}', response_model=Optional[FileModel])","@router.get('/{id}', response_model=Optional[FileModel], response_model_exclude={'path'})")
s=once(s,"@router.post('/{id}/rename')","@router.post('/{id}/rename', response_model=FileModelResponse, response_model_exclude={'path'})")
changes[path]=s
for p in (ROOT/'overlays/open-webui/workstation_workspace').glob('*.py'):
    changes['backend/open_webui/workstation_workspace/'+p.name]=p.read_text(encoding='utf-8')
catalog_text=(ROOT/'configs/workstation/model-catalog.json').read_text(encoding='utf-8')
changes['backend/open_webui/workstation_models/catalog.json']=catalog_text
path='backend/open_webui/main.py'
s=original('open-webui',path)
s=once(s,"app.include_router(ollama.router, prefix='/ollama', tags=['ollama'])",
       "from open_webui.workstation_models.router import router as workstation_models_router\nfrom open_webui.workstation_workspace.router import router as workstation_workspace_router\napp.include_router(workstation_models_router, prefix='/api/workstation', tags=['workstation'])\napp.include_router(workstation_workspace_router, prefix='/api/workstation', tags=['workstation'])\n\napp.include_router(ollama.router, prefix='/ollama', tags=['ollama'])")
changes[path]=s
path='backend/open_webui/utils/chat.py'
s=original('open-webui',path)
s=once(s,"    model_id = form_data['model']", """    model_id = form_data['model']
    # Once workspace isolation is enabled, hidden legacy/direct model entries
    # must not provide a route back to the old shared execution service.
    import os
    if os.environ.get('WORKSTATION_WORKSPACE_ROOT') and (not model_id.startswith('ws-') or getattr(request.state, 'direct', False)):
        raise HTTPException(status_code=400, detail='请选择模型列表中的科研模型，旧模型入口已停用。')""")
s=once(s,"        # Arena model — sub-model was already resolved by process_chat_payload.",
       "        if model_id.startswith('ws-'):\n            from open_webui.workstation_models.router import generate_chat\n            return await generate_chat(request, form_data, user)\n\n        # Arena model — sub-model was already resolved by process_chat_payload.")
changes[path]=s
activity_path='src/lib/components/chat/Messages/ResponseMessage/ResearchActivity.svelte'
changes[activity_path]=(ROOT/'overlays/open-webui/ResearchActivity.svelte').read_text(encoding='utf-8')
path='src/lib/components/chat/Messages/ResponseMessage/StatusHistory.svelte'
s=original('open-webui',path)
s=once(s, "\timport StatusItem from './StatusHistory/StatusItem.svelte';", "\timport StatusItem from './StatusHistory/StatusItem.svelte';\n\timport ResearchActivity from './ResearchActivity.svelte';\n\texport let messageDone = false;")
s=once(s, '\texport let statusHistory = [];', "\t/** @type {import('./ResearchActivity.svelte').ResearchStatus[]} */\n\texport let statusHistory = [];")
s=once(s, '\tlet history = [];', "\t/** @type {import('./ResearchActivity.svelte').ResearchStatus[]} */\n\tlet history = [];")
s=once(s, '\tlet status = null;', "\t/** @type {import('./ResearchActivity.svelte').ResearchStatus | null | undefined} */\n\tlet status = null;")
s=once(s, '{#if history && history.length > 0}', '''<ResearchActivity {statusHistory} {messageDone} />
{#if history && history.length > 0 && !history.some((entry) => entry.action === 'workstation_tool')}''')
changes[path]=s
path='src/lib/components/chat/Messages/ResponseMessage.svelte'
s_path='src/lib/components/chat/Messages/ResponseMessage/StatusHistory/StatusItem.svelte'
status_item=original('open-webui',s_path)
status_item=once(status_item, '\texport let status = null;', "\t/** @type {import('../ResearchActivity.svelte').ResearchStatus | null | undefined} */\n\texport let status = null;")
status_item=once(status_item, '(status?.urls || status?.items).length', '(status?.urls || status?.items)?.length ?? 0')
changes[s_path]=status_item
s_path='src/lib/components/chat/Messages/ResponseMessage/WebSearchResults.svelte'
search_results=original('open-webui',s_path)
search_results=once(search_results, "\texport let status = { urls: [], query: '' };", "\timport type { ResearchStatus } from './ResearchActivity.svelte';\n\texport let status: ResearchStatus | null | undefined = { urls: [], query: '' };")
changes[s_path]=search_results
s=changes.get(path,original('open-webui',path))
s=once(s, '<StatusHistory statusHistory={message?.statusHistory} />', '<StatusHistory statusHistory={message?.statusHistory} messageDone={message?.done} />')
changes[path]=s
for p in (ROOT/'overlays/open-webui/workspaces').iterdir():
    if p.suffix in ('.svelte', '.ts'):
        changes['src/lib/components/workspaces/'+p.name]=p.read_text(encoding='utf-8')
path='src/lib/components/layout/Sidebar.svelte'
s=original('open-webui',path)
s=once(s,'<script lang="ts">','<script lang="ts">\n    import WorkspaceSidebar from "$lib/components/workspaces/WorkspaceSidebar.svelte";')
s=once(s,'\tconst newChatHandler = async () => {','\tconst newChatHandler = async () => {\n        await goto("/?draft=" + crypto.randomUUID());')
start=s.index('\t\t\t\t\t<SidebarSection\n\t\t\t\t\t\tid="sidebar-chats"')
end=s.index('\n\t\t\t\t</div>\n\n\t\t\t\t<div class="px-1 pt-1 pb-1.5 sticky',start)
s=s[:start]+'                    <WorkspaceSidebar />\n'+s[end:]
s=s.replace("$i18n.t('New Chat')", "'新建项目'")
# Native folders grouped chats without owning their files. The unified project
# tree takes over navigation; native records remain available for migration.
s=s.replace('{#if $config?.features?.enable_folders &&', '{#if false && $config?.features?.enable_folders &&')
changes[path]=s
path='src/lib/components/chat/Chat.svelte'
s=changes[path]
s=once(s,'<script lang="ts">','''<script lang="ts">
    import WorkspacePreview from '$lib/components/workspaces/WorkspacePreview.svelte';
    import { api as workspaceApi, selectedFile as workspaceSelectedFile, selectProject as workspaceSelectProject, clearSelection as workspaceClearSelection, changed as workspaceChanged } from '$lib/components/workspaces/state';
    let workspaceDraftId = '', workspaceDraftVersion = 0;
    let workspacePending: Promise<string> | null = null;
    let workspaceUploadBusy = false;
    let workspaceFilesSeen = new Set<string>();
    const workspaceFileIds = (items: any[]): string[] => items.filter(f => f.status === 'uploaded' && f.file?.id).map(f => f.file.id);
    async function workspaceEnsure(documentHistory: any, attachments: any[]): Promise<string> {
        if ($chatId) return $chatId;
        if (workspacePending) return workspacePending;
        const version = workspaceDraftVersion, owner = $user?.id;
        const target = $page.url.searchParams.get('workspace') || null;
        const payload = {project:target, file_ids:workspaceFileIds(attachments), chat:{
            history:structuredClone(documentHistory), messages:createMessagesList(documentHistory, documentHistory.currentId),
            models:selectedModels, params, timestamp:Date.now()}};
        workspacePending = (async () => {
            const result = await (await workspaceApi('/drafts/' + workspaceDraftId + '/commit', {method:'POST', body:JSON.stringify(payload)})).json();
            if (version !== workspaceDraftVersion || owner !== $user?.id) throw new DOMException('Draft changed', 'AbortError');
            chat = await getChatById(localStorage.token, result.thread);
            if (version !== workspaceDraftVersion || owner !== $user?.id) throw new DOMException('Draft changed', 'AbortError');
            await chatId.set(result.thread);
            await clearDraft();
            chatTitle.set(chat.chat.title);
            window.history.replaceState(window.history.state, '', '/c/' + result.thread);
            await workspaceSelectProject(result.project.id);
            workspaceChanged();
            return result.thread;
        })();
        try { return await workspacePending; }
        finally { if (version === workspaceDraftVersion) workspacePending = null; }
    }
    async function workspaceSyncUploads(attachments: any[]) {
        const ids = workspaceFileIds(attachments);
        if (workspaceUploadBusy || !ids.some(id => !workspaceFilesSeen.has(id))) return;
        const version = workspaceDraftVersion, owner = $user?.id;
        workspaceUploadBusy = true;
        try {
            const thread = await workspaceEnsure(history, attachments);
            const project = await (await workspaceApi('/threads/' + thread + '/workspace')).json();
            for (const id of ids) {
                if (version !== workspaceDraftVersion || owner !== $user?.id) return;
                if (!workspaceFilesSeen.has(id)) {
                    await workspaceApi('/projects/' + project.id + '/import', {method:'POST', body:JSON.stringify({file_id:id,thread})});
                    workspaceFilesSeen.add(id);
                }
            }
            workspaceChanged();
        } catch(error: any) {
            if (version === workspaceDraftVersion && error?.name !== 'AbortError') {
                ids.forEach(id => workspaceFilesSeen.add(id));
                toast.error(error instanceof Error ? error.message : '文件保存失败，请重试上传。');
            }
        } finally { if (version === workspaceDraftVersion) { workspaceUploadBusy = false; void workspaceSyncUploads(files); } }
    }
    $: if (!embedded && !loading && !$temporaryChatEnabled && files) void workspaceSyncUploads(files);''')
s=once(s,'\tconst initNewChat = async () => {','''\tconst initNewChat = async () => {
        if ($page.url.searchParams.has('draft')) await clearDraft();
        workspaceDraftId = crypto.randomUUID(); workspaceDraftVersion++;
        workspacePending = null; workspaceUploadBusy = false; workspaceFilesSeen = new Set();
        workspaceClearSelection();
        const draftProject = $page.url.searchParams.get('workspace');
        if (draftProject) void workspaceSelectProject(draftProject).catch(error => toast.error(error.message));''')
s=once(s,'\tconst submitPrompt = async (inputContent, inputFiles) => {','''\tconst submitPrompt = async (inputContent, inputFiles) => {
        const workspacePreviousHistory = structuredClone(history), workspaceSubmitVersion = workspaceDraftVersion;''')
s=once(s,'\t\thistory.currentId = userMessageId;\n\n\t\t// focus on chat input', '''\t\thistory.currentId = userMessageId;
        if (!embedded && !$temporaryChatEnabled && !$chatId) {
            try { await workspaceEnsure(history, inputFiles); }
            catch(error: any) {
                if (workspaceSubmitVersion === workspaceDraftVersion && error?.name !== 'AbortError') {
                    history = workspacePreviousHistory; prompt = inputContent; files = inputFiles;
                    toast.error(error instanceof Error ? error.message : '保存首次输入失败，请重试。');
                }
                return;
            }
        }
        // focus on chat input''')
s=once(s,"\tconst getDraftChatId = () => chatIdProp || null;", "\tconst getDraftChatId = () => chatIdProp || $chatId || null;")
s=once(s,"\t\tawait restoreChatInput(sessionStorage.getItem('chat-input'));", "\t\tawait restoreChatInput($page.url.searchParams.has('draft') ? null : sessionStorage.getItem('chat-input'));")
assert s.count("\t\tconst storageChatInput = sessionStorage.getItem(") == 2
s=s.replace("\t\tconst storageChatInput = sessionStorage.getItem(", "\t\tconst storageChatInput = $page.url.searchParams.has('draft') ? null : sessionStorage.getItem(")
s=once(s,"        const defaultHistory = history;", "        const defaultHistory = history;\n        const defaultThread = chatIdProp;")
s=once(s,'                chatIdProp || history.currentId || selectedModels.some(Boolean)) return;',
       '                defaultThread !== chatIdProp || selectedModels.some(Boolean)) return;')
s=once(s, "$models.filter((m) => !(m?.info?.meta?.hidden ?? false)).map((m) => m.id)",
       "$models.filter((m) => m.id.startsWith('ws-') && !(m?.info?.meta?.hidden ?? false)).map((m) => m.id)")
s=once(s, "\t\t\t\tselectedModels =\n\t\t\t\t\t(chatContent?.models ?? undefined) !== undefined\n\t\t\t\t\t\t? chatContent.models\n\t\t\t\t\t\t: [chatContent.models ?? ''];",
       "\t\t\t\tselectedModels = restoreWorkstationModels(chatContent.models, getAvailableModelIds());")
s=once(s,"\t\t\t\t\tselectedModels = normalizeSelectedModels(selectedModels);", "\t\t\t\t\tselectedModels = [''];")
s=once(s,"\t\t\t\tchatTitle.set(chatContent.title);", "\t\t\t\tchatTitle.set(chatContent.title);\n                if (!selectedModels.some(Boolean)) void selectWorkstationDefault();")
s=s.replace('!history.currentId && !chatIdProp && !selectedModels.some(Boolean)', '!selectedModels.some(Boolean)')
s=once(s,'\t\t\t\t{#if !embedded}\n\t\t\t\t\t<ChatControls', '\t\t\t\t{#if !embedded}<WorkspacePreview />{/if}\n\t\t\t\t{#if !embedded && !$workspaceSelectedFile}\n\t\t\t\t\t<ChatControls')
changes[path]=s
path='src/lib/components/chat/Messages/ResponseMessage.svelte'
s=changes[path]
s=once(s,'<script lang="ts">','<script lang="ts">\n    import { openWorkspaceFile } from "$lib/components/workspaces/state";')
s=once(s, 'files?: { type: string; url: string }[];', 'files?: { type: string; url: string; name?: string; size?: number; content_type?: string; workstation?: { node: string; project: string } }[];')
s=once(s, 'name={file.name}', "name={file.name ?? '文件'}")
s=once(s, 'size={file?.size}', 'size={file?.size ?? 0}')
s=once(s,"{#if file.type === 'image' || (file?.content_type ?? '').startsWith('image/')}", '''{#if file?.workstation?.node}
                                            {@const workspaceFile = file.workstation}
                                            <button class="flex items-center gap-3 rounded-xl border border-gray-200 dark:border-gray-700 px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-800" on:click={() => openWorkspaceFile(workspaceFile.node,workspaceFile.project).catch((error) => toast.error(error.message))}>
                                                <span aria-hidden="true">▤</span><span><span class="block text-sm font-medium">{file.name}</span><span class="block text-xs text-gray-500">打开文件 · {Math.ceil((file.size || 0)/1024)} KB</span></span>
                                            </button>
                                        {:else if file.type === 'image' || (file?.content_type ?? '').startsWith('image/')}''')
changes[path]=s
emit('open-webui',changes)
path='agent/prompt_builder.py'
s=once(original('hermes-agent',path),'You are Hermes Agent, built by Nous Research. ',
       'You are the research assistant in the scientific research workstation. ')
assert s.count('You run on Hermes Agent (by Nous Research). ')==2
s=s.replace('You run on Hermes Agent (by Nous Research). ','')
agent_changes={path:s}
agent_changes['gateway/workstation_runtime.py']=(ROOT/'overlays/hermes-agent/workstation_runtime.py').read_text(encoding='utf-8')
agent_changes['gateway/workstation_activity.py']=(ROOT/'overlays/hermes-agent/workstation_activity.py').read_text(encoding='utf-8')
agent_changes['gateway/workstation_catalog.json']=catalog_text
path='gateway/platforms/api_server_openai_routes.py'
s=original('hermes-agent',path)
s=once(s, '            _started_tool_call_ids: set[str] = set()', '''            _started_tool_call_ids: set[str] = set()
            from gateway.workstation_activity import ActivityTracker
            _activity = ActivityTracker()''')
begin=s.index('                from agent.display import build_tool_preview, get_tool_emoji', s.index('            def _on_tool_start'))
end=s.index('\n\n            def _on_tool_complete', begin)
s=s[:begin]+'''                _stream_q.put_threadsafe(("__tool_progress__",
                    _activity.start(tool_call_id, function_name, function_args)))'''+s[end:]
s=once(s, '''                _stream_q.put_threadsafe(("__tool_progress__", {
                    "tool": function_name, "toolCallId": tool_call_id, "status": "completed"}))''',
       '''                _stream_q.put_threadsafe(("__tool_progress__",
                    _activity.complete(tool_call_id, function_name, function_result)))''')
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
s=once(s,'                _stream_q, tool_start_callback=_on_tool_start,',
       '''                _stream_q,
                reasoning_callback=lambda text: _stream_q.put_threadsafe(("__reasoning_delta__", text)) if text else None,
                tool_start_callback=_on_tool_start,''')
s=once(s,'                    await response.write(_sse_frame(delta[1], event="hermes.tool.progress"))\n                else:',
       '''                    await response.write(_sse_frame(delta[1], event="hermes.tool.progress"))
                elif isinstance(delta, tuple) and len(delta) == 2 and delta[0] == "__reasoning_delta__":
                    await response.write(_sse_frame(_chunk({"reasoning_content": delta[1]})))
                else:''')
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
# Forward one provider-independent callback through API creation and execution.
s=once(s,'        room_execution_policy: Optional[Dict[str, Any]] = None) -> Any:',
       '        room_execution_policy: Optional[Dict[str, Any]] = None, reasoning_callback=None) -> Any:')
s=once(s,'        confirmed_runtime_lock: bool = False, bind_declared_conversation: bool = False) -> tuple:',
       '        confirmed_runtime_lock: bool = False, bind_declared_conversation: bool = False, reasoning_callback=None) -> tuple:')
s=once(s,'            "stream_delta_callback": stream_delta_callback,',
       '            "stream_delta_callback": stream_delta_callback,\n            "reasoning_callback": reasoning_callback,')
s=once(s,'                        stream_delta_callback=stream_delta_callback, tool_progress_callback=tool_progress_callback,',
       '                        stream_delta_callback=stream_delta_callback, reasoning_callback=reasoning_callback,\n                        tool_progress_callback=tool_progress_callback,')
agent_changes[path]=s
emit('hermes-agent',agent_changes)
