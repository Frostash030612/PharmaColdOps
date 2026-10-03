<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue';
import { useDecisionsStore } from '../stores/decisions.js';
import { locale, bundle } from '../i18n/index.js';
import { postJson } from '../lib/api.js';
import { eventReasonLabel, v2Context } from '../lib/eventV2.js';

const props = defineProps({ productId: String, modelValue: Object, saved: Object, readonly: Boolean, offline: Boolean });
const emit = defineEmits(['update:modelValue', 'adopt', 'pending']);
const decisions = useDecisionsStore(), L = computed(() => bundle(locale.value));
const raw = ref(props.modelValue ? JSON.stringify(props.modelValue.observation, null, 2) : '');
const samples = ref([]), sampleId = ref(''), result = ref(null), analysed = ref(null), info = ref(null), error = ref(''), busy = ref(false);
let sequence = 0;
const assessment = computed(() => props.readonly ? props.saved : result.value);
const eligibleSamples = computed(() => samples.value.filter(s => s.observation.product_id === props.productId));
const reasons = computed(() => (assessment.value?.reasons || []).map(k => eventReasonLabel(k, L.value.eventV2.reasons)));
const scores = computed(() => Object.entries(assessment.value?.scores || {}).sort((a,b) => b[1]-a[1]).slice(0,3));
const causeLabel = key => L.value.eventV2.causes[key] || key;
function invalidate() {
  sequence++; busy.value = false; result.value = null; analysed.value = null; error.value = '';
  if (!props.readonly) { emit('update:modelValue', null); emit('pending', false); }
}
async function get(path) {
  const r = await fetch(decisions.apiBase + path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
async function loadSamples() {
  if (props.readonly || props.offline || busy.value) return;
  invalidate(); const id = ++sequence; busy.value = true; emit('pending', true);
  try {
    const state = await get('/api/ml/event/v2/info');
    if (id !== sequence || props.offline || props.readonly) return;
    info.value = state;
    if (state.status !== 'shadow_ready') return;
    const response = await get('/api/ml/event/v2/samples');
    if (id === sequence && !props.offline && !props.readonly) samples.value = response.samples;
  } catch (e) { if (id === sequence) error.value = String(e.message || e); }
  finally { if (id === sequence) { busy.value = false; emit('pending', false); } }
}
function choose() {
  invalidate(); const sample = samples.value.find(s => s.sample_id === sampleId.value);
  raw.value = sample ? JSON.stringify(sample.observation, null, 2) : '';
}
async function preview() {
  if (props.readonly || props.offline || busy.value) return;
  invalidate(); const id = ++sequence; busy.value = true; emit('pending', true);
  try {
    const observation = JSON.parse(raw.value);
    if (observation.product_id !== props.productId) throw new Error(L.value.eventV2.productMismatch);
    const response = await postJson(decisions.apiBase + '/api/ml/event/v2/assess', { observation });
    if (id !== sequence || props.offline || props.readonly) return;
    analysed.value = observation; result.value = response;
  } catch (e) { if (id === sequence) error.value = String(e.message || e); }
  finally { if (id === sequence) { busy.value = false; emit('pending', false); } }
}
function adopt() {
  if (props.readonly || props.offline || busy.value) return;
  try {
    const value = v2Context(result.value, analysed.value, props.productId);
    emit('update:modelValue', value.eventContext); emit('adopt', value);
  } catch (e) { error.value = String(e.message || e); }
}
function clear() { invalidate(); raw.value = ''; sampleId.value = ''; }
watch(() => [props.productId, props.offline, props.readonly, decisions.apiBase], () => {
  invalidate(); raw.value = ''; sampleId.value = ''; info.value = null; samples.value = [];
});
onBeforeUnmount(() => { sequence++; });
</script>

<template>
  <section class="event-v2-panel">
    <h3>{{ L.eventV2.title }}</h3><p>{{ L.eventV2.disclosure }}</p>
    <p v-if="offline">{{ L.eventV2.offline }}</p>
    <template v-if="!readonly && !offline">
      <div class="event-v2-actions"><button type="button" :disabled="busy" @click="loadSamples">{{ L.eventV2.load }}</button>
        <label>{{ L.eventV2.sample }}<select v-model="sampleId" :disabled="busy" @change="choose"><option value="">—</option><option v-for="sample in eligibleSamples" :key="sample.sample_id" :value="sample.sample_id">{{ L.eventV2.roles[sample.role] || sample.role }} · {{ sample.sample_id }}</option></select></label>
      </div>
      <p v-if="info && info.status !== 'shadow_ready'">{{ info.status === 'disabled' ? L.eventV2.disabled : L.eventV2.unavailable }}</p>
      <p v-if="samples.length">{{ L.eventV2.sampleNote }}</p>
      <label>{{ L.eventV2.input }}<textarea v-model="raw" rows="7" :disabled="busy" :aria-label="L.eventV2.input" @input="invalidate" /></label>
      <div class="event-v2-actions"><button type="button" :disabled="busy || !raw.trim()" @click="preview">{{ L.eventV2.preview }}</button><button type="button" :disabled="busy" @click="clear">{{ L.eventV2.clear }}</button></div>
    </template>
    <p v-if="busy" role="status">{{ L.eventV2.loading }}</p><p v-if="error" role="alert">{{ error }}</p>
    <div v-if="assessment" class="event-v2-result">
      <strong>{{ L.eventV2.status[assessment.status] || assessment.status }}</strong><p>{{ L.eventV2.mandatoryReview }}</p>
      <p v-if="assessment.model_id">{{ assessment.model_id }} · {{ assessment.feature_count }} {{ L.eventV2.features }}</p>
      <p v-if="assessment.candidates?.length">{{ L.eventV2.candidates }}: {{ assessment.candidates.map(causeLabel).join(' · ') }}</p>
      <ul><li v-for="reason in reasons" :key="reason">{{ reason }}</li></ul>
      <p v-if="scores.length">{{ L.eventV2.scores }}: {{ scores.map(([key,value]) => `${causeLabel(key)}: ${value.toFixed(4)}`).join(' · ') }}</p>
      <details><summary>{{ L.eventV2.provenance }}</summary><p>{{ assessment.model_sha256 }}<br>{{ assessment.policy_sha256 }}<br>{{ assessment.observation_sha256 }}</p></details>
      <button v-if="!readonly && !offline && ['candidate_only','abstained'].includes(assessment.status)" type="button" :disabled="busy" @click="adopt">{{ L.eventV2.adopt }}</button>
    </div>
    <p v-if="modelValue && !readonly">{{ L.eventV2.attached }}</p>
    <p v-if="readonly">{{ saved ? L.eventV2.frozen : L.eventV2.noSnapshot }}</p>
  </section>
</template>

<style scoped>
.event-v2-panel { border:1px solid #94a3b8; border-radius:10px; padding:14px; margin:12px 0; }
h3 { margin:0 0 8px; } p, label, li, details { font-size:12px; } label { display:grid; gap:4px; }
.event-v2-actions { display:flex; gap:8px; flex-wrap:wrap; align-items:end; margin:8px 0; }
button, select, textarea { border:1px solid #cbd5e1; border-radius:5px; padding:6px; max-width:100%; }
textarea { box-sizing:border-box; width:100%; font-family:monospace; font-size:11px; }
button:disabled { opacity:.5; } .event-v2-result { background:#fffbeb; padding:10px; border-radius:7px; overflow-wrap:anywhere; }
</style>
