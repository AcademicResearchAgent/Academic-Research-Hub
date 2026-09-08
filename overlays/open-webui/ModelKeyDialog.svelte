<script lang="ts">
  import { onMount, onDestroy, createEventDispatcher } from 'svelte';
  import Modal from '$lib/components/common/Modal.svelte';
  export let show = true;
  export let modelId = '';
  const dispatch = createEventDispatcher();
  let catalog: any = null;
  let apiKey = '';
  let endpointId = '';
  let busy = false;
  let error = '';
  let secure = false;
  $: selected = catalog?.models.find((m: any) => m.id === modelId);
  $: provider = selected ? catalog.providers[selected.provider] : null;
  $: configured = selected ? catalog.credentials[selected.provider]?.configured : false;

  async function request(path: string, method = 'GET', body?: any) {
    const response = await fetch('/api/workstation' + path, {
      method, headers: { Authorization: `Bearer ${localStorage.token}`, 'Content-Type': 'application/json' },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '操作失败，请重试。');
    return data;
  }
  function chooseModel() {
    apiKey = ''; error = '';
    const model = catalog?.models.find((m: any) => m.id === modelId);
    endpointId = model ? (catalog.credentials[model.provider]?.endpoint_id || catalog.providers[model.provider].endpoints[0].id) : '';
  }
  onMount(async () => {
    secure = window.isSecureContext;
    try {
      catalog = await request('/catalog');
      if (!catalog.models.some((m: any) => m.id === modelId)) modelId = catalog.models[0]?.id || '';
      chooseModel();
    } catch (e) { error = e instanceof Error ? e.message : '操作失败，请重试。'; }
  });
  onDestroy(() => { apiKey = ''; });
  async function save() {
    if (!secure || !apiKey.trim() || busy) return;
    busy = true; error = '';
    try {
      await request('/credentials', 'POST', {model_id: modelId, endpoint_id: endpointId, api_key: apiKey.trim()});
      apiKey = ''; show = false; dispatch('ready', modelId);
    } catch (e) { error = e instanceof Error ? e.message : '操作失败，请重试。'; }
    finally { busy = false; }
  }
  async function useSaved() {
    busy = true; error = '';
    try {
      await request('/models/' + encodeURIComponent(modelId) + '/activate', 'POST');
      show = false; dispatch('ready', modelId);
    } catch (e) { error = e instanceof Error ? e.message : '操作失败，请重试。'; }
    finally { busy = false; }
  }
  async function remove() {
    busy = true; error = '';
    try {
      await request('/credentials/' + selected.provider, 'DELETE');
      catalog = await request('/catalog'); apiKey = ''; chooseModel();
    } catch (e) { error = e instanceof Error ? e.message : '操作失败，请重试。'; }
    finally { busy = false; }
  }
</script>

<Modal bind:show size="sm">
  <div class="p-5 space-y-4" data-workstation-model-keys>
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold">模型与 API Key</h2>
      <button type="button" aria-label="关闭模型配置" class="rounded-lg px-2 py-1" on:click={() => {show = false;}}>关闭</button>
    </div>
    <p class="text-sm text-gray-500">首次使用厂商模型时，填写你自己的 API Key。同一厂商可复用已配置的密钥，其他账号无法使用。</p>
    {#if catalog}
      <label class="block text-sm">选择模型
        <select class="mt-1 w-full rounded-xl border border-gray-300 dark:border-gray-700 bg-transparent p-2" bind:value={modelId} on:change={chooseModel} disabled={busy}>
          {#each catalog.models as model}<option value={model.id}>{model.name}</option>{/each}
        </select>
      </label>
      {#if selected && provider}
        <p class="text-sm text-gray-500">{selected.description}</p>
        <div class="flex items-center justify-between text-sm">
          <span>{provider.name} · {configured ? '已配置' : '待配置'}</span>
          <a class="underline" href={provider.key_url} target="_blank" rel="noopener noreferrer">获取 API Key</a>
        </div>
        <label class="block text-sm">接入区域
          <select class="mt-1 w-full rounded-xl border border-gray-300 dark:border-gray-700 bg-transparent p-2" bind:value={endpointId} disabled={busy}>
            {#each provider.endpoints as endpoint}<option value={endpoint.id}>{endpoint.name}</option>{/each}
          </select>
        </label>
        {#if !secure}
          <div class="rounded-xl bg-amber-50 dark:bg-amber-950 p-3 text-sm" role="status">当前是 HTTP 连接。请通过工作站 HTTPS 地址或 localhost SSH 隧道填写 API Key；已有密钥的模型仍可选择使用。</div>
        {/if}
        <form on:submit|preventDefault={save} class="space-y-3">
          <label class="block text-sm">{configured ? '更换 API Key' : 'API Key'}
            <input class="mt-1 w-full rounded-xl border border-gray-300 dark:border-gray-700 bg-transparent p-2" type="password" bind:value={apiKey} autocomplete="off" spellcheck="false" placeholder={configured ? '填写新密钥以替换' : '粘贴该厂商的 API Key'} disabled={!secure || busy} />
          </label>
          <p class="text-xs text-gray-500">密钥由本站加密保存，不写入聊天记录。验证会向所选模型发送一条简短请求。</p>
          <button class="w-full rounded-xl bg-gray-900 dark:bg-white text-white dark:text-black px-4 py-2 disabled:opacity-40" type="submit" disabled={!secure || !apiKey.trim() || busy}>{busy ? '正在验证…' : '保存并使用'}</button>
        </form>
        {#if configured}
          <div class="flex gap-4 text-sm">
            <button class="underline" disabled={busy} on:click={useSaved}>使用已保存的密钥</button>
            <button class="text-red-600 underline" disabled={busy} on:click={remove}>删除此厂商密钥</button>
          </div>
        {/if}
      {/if}
      <p class="text-xs text-gray-400">目录核对日期：{catalog.checked_at}。实际可用模型取决于厂商区域和账号权限。</p>
    {:else if !error}
      <p class="text-sm">正在加载模型目录…</p>
    {/if}
    {#if error}<p role="alert" class="rounded-xl bg-red-50 dark:bg-red-950 p-3 text-sm text-red-700 dark:text-red-200">{error}</p>{/if}
  </div>
</Modal>
