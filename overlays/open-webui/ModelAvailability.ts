export type Availability = {
  state: 'unconfigured' | 'available' | 'unavailable' | 'checking' | 'error';
  detail?: string;
  checked_at?: number | null;
};

export const statusLabel = (status?: Availability) => ({
  unconfigured: '未配置', available: '可用', unavailable: '不可用',
  checking: '检测中…', error: '检测失败'
}[status?.state || 'checking']);

export async function refreshAvailability(
  update: (states: Record<string, Availability>) => void,
  signal: AbortSignal
) {
  const headers = { Authorization: `Bearer ${localStorage.token}` };
  const response = await fetch('/api/workstation/catalog', { headers, signal });
  if (!response.ok) throw new Error('无法获取模型状态，请重新打开模型列表。');
  const catalog = await response.json();
  let states: Record<string, Availability> = catalog.availability;
  update({ ...states });
  await Promise.all(catalog.models.map(async (model: { id: string }) => {
    if (states[model.id]?.state !== 'checking') return;
    try {
      const result = await fetch('/api/workstation/models/' + encodeURIComponent(model.id) + '/check', {
        method: 'POST', headers, signal
      });
      const data = await result.json();
      if (!result.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '检测失败，请重试。');
      states = { ...states, [model.id]: data };
    } catch (error) {
      if (signal.aborted) return;
      states = { ...states, [model.id]: { state: 'error', detail: error instanceof Error ? error.message : '检测失败，请重试。' } };
    }
    if (!signal.aborted) update({ ...states });
  }));
  return catalog;
}
