<script setup>
import { computed, ref, watch } from 'vue';
import { useDecisionsStore } from '../stores/decisions.js';
import { locale, bundle } from '../i18n/index.js';
import { postJson } from '../lib/api.js';
import { contextKey, contextPayload, replaceContext } from '../lib/ml.js';
const props = defineProps({ modelValue: { type: Array, default: () => [] }, saved: { type: Array, default: () => [] }, readonly: Boolean, offline: Boolean });
const emit = defineEmits(['update:modelValue']);
const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));
const task = ref('risk');
const models = ref(null), samples = ref([]), values = ref({}), sampleId = ref(null);
const result = ref(null), error = ref(''), busy = ref(false), evaluatedKey = ref(null);
let sequence = 0;
const active = computed(() => models.value?.[task.value]);
const fields = computed(() => active.value?.fields || []);
const attached = computed(() => props.modelValue.some(c => c.task === task.value));
const evidence = computed(() => props.saved.length ? props.saved : result.value ? [result.value] : []);
const label = key => L.value.ml.features[key] || key;
const percent = value => `${(value * 100).toFixed(1)}%`;
const currentKey = () => contextKey(contextPayload(task.value, fields.value, values.value, sampleId.value));
const fresh = computed(() => { try { return evaluatedKey.value === currentKey(); } catch { return false; } });
async function init() {
  if (props.offline || props.readonly) return;
  const id = ++sequence;
  try {
    const response = await fetch(decisions.apiBase + '/api/ml/models');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json();
    if (id === sequence && !props.offline && !props.readonly) models.value = body;
  } catch(e) { if (id === sequence) error.value = String(e.message || e); }
}
function clearSelected() {
  sequence++; result.value = null; evaluatedKey.value = null; samples.value = []; values.value = {}; sampleId.value = null; error.value = ''; busy.value = false;
}
function edit(key, value) {
  values.value[key] = value; sampleId.value = null; result.value = null; evaluatedKey.value = null;
  sequence++; busy.value = false;
  emit('update:modelValue', replaceContext(props.modelValue, task.value));
}
async function loadSamples() {
  if (props.offline || props.readonly || busy.value) return;
  const id = ++sequence; busy.value = true; error.value = '';
  try {
    const response = await fetch(`${decisions.apiBase}/api/ml/samples/${task.value}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json();
    if (id === sequence && !props.offline && !props.readonly) samples.value = body.samples;
  } catch(e) { if (id === sequence) error.value = String(e.message || e); }
  finally { if (id === sequence) busy.value = false; }
}
function chooseSample(id) {
  const sample = samples.value.find(s => s.sample_id === id);
  if (!sample) return;
  values.value = { ...sample.features }; sampleId.value = id; result.value = null; evaluatedKey.value = null;
  sequence++; emit('update:modelValue', replaceContext(props.modelValue, task.value));
}
async function predict() {
  if (props.offline || props.readonly || busy.value) return;
  const id = ++sequence; busy.value = true; error.value = ''; result.value = null;
  try {
    const body = contextPayload(task.value, fields.value, values.value, sampleId.value);
    const key = contextKey(body);
    const response = await postJson(decisions.apiBase + '/api/ml/predict', body);
    if (id === sequence && !props.offline && !props.readonly && currentKey() === key) { result.value = response; evaluatedKey.value = key; }
  } catch(e) { if (id === sequence) error.value = String(e.message || e); }
  finally { if (id === sequence) busy.value = false; }
}
function attach(on) {
  if (props.offline || props.readonly || !fresh.value || busy.value) return;
  const context = on ? contextPayload(task.value, fields.value, values.value, sampleId.value) : null;
  emit('update:modelValue', replaceContext(props.modelValue, task.value, context));
}
watch(task, clearSelected);
watch(() => [props.offline, props.readonly, decisions.apiBase], () => { clearSelected(); init(); }, { immediate: true });
</script>

<template>
  <section class="m4-panel">
    <h3>{{ L.ml.title }}</h3>
    <p class="m4-disclosure">{{ L.ml.disclosure }}</p>
    <p v-if="offline" class="m4-note">{{ L.ml.offline }}</p>
    <p v-else-if="readonly && !saved.length">{{ L.ml.noSnapshot }}</p>
    <template v-if="!offline && !readonly">
      <div class="m4-tabs"><button type="button" :class="{on: task === 'risk'}" @click="task = 'risk'">{{ L.ml.risk }}</button><button type="button" :class="{on: task === 'cause'}" @click="task = 'cause'">{{ L.ml.cause }}</button></div>
      <p v-if="active?.status === 'unavailable'" role="status">{{ L.ml.unavailable }}</p>
      <p v-else-if="!models">{{ L.ml.loading }}</p>
      <template v-else-if="active?.status === 'ready'">
        <p>{{ active.algorithm }} · {{ active.model_id }} · {{ L.ml.testMetric }} {{ task === 'risk' ? `F1 ${active.test_metrics.f1.toFixed(3)} · AUC ${active.test_metrics.auc.toFixed(3)}` : `macro-F1 ${active.test_metrics.macro_f1.toFixed(3)} · top-3 ${percent(active.test_metrics.top3)}` }}</p>
        <p v-if="task === 'cause' && active.test_metrics.macro_f1 < .5" class="m4-warning">{{ L.ml.weakCause }}</p>
        <button type="button" :disabled="busy" @click="loadSamples">{{ L.ml.samples }}</button>
        <select v-if="samples.length" class="m4-sample" :value="sampleId || ''" :disabled="busy" @change="chooseSample($event.target.value)"><option value="">{{ L.ml.choose }}</option><option v-for="sample in samples" :key="sample.sample_id" :value="sample.sample_id">{{ sample.sample_id }}</option></select>
        <p v-if="sampleId">{{ L.ml.sampleNote }} · {{ sampleId }}</p>
        <details class="m4-inputs" open>
          <summary>{{ task === 'risk' ? L.ml.riskInputs : L.ml.causeInputs }}</summary>
          <fieldset :disabled="busy">
            <label v-for="field in fields" :key="field.key">{{ label(field.key) }}
              <select v-if="field.kind === 'category'" :value="values[field.key] ?? ''" @change="edit(field.key, $event.target.value)"><option value="">—</option><option v-for="option in field.options" :key="option" :value="option">{{ option }}</option></select>
              <input v-else type="number" :step="field.kind === 'integer' ? 1 : 'any'" :min="field.bounds[0]" :max="field.bounds[1]" :value="values[field.key] ?? ''" @input="edit(field.key, $event.target.value)" />
            </label>
          </fieldset>
        </details>
        <button type="button" class="m4-predict" :disabled="busy" @click="predict">{{ busy ? L.ml.loading : L.ml.predict }}</button>
        <label v-if="result?.status === 'predicted' && fresh" class="m4-attach"><input type="checkbox" :checked="attached" :disabled="busy" @change="attach($event.target.checked)" />{{ L.ml.attach }}</label>
        <p v-if="modelValue.length" class="m4-note">{{ L.ml.attached }}: {{ modelValue.map(c => c.task).join(' / ') }}</p>
      </template>
    </template>
    <p v-if="error" class="m4-warning" role="status">{{ error }}</p>
    <article v-for="assessment in evidence" :key="assessment.task" class="m4-result">
      <strong>{{ assessment.task === 'risk' ? L.ml.risk : L.ml.cause }}</strong>
      <p>{{ assessment.model_id }} · {{ assessment.source === 'dataset_sample' ? L.ml.sampleSource : L.ml.manualSource }} {{ assessment.sample_id || '' }}</p>
      <p v-if="assessment.status === 'out_of_domain'" class="m4-warning" role="status">{{ L.ml.ood }}: {{ assessment.unsupported_features.map(label).join(' / ') }}</p>
      <template v-else-if="assessment.status === 'predicted'">
        <p v-if="assessment.task === 'risk'" class="m4-probability">{{ L.ml.probability }}: <b>{{ percent(assessment.failure_probability) }}</b> · {{ L.ml.threshold }} {{ percent(assessment.threshold) }} · {{ assessment.above_threshold ? L.ml.above : L.ml.below }}</p>
        <ol v-else><li v-for="candidate in assessment.top_classes" :key="candidate.label">{{ candidate.label }} · {{ percent(candidate.probability) }}</li></ol>
        <p>{{ L.ml.explanation }}</p>
        <ul><li v-for="effect in assessment.explanations" :key="effect.feature">{{ label(effect.feature) }} · {{ effect.value }} → {{ effect.reference }} · Δ {{ (effect.probability_delta * 100).toFixed(1) }} pp</li></ul>
      </template>
      <p v-if="saved.length" class="m4-note">{{ L.ml.snapshot }}</p>
    </article>
  </section>
</template>

<style scoped>
.m4-panel { border: 1px solid #93c5fd; background: #eff6ff; padding: 14px; margin: 16px 0; border-radius: 10px; overflow-wrap:anywhere; }
.m4-panel h3 { margin-top:0; }.m4-panel p, .m4-panel li { font-size:12px; line-height:1.6; }
.m4-tabs { display:flex;gap:8px; }.m4-panel button { margin:5px 5px 5px 0; cursor:pointer; padding:6px 10px; }.m4-tabs .on { background:#1d4ed8;color:white; }
.m4-inputs fieldset { display:grid; grid-template-columns:1fr 1fr; gap:8px; border:0; padding:10px 0; }.m4-inputs label { display:grid;gap:4px;font-size:12px; }.m4-inputs input,.m4-inputs select { min-width:0;width:100%;box-sizing:border-box; }
.m4-warning { color:#92400e; }.m4-note { color:#475569; }.m4-result { background:white; padding:10px; margin-top:10px;border-radius:8px; }.m4-attach { display:block;font-size:12px; }.m4-attach input { margin-right:8px; }
</style>
