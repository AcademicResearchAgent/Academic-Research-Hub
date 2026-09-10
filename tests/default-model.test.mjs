import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const code = fs.readFileSync(new URL('../overlays/open-webui/DefaultModel.js', import.meta.url), 'utf8');
const { findFirstAvailableModel, restoreWorkstationModels } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
globalThis.localStorage = { token: 'test-token' };
const response = (data) => ({ ok: true, json: async () => data });
const catalog = (states) => response({ models: Object.keys(states).map(id => ({ id })),
  availability: Object.fromEntries(Object.entries(states).map(([id, state]) => [id, { state }])) });

test('selects first available in displayed order, skipping unconfigured and unavailable', async () => {
  const calls = [];
  const request = async (url) => { calls.push(url); return catalog({ a:'unconfigured', b:'unavailable', c:'available', d:'available' }); };
  assert.equal((await findFirstAvailableModel(['a','b','d','c'], new AbortController().signal, request)).modelId, 'd');
  assert.equal(calls.length, 1);
});
test('checks earlier pending candidates before choosing a later cached available model', async () => {
  const calls = [];
  const request = async (url) => { calls.push(url); return url.endsWith('/catalog')
    ? catalog({ a:'checking', b:'available', c:'checking' }) : response({ state:'available' }); };
  assert.equal((await findFirstAvailableModel(['a','b','c'], new AbortController().signal, request)).modelId, 'a');
  assert.deepEqual(calls, ['/api/workstation/catalog','/api/workstation/models/a/check']);
});
test('does not invent a default when every model is unconfigured or unavailable', async () => {
  assert.equal((await findFirstAvailableModel(['a','b'], new AbortController().signal,
    async () => catalog({ a:'unconfigured', b:'unavailable' }))).modelId, null);
});
test('does not select models outside the visible list and tolerates one probe failure', async () => {
  const request = async (url) => url.endsWith('/catalog') ? catalog({ hidden:'available', a:'checking', b:'available' }) : { ok:false };
  assert.deepEqual(await findFirstAvailableModel(['a','b'], new AbortController().signal, request), {modelId:'b',failed:true});
});
test('cancelled checks cannot return a model and overwrite a newer choice', async () => {
  const controller = new AbortController();
  const request = async () => { controller.abort(); return catalog({ a:'available' }); };
  await assert.rejects(findFirstAvailableModel(['a'], controller.signal, request), { name:'AbortError' });
});

test('retired historical model cannot bypass the availability-based default', async () => {
  const visible = ['hermes-agent', 'ws-a', 'ws-b'];
  assert.deepEqual(restoreWorkstationModels(['hermes-agent', 'ws-deleted'], visible), ['']);
  const result = await findFirstAvailableModel(visible.filter(id => id.startsWith('ws-')),
    new AbortController().signal, async () => catalog({'ws-a':'unconfigured', 'ws-b':'available'}));
  assert.equal(result.modelId, 'ws-b');
});

test('restoration retains valid user choices without adding fallback models', () => {
  const visible = ['ws-a', 'ws-b'];
  assert.deepEqual(restoreWorkstationModels(['ws-b', 'ws-a', 'ws-b', 'hidden'], visible), ['ws-b', 'ws-a']);
  assert.deepEqual(restoreWorkstationModels('ws-b', visible), ['ws-b']);
  for (const value of [null, undefined, [], {}, ['hermes-agent'], ['ws-a']])
    assert.deepEqual(restoreWorkstationModels(value, []), ['']);
});
