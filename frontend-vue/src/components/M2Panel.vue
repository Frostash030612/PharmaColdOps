<script setup>
import { computed, ref, watch } from 'vue';
import { useDecisionsStore } from '../stores/decisions.js';
import { PRODUCT_NUM } from '../data/products.js';
import { locale, bundle } from '../i18n/index.js';
import { postJson } from '../lib/api.js';

const props = defineProps({ productId: String, modelValue: Object, saved: Object, readonly: Boolean, offline: Boolean });
const emit = defineEmits(['update:modelValue', 'event', 'pending', 'reviewNeeded']);
const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));
const mode = ref(props.modelValue ? 'series' : 'manual');
const scenario = ref('hot'), seed = ref(42), horizon = ref(props.modelValue?.series.observation_end_min || 120), cadence = ref(5);
const energy = ref(props.modelValue?.series.activation_energy_kj_mol || 83.144);
const raw = ref(props.modelValue ? JSON.stringify(props.modelValue.series.intervals, null, 2) : '[]');
const result = ref(null), analysedSeries = ref(null), error = ref(''), busy = ref(false);
let sequence = 0;
const assessment = computed(() => props.readonly ? props.saved : result.value);
const series = computed(() => props.modelValue?.series || analysedSeries.value);
const spec = computed(() => assessment.value ? { min: assessment.value.storage_min_c, max: assessment.value.storage_max_c } : PRODUCT_NUM[props.productId]);
const x = t => 35 + t / series.value.observation_end_min * 600;
const bounds = computed(() => {
  const known = series.value?.intervals.filter(i => i.temp_c !== null).map(i => i.temp_c) || [];
  return [Math.min(spec.value.min, ...known) - 2, Math.max(spec.value.max, ...known) + 2];
});
const y = temp => 160 - (temp - bounds.value[0]) / (bounds.value[1] - bounds.value[0]) * 140;
const number = value => value == null ? '—' : value.toFixed(3);
const scenarioLabel = key => L.value.temperature.scenarios[key];

function invalidate() {
  sequence++; busy.value = false; result.value = null; analysedSeries.value = null; error.value = '';
  if (!props.readonly) { emit('update:modelValue', null); emit('pending', mode.value === 'series'); emit('reviewNeeded', false); }
}
function changeMode(value) { mode.value = value; invalidate(); }
function inputSeries() {
  return { source: 'manual_simulated', observation_end_min: Number(horizon.value),
    activation_energy_kj_mol: Number(energy.value), intervals: JSON.parse(raw.value) };
}
async function run(simulation) {
  if (props.readonly || props.offline || busy.value) return;
  invalidate(); const id = ++sequence; busy.value = true;
  try {
    const body = simulation ? { product_id: props.productId, scenario: scenario.value, seed: Number(seed.value),
      observation_end_min: Number(horizon.value), interval_min: Number(cadence.value) }
      : { product_id: props.productId, series: inputSeries() };
    const response = await postJson(decisions.apiBase + (simulation ? '/api/m2/simulate' : '/api/m2/analyse'), body);
    if (id !== sequence || props.readonly || props.offline) return;
    analysedSeries.value = simulation ? response.series : body.series;
    result.value = simulation ? response.analysis : response;
    if (simulation) { raw.value = JSON.stringify(response.series.intervals, null, 2); energy.value = response.series.activation_energy_kj_mol; }
  } catch (e) { if (id === sequence) error.value = String(e.message || e); }
  finally { if (id === sequence) busy.value = false; }
}
function choose(window) {
  if (props.readonly || props.offline || busy.value) return;
  emit('update:modelValue', { series: JSON.parse(JSON.stringify(analysedSeries.value)), window_id: window.window_id, method: result.value.method });
  emit('event', window.event); emit('pending', false);
  emit('reviewNeeded', !window.registration_allowed || result.value.windows.length > 1);
}
function chooseObservation() {
  if (props.readonly || props.offline || busy.value || !result.value) return;
  emit('update:modelValue', { series: JSON.parse(JSON.stringify(analysedSeries.value)), window_id: null, method: result.value.method });
  emit('event', { excursion_temp_c: null, duration_min: null, mkt_c: null }); emit('pending', false); emit('reviewNeeded', true);
}
watch(() => [props.productId, props.offline, props.readonly, decisions.apiBase], () => invalidate());
</script>

<template>
  <section class="m2-panel">
    <h3>{{ L.temperature.title }}</h3>
    <p>{{ L.temperature.disclosure }}</p>
    <p v-if="offline">{{ L.temperature.offline }}</p>
    <template v-if="!readonly && !offline">
      <div class="m2-actions">
        <button type="button" :class="{on: mode === 'manual'}" @click="changeMode('manual')">{{ L.temperature.manual }}</button>
        <button type="button" :class="{on: mode === 'series'}" @click="changeMode('series')">{{ L.temperature.sequence }}</button>
      </div>
      <fieldset v-if="mode === 'series'" :disabled="busy">
        <div class="m2-actions">
          <label>{{ L.temperature.scenario }}<select v-model="scenario" @change="invalidate"><option v-for="key in ['normal','hot','cold','mixed','gap']" :key="key" :value="key">{{ scenarioLabel(key) }}</option></select></label>
          <label>{{ L.temperature.seed }}<input v-model="seed" type="number" min="0" max="4294967295" @input="invalidate"></label>
          <label>{{ L.temperature.horizon }}<input v-model="horizon" type="number" min="1" max="10080" @input="invalidate"></label>
          <label>{{ L.temperature.cadence }}<input v-model="cadence" type="number" min="1" max="60" @input="invalidate"></label>
          <button type="button" @click="run(true)">{{ L.temperature.generate }}</button>
        </div>
        <details class="m2-editor">
          <summary>{{ L.temperature.edit }}</summary>
          <p>{{ L.temperature.intervalHelp }}</p>
          <label>{{ L.temperature.energy }}<input v-model="energy" type="number" min="20" max="200" step="any" @input="invalidate"></label>
          <textarea v-model="raw" :aria-label="L.temperature.json" rows="8" @input="invalidate"></textarea>
          <button type="button" @click="run(false)">{{ L.temperature.analyse }}</button>
        </details>
      </fieldset>
    </template>
    <p v-if="mode === 'manual' && !readonly">{{ L.temperature.manualNote }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="busy" role="status">{{ L.temperature.loading }}</p>
    <template v-if="series">
      <svg class="m2-chart" viewBox="0 0 660 195" role="img" :aria-label="L.temperature.chart">
        <rect x="35" :y="y(spec.max)" width="600" :height="y(spec.min)-y(spec.max)" fill="#dcfce7" />
        <line v-for="i in series.intervals.filter(i => i.temp_c !== null)" :key="i.start_min" :x1="x(i.start_min)" :x2="x(i.end_min)" :y1="y(i.temp_c)" :y2="y(i.temp_c)" :stroke="i.temp_c < spec.min || i.temp_c > spec.max ? '#dc2626' : '#0284c7'" stroke-width="3" />
        <text x="0" :y="y(spec.max)">{{ spec.max }}°C</text><text x="0" :y="y(spec.min)">{{ spec.min }}°C</text>
        <text x="35" y="187">0 min</text><text x="580" y="187">{{ series.observation_end_min }} min</text>
      </svg>
      <p>{{ L.temperature.energy }}: {{ series.activation_energy_kj_mol }} kJ/mol · {{ series.source }}</p>
    </template>
    <template v-if="assessment">
      <p>{{ L.temperature.coverage }}: {{ (assessment.coverage_ratio*100).toFixed(2) }}% · {{ L.temperature.fullMkt }}: {{ number(assessment.known_only_mkt_c) }}°C</p>
      <p>{{ L.temperature.hotTotal }}: {{ number(assessment.total_hot_min) }} min · {{ L.temperature.coldTotal }}: {{ number(assessment.total_cold_min) }} min</p>
      <p class="m2-warning">{{ L.temperature.scope }}</p>
      <p v-if="!assessment.coverage_complete" class="m2-warning">{{ L.temperature.gap }} · {{ assessment.missing_intervals.map(g => `${g.start_min}–${g.end_min} min`).join(', ') }}</p>
      <p v-if="!assessment.windows.length">{{ L.temperature.noWindows }}</p>
      <button v-if="!readonly && (!assessment.coverage_complete || assessment.windows.length > 1)" type="button" :disabled="offline || busy" @click="chooseObservation">{{ L.review.observation }}</button>
      <div v-for="window in assessment.windows" :key="window.window_id" class="m2-window" :class="{selected: modelValue?.window_id === window.window_id}">
        <strong>{{ window.window_id }} · {{ scenarioLabel(window.kind) }} · {{ window.start_min }}–{{ window.end_min }} min</strong>
        <p>{{ L.temperature.extreme }}: {{ window.event.excursion_temp_c }}°C · {{ L.center.dur }}: {{ window.duration_exact_min }} → {{ window.event.duration_min }} min · MKT: {{ number(window.event.mkt_c) }}°C</p>
        <p v-if="window.blocked_reason === 'cold_rule_not_supported'" class="m2-warning">{{ L.temperature.coldBlocked }}</p>
        <button v-if="!readonly" type="button" :disabled="offline || busy" @click="choose(window)">{{ modelValue?.window_id === window.window_id ? L.temperature.selected : window.registration_allowed ? L.temperature.select : L.review.selectHeld }}</button>
      </div>
      <small>{{ assessment.method }} · {{ assessment.source_hash }}</small>
    </template>
    <p v-if="readonly && !assessment && modelValue">{{ L.temperature.frozenDraft }} · {{ modelValue.window_id }}</p>
    <p v-if="!readonly && mode === 'series' && !modelValue">{{ L.temperature.mustSelect }}</p>
  </section>
</template>

<style scoped>
.m2-panel { border: 1px solid #cbd5e1; border-radius: 10px; padding: 14px; margin: 12px 0; }
.m2-panel h3 { margin: 0 0 8px; } .m2-panel p { font-size: 12px; margin: 8px 0; }
fieldset { border: 0; padding: 0; min-width: 0; }
.m2-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: end; }
label { display: grid; font-size: 12px; gap: 4px; } input { max-width: 110px; }
button, select, input, textarea { border: 1px solid #cbd5e1; padding: 6px; border-radius: 5px; }
button { cursor: pointer; } button:disabled { opacity: .5; cursor: default; } button.on { background: #dbeafe; }
textarea { box-sizing: border-box; width: 100%; font-family: monospace; font-size: 11px; margin: 8px 0; }
.m2-chart { width: 100%; height: auto; } .m2-chart text { font-size: 10px; }
.m2-window { margin: 8px 0; border: 1px solid #e2e8f0; padding: 8px; border-radius: 6px; font-size: 12px; }
.m2-window.selected { border-color: #2563eb; } .m2-warning { color: #92400e; }
small { overflow-wrap: anywhere; } .m2-editor { margin-top: 12px; }
</style>
