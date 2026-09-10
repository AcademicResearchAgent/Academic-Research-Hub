<script lang="ts">
    import { onDestroy } from 'svelte';
    import DOMPurify from 'dompurify';
    import { marked } from 'marked';
    import hljs from 'highlight.js/lib/common';
    import PDFViewer from '$lib/components/common/PDFViewer.svelte';
    import ResizableSidePanel from '$lib/components/common/ResizableSidePanel.svelte';
    import { user } from '$lib/stores';
    import { selectedFile, activeProject, nodes, drafts, api, downloadFile, changed, openWorkspaceFile } from './state';
    import type { WorkspaceFile } from './state';

    let width=480, screenWidth=1200, sequence=0, loadedId='', loadedName='', version=0, text='', original='';
    let saving = new Set<string>();
    let loading=false, error='', mode='preview', url='', pdf: ArrayBuffer|null=null, zoom=1;
    let editable=false, versions: {revision:number;size:number;created:number}[]=[], showVersions=false;
    let markdown='', highlight='', kind='', imageUrls:string[]=[], markdownVersion=0;
    $: dirty = text !== original;
    $: if ($selectedFile && ($selectedFile.id !== loadedId || $selectedFile.name !== loadedName)) load($selectedFile);
    $: if (!$selectedFile && loadedId) { sequence++; release(); loadedId=''; text=''; original=''; error=''; }
    $: if (editable && mode==='preview' && kind==='markdown' && $selectedFile) renderMarkdown(text, $selectedFile, $nodes);
    $: if (editable && kind==='code') highlight=hljs.highlightAuto(text.slice(0,200000)).value;
    $: csvRows = kind==='csv' ? parseCsv(text) : [];

    function release() { if(url)URL.revokeObjectURL(url); url=''; imageUrls.forEach(u=>URL.revokeObjectURL(u));imageUrls=[];pdf=null; }
    function imageFailed(event: Event) {
        // A late error from a previously selected blob must not replace the
        // currently opened file's preview or draft.
        if ((event.currentTarget as HTMLImageElement).currentSrc !== url) return;
        error='图片无法解析，请下载原文件检查格式。'; kind='binary'; release();
    }
    onDestroy(()=>{sequence++;release();});
    async function load(file: WorkspaceFile) {
        const id=++sequence; loadedId=file.id; loadedName=file.name; loading=true; error=''; release();
        kind=''; editable=false; text=''; original=''; version=file.version; zoom=1; showVersions=false;
        try {
            const ext=file.name.split('.').pop()?.toLowerCase()??'';
            kind=['md','markdown'].includes(ext)?'markdown':ext==='csv'?'csv':ext==='pdf'?'pdf':file.mime?.startsWith('image/')&&ext!=='svg'?'image':
                ['txt','tex','bib','py','js','ts','json','yaml','yml','toml','ini','sh','css','html','xml','svg','r','c','cpp','h','rs','go','sql','log','cls','sty','bst'].includes(ext)||file.mime?.startsWith('text/')?'code':'binary';
            if (file.size>20*1024*1024 || (['markdown','csv','code'].includes(kind)&&file.size>2*1024*1024)) {
                kind='binary'; error='文件较大，请下载后使用本地工具查看。'; return;
            }
            if(kind==='binary')return;
            const response=await api('/files/'+file.id+'/content');
            const blob=await response.blob();
            if(id!==sequence || $selectedFile?.id!==file.id || $activeProject!==file.project)return;
            version=Number(response.headers.get('X-File-Version')??file.version);
            if(kind==='pdf') { const data=await blob.arrayBuffer(); if(id!==sequence)return; pdf=data; }
            else if(kind==='image')url=URL.createObjectURL(blob);
            else {
                const data=await blob.text();if(id!==sequence)return;original=data;
                const draft=drafts.get(file.id);text=draft?.content??original;
                if(draft)version=draft.version;
                editable=true;mode=kind==='code'?'source':'preview';
            }
        } catch(e:any) { if(id===sequence && e.name!=='AbortError')error=e.message; }
        finally { if(id===sequence)loading=false; }
    }
    async function renderMarkdown(content: string, file: WorkspaceFile, entries: WorkspaceFile[]) {
        const id=sequence;
        const renderVersion=++markdownVersion;
        const safe=DOMPurify.sanitize(marked.parse(content,{async:false}) as string,{
            FORBID_TAGS:['style','script','iframe','object','embed','form','input','svg','math'],FORBID_ATTR:['style','srcset']});
        const doc=new DOMParser().parseFromString(safe,'text/html');
        const locate=(href:string)=>{
            try {
                const target=new URL(href,'https://workspace.invalid/'+file.path);
                if(target.origin!=='https://workspace.invalid')return null;
                return entries.find(n=>n.project===file.project && n.path===decodeURIComponent(target.pathname.slice(1)));
            }catch{return null;}
        };
        const created:string[]=[];
        for(const image of doc.querySelectorAll('img')) {
            const match=locate(image.getAttribute('src')??'');image.removeAttribute('src');
            if(match?.mime.startsWith('image/')&&match.size<10*1024*1024) {
                try{const b=await(await api('/files/'+match.id+'/content')).blob();const u=URL.createObjectURL(b);created.push(u);image.src=u;}catch{image.alt+='（图片不可用）';}
            }else image.alt+='（请在资源管理器查看图片）';
        }
        for(const anchor of doc.querySelectorAll('a')) {
            const match=locate(anchor.getAttribute('href')??'');
            if(match){anchor.href='#';anchor.dataset.workspaceFile=match.id;}
            else {anchor.target='_blank';anchor.rel='noopener noreferrer';}
        }
        if(id!==sequence || renderVersion!==markdownVersion){created.forEach(u=>URL.revokeObjectURL(u));return;}
        imageUrls.forEach(u=>URL.revokeObjectURL(u));imageUrls=created;markdown=doc.body.innerHTML;
    }
    function follow(event: MouseEvent) {
        const anchor=(event.target as HTMLElement).closest?.('a[data-workspace-file]') as HTMLElement;
        if(anchor){event.preventDefault();openWorkspaceFile(anchor.dataset.workspaceFile!).catch((e)=>error=e.message);}
    }
    function editText(content: string) {
        text=content;
        // Only user input creates a draft. Reactive load/reset assignments can
        // observe the preceding file's dirty flag and must never write drafts.
        if(!loadedId || !editable)return;
        if(text===original && !saving.has(loadedId))drafts.delete(loadedId);
        else drafts.set(loadedId,{content:text,version});
    }
    async function save() {
        const file=$selectedFile;if(!file)return;
        if(saving.has(file.id))return;
        const content=text, revision=version, account=$user?.id, requestSequence=sequence;
        saving=new Set([...saving,file.id]);
        try{
            const saved=await(await api('/files/'+file.id+'/content',{method:'PUT',body:JSON.stringify({content,version:revision})})).json();
            if(account!==$user?.id)return;
            const draft=drafts.get(file.id);
            if(draft?.version===revision){
                if(draft.content===content)drafts.delete(file.id);
                else drafts.set(file.id,{content:draft.content,version:saved.version});
            }
            if(sequence===requestSequence && $selectedFile?.id===file.id){original=content;version=saved.version;selectedFile.set({...$selectedFile,...saved});error='';}
            changed();
        }catch(e:any){if(e.name!=='AbortError' && sequence===requestSequence && account===$user?.id)error=e.message;}
        finally{saving.delete(file.id);saving=new Set(saving);}
    }
    async function history() {
        const file=$selectedFile, id=sequence;if(!file)return;
        try{
            const result=await(await api('/files/'+file.id+'/versions')).json();
            if(id===sequence && $selectedFile?.id===file.id){versions=result;showVersions=!showVersions;}
        }catch(e:any){if(id===sequence && e.name!=='AbortError')error=e.message;}
    }
    function parseCsv(value:string):string[][] {
        const result:string[][]=[];let row:string[]=[],cell='',quoted=false;
        for(let i=0;i<value.length&&result.length<101;i++){
            const c=value[i];
            if(c==='"'){if(quoted&&value[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}
            else if(!quoted&&(c===','||c==='\n')){row.push(cell);cell='';if(c==='\n'){result.push(row);row=[];}}
            else if(c!=='\r'||quoted)cell+=c;
        }
        if(result.length<101&&(cell||row.length))result.push([...row,cell]);
        return result.map(r=>r.slice(0,50));
    }
    function beforeUnload(e:BeforeUnloadEvent){if(drafts.size){e.preventDefault();e.returnValue='';}}
</script>

<svelte:window bind:innerWidth={screenWidth} on:beforeunload={beforeUnload}/>
{#if $selectedFile}
<ResizableSidePanel open={true} bind:width minWidth={320} minSiblingWidth={360} storageKey="workspace-preview-width" resizerId="workspace-preview-resizer" className={screenWidth<900?'workspace-preview-panel workspace-mobile':'workspace-preview-panel'} onClose={()=>selectedFile.set(null)}>
    <section class="flex h-full min-h-0 flex-col bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-800" aria-label="文件预览与编辑">
        <header class="px-4 py-3 border-b dark:border-gray-800">
            <div class="flex items-center justify-between gap-2"><h2 class="font-medium truncate" title={$selectedFile.path}>{$selectedFile.name}</h2><button aria-label="关闭文件预览" class="px-2 py-1" on:click={()=>selectedFile.set(null)}>✕</button></div>
            <p class="text-xs text-gray-500 truncate mt-1">{$selectedFile.path} · {Math.ceil($selectedFile.size/1024)} KB · 版本 {version}</p>
            <div class="flex items-center gap-3 text-xs mt-3 flex-wrap">
                {#if editable}<button class:text-blue-600={mode==='preview'} on:click={()=>mode='preview'}>预览</button><button class:text-blue-600={mode==='source'} on:click={()=>mode='source'}>源码／编辑</button><button class="bg-blue-600 text-white rounded px-2 py-1 disabled:opacity-40" disabled={!dirty || saving.has($selectedFile.id)} on:click={save}>{saving.has($selectedFile.id)?'保存中…':'保存'}</button>{/if}
                <button on:click={()=>downloadFile($selectedFile!).catch(e=>error=e.message)}>下载</button><button on:click={history}>历史版本</button>
                {#if dirty}<span class="text-amber-600">未保存，草稿已暂存</span>{/if}
            </div>
        </header>
        {#if error}<div role="alert" class="m-3 rounded-lg bg-amber-50 dark:bg-amber-950/30 p-3 text-xs text-amber-800 dark:text-amber-200">{error}</div>{/if}
        {#if $selectedFile.version!==version && !loading}<div class="p-3 text-xs text-amber-700">文件已有新版本。<button class="underline" on:click={()=>{if($selectedFile){drafts.delete($selectedFile.id);load($selectedFile);}}}>放弃当前草稿并重新载入</button></div>{/if}
        {#if showVersions}<div class="max-h-48 overflow-auto border-b dark:border-gray-700 p-3 text-xs">{#each versions as v}<div class="flex justify-between py-1"><span>版本 {v.revision} · {Math.ceil(v.size/1024)} KB</span><button class="text-blue-600" on:click={()=>downloadFile($selectedFile!,v.revision).catch(e=>error=e.message)}>下载此版本</button></div>{/each}</div>{/if}
        <div class="flex-1 min-h-0 overflow-auto">
            {#if loading}<p role="status" class="p-5 text-sm text-gray-500">正在读取文件…</p>
            {:else if kind==='pdf' && pdf}<PDFViewer data={pdf} className="w-full h-full" />
            {:else if kind==='image' && url}
                <div class="sticky top-0 flex justify-end gap-2 p-2 bg-white/90 dark:bg-gray-900/90 text-sm"><button aria-label="缩小图片" on:click={()=>zoom=Math.max(.25,zoom-.25)}>−</button><button on:click={()=>zoom=1}>{Math.round(zoom*100)}%</button><button aria-label="放大图片" on:click={()=>zoom=Math.min(4,zoom+.25)}>＋</button></div>
                <img src={url} alt={$selectedFile.name} on:error={imageFailed} style:width={zoom*100+'%'} style:max-width="none" class="p-3" />
            {:else if editable && mode==='source'}
                <textarea aria-label="文件源码编辑器" class="w-full h-full min-h-96 p-4 bg-transparent font-mono text-sm resize-none outline-none" value={text} on:input={(event)=>editText(event.currentTarget.value)} spellcheck="false"></textarea>
            {:else if kind==='markdown'}
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <article class="workspace-markdown p-5 text-sm leading-7 break-words" on:click={follow}>{@html markdown}</article>
            {:else if kind==='csv'}<div class="p-3"><p class="text-xs text-gray-500 mb-2">预览前 100 行、50 列；完整内容可下载或查看源码。</p><table class="text-xs border-collapse"><tbody>{#each csvRows.slice(0,100) as row}<tr>{#each row as cell}<td class="border border-gray-200 dark:border-gray-700 p-2 max-w-60 break-words">{cell}</td>{/each}</tr>{/each}</tbody></table></div>
            {:else if kind==='code'}<pre class="p-4 text-xs whitespace-pre-wrap break-words"><code>{@html highlight}</code></pre>
            {:else}<div class="p-6 text-sm text-gray-500">此格式暂不支持内嵌预览，请下载后查看。</div>{/if}
        </div>
    </section>
</ResizableSidePanel>
{/if}

<style>
    :global(.workspace-markdown h1){font-size:1.6em;font-weight:600;margin:1em 0 .6em;}
    :global(.workspace-markdown h2){font-size:1.3em;font-weight:600;margin:1em 0 .5em;}
    :global(.workspace-markdown h3){font-weight:600;margin:1em 0 .5em;}
    :global(.workspace-markdown p){margin:.7em 0;}
    :global(.workspace-markdown ul){list-style:disc;padding-left:1.5em;}
    :global(.workspace-markdown ol){list-style:decimal;padding-left:1.5em;}
    :global(.workspace-markdown a){color:#2563eb;text-decoration:underline;}
    :global(.workspace-markdown table){border-collapse:collapse;display:block;overflow:auto;}
    :global(.workspace-markdown td),:global(.workspace-markdown th){border:1px solid #8885;padding:.4em;}
    :global(.workspace-markdown pre){overflow:auto;background:#8881;padding:1em;border-radius:.5em;}
    :global(.workspace-preview-panel){height:100%;min-height:0;overflow:hidden;}
    :global(.workspace-mobile){position:fixed;inset:0;z-index:80;width:100%!important;height:100%!important;max-width:none!important;}
    @media(max-width:899px){:global(#workspace-preview-resizer){display:none;}}
</style>
