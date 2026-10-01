import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { eventPayload, decisionKey, postJson } from '../frontend-vue/src/lib/api.js';
const ev = { product_id: 'vaccine_2_8', excursion_temp_c: 12, duration_min: 11, mkt_c: 12, packaging: 'intact', stage: 'transit' };
const spec = { allowable: 30, mktThreshold: 10, retestable: true };
const context = { method: 'm2-interval-arrhenius-v1', window_id: 'window-001', series: {
  source: 'manual_simulated', observation_end_min: 10.5, activation_energy_kj_mol: 83.144,
  intervals: [{ start_min: 0, end_min: 10.5, temp_c: 12 }],
} };
const attached = { ...ev, temperature_context: context };
assert.equal(eventPayload(ev).temperature_context, undefined);
assert.equal(decisionKey(ev, spec), 'vaccine_2_8|12|11|12|intact|transit|30|10|true');
assert.notEqual(decisionKey(ev, spec), decisionKey(attached, spec));
const body = eventPayload(attached);
context.series.intervals[0].temp_c = 13;
assert.equal(body.temperature_context.series.intervals[0].temp_c, 12);
assert.equal(eventPayload({ ...attached, temperature_context: null }).temperature_context, undefined);
assert.equal(eventPayload({ ...attached, ml_contexts: [], temperature_context: null }).ml_contexts, undefined);
for (const lang of ['en', 'zh']) {
  const bundle = new Function(readFileSync(`frontend-vue/src/i18n/${lang}.js`, 'utf8').replace(/^export default/m, 'return'))();
  for (const key of ['normal', 'hot', 'cold', 'mixed', 'gap']) assert.equal(typeof bundle.temperature.scenarios[key], 'string');
}
const originalFetch = globalThis.fetch;
try {
  globalThis.fetch = async () => ({ ok: false, status: 422, json: async () => ({ detail: [{ loc: ['body', 'series', 'intervals'], msg: 'overlap' }] }) });
  await assert.rejects(postJson('/unused', {}), /body.series.intervals: overlap/);
} finally { globalThis.fetch = originalFetch; }
console.log('M2 optional source payload, immutable clone, cache key, dynamic translations and validation feedback passed.');
