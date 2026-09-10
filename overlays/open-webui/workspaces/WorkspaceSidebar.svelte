<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { goto } from '$app/navigation';
    import { chatId, user } from '$lib/stores';
    import { toast } from 'svelte-sonner';
    import { projects, activeProject, nodes, selectedFile, workspaceRefresh, api, changed,
        resetWorkspace, refreshProjects, refreshFiles, selectThread, selectProject, downloadFile, clearSelection } from './state';
    import type { WorkspaceFile, Project } from './state';

    let knownUser = '', knownThread = '', ready = false, busy = false, query = '';
    let modes: Record<string, string> = {};
    let expanded = new Set<string>();
    let error = '', uploadStatus = '', uploadInput: HTMLInputElement, uploadProject = '', uploadParent = '';
    let dialog: null | {kind: string; project: string; node?: WorkspaceFile; thread?: string} = null;
    let name = '', parent = '', trash: Project[] | null = null;
    let recovery: null | {project: string; runs: {id: string; thread: string; status: string; updated: number}[]} = null;
    let recoveryVersion = 0;
    $: if (($user?.id ?? '') !== knownUser) {
        knownUser = $user?.id ?? ''; knownThread = ''; resetWorkspace(knownUser);
        modes = {}; expanded = new Set(); dialog = null; trash = null; recovery = null; recoveryVersion++;
        error = ''; uploadStatus = ''; busy = false; query = ''; name = ''; parent = '';
        uploadProject = ''; uploadParent = '';
        if (ready && knownUser) refresh();
    }
    $: if (ready && $chatId !== knownThread) {
        knownThread = $chatId;
        if ($chatId) selectThread($chatId).catch(showError);
    }
    $: if (ready && $workspaceRefresh) refresh();
    $: tree = flatten($nodes, expanded, '', 0);
    function flatten(entries: WorkspaceFile[], opened: Set<string>, id: string, depth: number): {file: WorkspaceFile; depth: number}[] {
        return entries.filter(n => n.parent === id).sort((a,b) => a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name))
            .flatMap(file => [{file, depth}, ...(file.kind === 'directory' && opened.has(file.id) ? flatten(entries, opened, file.id, depth + 1) : [])]);
    }
    function showError(e: any) { if (e?.name !== 'AbortError') { error = e.message || '操作失败，请重试。'; } }
    function closeMenus() {
        for (const menu of document.querySelectorAll('[aria-label="项目列表"] details[open]'))
            if (menu instanceof HTMLDetailsElement) menu.open = false;
    }
    async function refresh() {
        try { await refreshProjects(); await refreshFiles(); error = ''; } catch(e) { showError(e); }
    }
    onMount(() => {
        ready = true; refresh();
        const interval = setInterval(() => { if (!document.hidden) refresh(); }, 5000);
        return () => clearInterval(interval);
    });
    async function create(project?: string) {
        closeMenus();
        try {
            clearSelection();
            if (project) await selectProject(project);
            await goto('/?draft=' + crypto.randomUUID() + (project ? '&workspace=' + encodeURIComponent(project) : ''));
        } catch(e) { showError(e); }
    }
    async function open(project: Project) {
        closeMenus();
        try {
            await selectProject(project.id);
            const thread = project.threads.find(t => t.id === project.last_thread) || project.threads[0];
            if (thread) await goto('/c/' + thread.id);
            else await create(project.id);
        } catch(e) { showError(e); }
    }
    function configure(kind: string, project: string, node?: WorkspaceFile, thread?: string) {
        closeMenus();
        dialog = {kind, project, node, thread};
        error = '';
        name = node?.name ?? (kind === 'rename-project' ? $projects.find(p=>p.id===project)?.title ?? '' : kind === 'rename-thread' ? $projects.find(p=>p.id===project)?.threads.find(t=>t.id===thread)?.title ?? '' : '');
        parent = node?.parent ?? '';
    }
    async function confirm() {
        if (!dialog) return;
        const d = dialog; busy = true;
        try {
            if (d.kind === 'rename-project') await api('/projects/' + d.project, {method:'PATCH',body:JSON.stringify({title:name})});
            else if (d.kind === 'delete-project') {
                await api('/projects/' + d.project, {method:'DELETE'});
                if ($activeProject === d.project) { selectedFile.set(null); activeProject.set(''); nodes.set([]); await goto('/'); }
            } else if (d.kind === 'delete-thread') await api('/threads/' + d.thread, {method:'DELETE'});
            else if (d.kind === 'rename-thread') await api('/threads/' + d.thread, {method:'PATCH',body:JSON.stringify({title:name})});
            else if (d.kind === 'delete-file') await api('/files/' + d.node!.id, {method:'DELETE'});
            else if (d.kind === 'move') await api('/files/' + d.node!.id, {method:'PATCH',body:JSON.stringify({name,parent})});
            else await api('/projects/' + d.project + '/files', {method:'POST',body:JSON.stringify({name,parent,directory:d.kind==='directory',content:''})});
            dialog = null; changed(); await refresh();
            if (d.kind === 'delete-thread' && $chatId === d.thread) {
                const project = $projects.find(p=>p.id===d.project);
                if (project) await open(project);
            }
        } catch(e) { showError(e); } finally { busy = false; }
    }
    function chooseUpload(project: string) { uploadProject = project; uploadParent = ''; uploadInput.click(); }
    async function upload(event: Event) {
        const files = [...((event.target as HTMLInputElement).files ?? [])];
        const project = uploadProject, destination = uploadParent, owner = knownUser;
        busy = true;
        try {
            for (const file of files) {
                if (owner !== knownUser) return;
                uploadStatus = '正在上传：' + file.name;
                const form = new FormData(); form.append('file',file); form.append('parent',destination);
                await api('/projects/' + project + '/upload',{method:'POST',body:form});
            }
            if (owner !== knownUser) return;
            error = ''; changed(); await refreshFiles(project);
        } catch(e) { if (owner === knownUser) showError(e); }
        finally { if (owner === knownUser) { busy=false; uploadStatus=''; uploadInput.value=''; } }
    }
    async function extract(file: WorkspaceFile) {
        closeMenus();
        try { await api('/files/'+file.id+'/extract',{method:'POST'}); changed(); }
        catch(e) { showError(e); }
    }
    async function openRecovery(project: string) {
        closeMenus();
        const version = ++recoveryVersion, owner = knownUser;
        error = '';
        try {
            const runs = await (await api('/projects/' + project + '/recoverable-runs')).json();
            if (version === recoveryVersion && owner === knownUser) recovery = {project, runs};
        } catch(e) { if (version === recoveryVersion && owner === knownUser) showError(e); }
    }
    async function recoverFiles(run: string) {
        if (!recovery || busy) return;
        const project = recovery.project, owner = knownUser, version = recoveryVersion;
        busy = true; error = '';
        try {
            const result = await (await api('/projects/' + project + '/recoverable-runs/' + run + '/recover', {method:'POST'})).json();
            if (version !== recoveryVersion || owner !== knownUser) return;
            recovery = {project, runs: recovery.runs.filter(item=>item.id!==run)};
            toast.success(result.files.length ? '已导入独立的未完成文件目录，请检查内容后使用。' : '没有可恢复的新内容，原项目文件保持完整。');
            changed();
        } catch(e) { if (version === recoveryVersion && owner === knownUser) showError(e); }
        finally { if (owner === knownUser) busy = false; }
    }
</script>

<section class="px-2 py-2 text-sm" aria-label="项目列表">
    <div class="flex items-center justify-between mb-2"><h2 class="font-medium text-gray-700 dark:text-gray-200">项目列表</h2>
        <button class="rounded-lg px-2 py-1 hover:bg-gray-200 dark:hover:bg-gray-800" disabled={busy} on:click={()=>create()} aria-label="新建项目">＋ 新建</button></div>
    <input class="w-full rounded-lg bg-transparent border border-gray-200 dark:border-gray-800 px-2 py-1.5 mb-2" bind:value={query} placeholder="查找项目" aria-label="查找项目" />
    <input class="hidden" type="file" multiple bind:this={uploadInput} on:change={upload} />
    {#if uploadStatus}<p role="status" class="text-xs text-blue-700 dark:text-blue-300 p-2 break-words">{uploadStatus}</p>{/if}
    {#if error}<p role="status" class="text-xs text-amber-700 dark:text-amber-300 p-2 break-words">{error}<button class="ml-2 underline" on:click={refresh}>重试</button></p>{/if}
    {#each $projects.filter(p=>p.title.toLowerCase().includes(query.toLowerCase())) as project (project.id)}
        <div class="mb-1 rounded-xl border {$activeProject===project.id ? 'border-blue-200 dark:border-blue-900 bg-blue-50/40 dark:bg-blue-950/15' : 'border-transparent'}">
            <div class="flex items-center px-1 py-1">
                <button class="flex-1 truncate text-left rounded-lg px-2 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" title={project.title} on:click={()=>open(project)}>{project.title}</button>
                <details class="relative"><summary class="cursor-pointer list-none px-2" aria-label={'项目操作：'+project.title}>⋯</summary>
                    <div class="absolute right-0 top-6 z-30 bg-white dark:bg-gray-850 border dark:border-gray-700 rounded-lg shadow-lg p-1 w-32">
                        <button class="block w-full text-left p-2" on:click={()=>configure('rename-project',project.id)}>重命名</button>
                        {#if project.threads.length === 1}
                            <button class="block w-full text-left p-2" on:click={()=>configure('delete-thread',project.id,undefined,project.threads[0].id)}>删除对话</button>
                        {/if}
                        <button class="block w-full text-left p-2" on:click={()=>openRecovery(project.id)}>未完成文件</button>
                        <button class="block w-full text-left p-2 text-red-600" on:click={()=>configure('delete-project',project.id)}>移入回收站</button>
                    </div>
                </details>
            </div>
            {#if $activeProject===project.id}
                <div class="flex mx-2 mb-2 rounded-lg bg-gray-100 dark:bg-gray-900 p-0.5" role="tablist" aria-label="项目视图">
                    {#each [['files','资源管理器'],['threads','对话列表']] as tab}
                        <button role="tab" aria-selected={(modes[project.id]??'threads')===tab[0]} class="flex-1 rounded-md px-1 py-1 text-xs {(modes[project.id]??'threads')===tab[0]?'bg-white dark:bg-gray-700 shadow-sm':''}" on:click={()=>{modes={...modes,[project.id]:tab[0]};}}>{tab[1]}</button>
                    {/each}
                </div>
                {#if modes[project.id]==='files'}
                    <div class="flex gap-2 px-3 pb-2 text-xs text-blue-700 dark:text-blue-300">
                        <button disabled={busy} on:click={()=>chooseUpload(project.id)}>上传</button>
                        <button on:click={()=>configure('file',project.id)}>新建文件</button>
                        <button on:click={()=>configure('directory',project.id)}>新建目录</button>
                    </div>
                    {#each tree as {file,depth} (file.id)}
                        <div class="flex items-center group pr-1" style:padding-left={8+depth*12+'px'}>
                            <button class="flex-1 truncate text-left px-1 py-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-xs" title={file.path}
                                on:click={()=>{if(file.kind==='directory'){expanded.has(file.id)?expanded.delete(file.id):expanded.add(file.id);expanded=new Set(expanded);}else selectedFile.set(file);}}>
                                <span class="text-gray-400 mr-1">{file.kind==='directory'?(expanded.has(file.id)?'▾':'▸'):'▤'}</span>{file.name}</button>
                            <details class="relative"><summary class="cursor-pointer list-none px-1 text-gray-500" aria-label={'文件操作：'+file.name}>⋯</summary>
                                <div class="absolute right-0 top-5 z-30 bg-white dark:bg-gray-850 border dark:border-gray-700 rounded-lg shadow-lg p-1 w-36 text-xs">
                                    <button class="block w-full text-left p-2" on:click={()=>configure('move',project.id,file)}>重命名／移动</button>
                                    {#if file.kind==='file'}<button class="block w-full text-left p-2" on:click={()=>{closeMenus();downloadFile(file).catch(showError);}}>下载</button>{/if}
                                    {#if file.name.toLowerCase().endsWith('.zip')}<button class="block w-full text-left p-2" on:click={()=>extract(file)}>解压到新目录</button>{/if}
                                    <button class="block w-full text-left p-2 text-red-600" on:click={()=>configure('delete-file',project.id,file)}>删除</button>
                                </div>
                            </details>
                        </div>
                    {/each}
                {:else}
                    {#each (project.threads.length > 1 ? project.threads : []) as thread (thread.id)}
                        <div class="flex items-center px-2"><a href={'/c/'+thread.id} class="flex-1 truncate rounded-lg p-2 text-xs {$chatId===thread.id?'text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950/30':''}">{thread.title}</a>
                            <details class="relative"><summary class="list-none cursor-pointer px-1" aria-label={'对话操作：'+thread.title}>⋯</summary><div class="absolute right-0 top-5 z-30 bg-white dark:bg-gray-850 rounded-lg shadow border dark:border-gray-700 p-1 w-28 text-xs">
                                <button class="block p-2" on:click={()=>configure('rename-thread',project.id,undefined,thread.id)}>重命名</button>
                                <button class="block p-2 text-red-600" on:click={()=>configure('delete-thread',project.id,undefined,thread.id)}>删除对话</button>
                            </div></details>
                        </div>
                    {/each}
                    <button class="px-4 py-2 text-xs text-blue-700 dark:text-blue-300" disabled={busy} on:click={()=>create(project.id)}>＋ 新增对话</button>
                {/if}
            {/if}
        </div>
    {/each}
    <button class="mt-3 px-2 text-xs text-gray-500" on:click={async()=>{try{trash=await(await api('/projects-trash')).json();}catch(e){showError(e);}}}>项目回收站</button>
</section>

{#if dialog || trash || recovery}
    <div class="fixed inset-0 z-[100] bg-black/30 flex items-center justify-center p-4">
        <section role="dialog" aria-modal="true" aria-label="项目文件操作" class="w-full max-w-md rounded-2xl bg-white dark:bg-gray-900 p-5 shadow-xl">
            {#if recovery}
                <h3 class="font-medium mb-3">恢复未完成文件</h3>
                <p class="text-sm text-gray-600 dark:text-gray-300 mb-3">中断的输出可能不完整。恢复后会导入独立目录，供你检查和继续编辑，已有文件不会被覆盖。</p>
                {#each recovery.runs as run (run.id)}
                    <div class="flex justify-between gap-3 py-2 text-sm"><span>{new Date(run.updated / 1000000).toLocaleString()} · {run.status==='failed'?'失败':'已中断'}</span><button class="shrink-0 text-blue-600" disabled={busy} on:click={()=>recoverFiles(run.id)}>恢复文件</button></div>
                {/each}
                {#if !recovery.runs.length}<p class="text-sm text-gray-500">没有待恢复的运行。</p>{/if}
                {#if error}<p role="alert" class="text-sm text-red-600 mt-2">{error}</p>{/if}
                <button class="mt-4" on:click={()=>{recovery=null;recoveryVersion++;}}>关闭</button>
            {:else if trash}
                <h3 class="font-medium mb-3">项目回收站</h3>
                {#each trash as project}<div class="flex justify-between py-2"><span>{project.title}</span><button class="text-blue-600" on:click={async()=>{try{await api('/projects/'+project.id+'/restore',{method:'POST'});trash=trash?.filter(p=>p.id!==project.id)??[];changed();}catch(e){showError(e);}}}>恢复</button></div>{/each}
                {#if !trash.length}<p class="text-gray-500 text-sm">没有已删除项目。</p>{/if}
                <button class="mt-4" on:click={()=>trash=null}>关闭</button>
            {:else if dialog}
                <h3 class="font-medium mb-3">{dialog.kind.startsWith('delete')?'确认删除':'名称与位置'}</h3>
                {#if dialog.kind.startsWith('delete')}
                    <p class="text-sm text-gray-600 dark:text-gray-300">{dialog.kind==='delete-project'?'项目及其文件将从列表隐藏，可从项目回收站恢复。':dialog.kind==='delete-thread'?'删除此交流线程，项目文件仍然保留。':'删除此文件或目录及其子文件。已有版本仍由服务端保留。'}</p>
                {:else}
                    <label class="block text-sm">名称<input class="block w-full rounded-lg border dark:border-gray-700 bg-transparent p-2 mt-1" bind:value={name} /></label>
                    {#if ['move','file','directory'].includes(dialog.kind)}
                        <label class="block text-sm mt-3">位置<select class="block w-full rounded-lg border dark:border-gray-700 bg-white dark:bg-gray-900 p-2 mt-1" bind:value={parent}><option value="">工作区根目录</option>{#each $nodes.filter(n=>n.kind==='directory'&&n.id!==dialog?.node?.id) as n}<option value={n.id}>{n.path}</option>{/each}</select></label>
                    {/if}
                {/if}
                {#if error}<p role="alert" class="text-sm text-red-600 mt-2">{error}</p>{/if}
                <div class="mt-5 flex justify-end gap-3"><button on:click={()=>dialog=null}>取消</button><button class="bg-blue-600 text-white rounded-lg px-4 py-2" disabled={busy} on:click={confirm}>确认</button></div>
            {/if}
        </section>
    </div>
{/if}
