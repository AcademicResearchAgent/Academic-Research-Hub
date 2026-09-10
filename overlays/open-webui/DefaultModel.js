// Follow the displayed model order, using the current account's probe results.
/**
 * @param {string[]} modelIds
 * @param {AbortSignal} signal
 * @param {typeof fetch} request
 */
export async function findFirstAvailableModel(modelIds, signal, request = fetch) {
  const headers = { Authorization: `Bearer ${localStorage.token}` };
  const response = await request('/api/workstation/catalog', { headers, signal });
  if (!response.ok) throw new Error('无法检测默认模型，请手动选择模型或稍后重试。');
  const catalog = await response.json();
  const ids = new Set(catalog.models.map(/** @param {{id: string}} model */ (model) => model.id));
  let failed = false;
  for (const id of modelIds) {
    signal.throwIfAborted();
    if (!ids.has(id)) continue;
    let status = catalog.availability[id];
    if (status?.state === 'checking') {
      try {
        const result = await request('/api/workstation/models/' + encodeURIComponent(id) + '/check', {
          method: 'POST', headers, signal
        });
        if (!result.ok) { failed = true; continue; }
        status = await result.json();
      } catch (error) {
        if (signal.aborted) throw error;
        failed = true;
        continue;
      }
    }
    signal.throwIfAborted();
    if (status?.state === 'available') return { modelId: id, failed };
  }
  return { modelId: null, failed };
}

/** Restore only models that the current account can select in this workstation.
 * @param {unknown} stored
 * @param {string[]} visibleIds
 * @returns {string[]}
 */
export function restoreWorkstationModels(stored, visibleIds) {
  const visible = new Set(visibleIds.filter(id => id.startsWith('ws-')));
  const restored = [...new Set((Array.isArray(stored) ? stored : [stored])
    .filter(id => typeof id === 'string' && visible.has(id)))];
  return restored.length ? restored : [''];
}
