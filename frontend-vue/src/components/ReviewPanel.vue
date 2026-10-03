<script setup>
import { computed, ref, watch } from 'vue';
import { useHistoryStore } from '../stores/history.js';
import { useDecisionsStore } from '../stores/decisions.js';
import { locale, bundle } from '../i18n/index.js';
import { postJson } from '../lib/api.js';
import routes from '../data/singaporeRoutes.json';
const history = useHistoryStore(), decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));
const record = computed(() => history.currentRun);
const reviewer = ref(''), reason = ref(''), disposition = ref('quarantine'), destination = ref('');
const request = ref(null), busy = ref(false), error = ref(''), storageWarning = ref(false);
const locked = computed(() => record.value?.execution_locked || ['handled', 'closed'].includes(record.value?.processing_status));
const label = value => value ? L.value.dispo[value]?.label || value : L.value.review.awaiting;
const reasons = computed(() => (record.value?.review_reasons || []).map(key => L.value.review.reasons[key] || key));
const key = () => `pharmacoldops:review:v1:${decisions.apiBase}:${record.value?.run_id}`;
function persist(value) {
  try { if (value) sessionStorage.setItem(key(), JSON.stringify(value)); else sessionStorage.removeItem(key()); }
  catch { storageWarning.value = true; }
}
function restore() {
  request.value = null; error.value = ''; reviewer.value = ''; reason.value = ''; disposition.value = 'quarantine';
  destination.value = record.value?.event.destination_facility_id || '';
  try {
    const value = JSON.parse(sessionStorage.getItem(key()) || 'null');
    if (value) { request.value = value; reviewer.value = value.reviewer; reason.value = value.reason; disposition.value = value.disposition; destination.value = value.destination_facility_id || ''; }
  } catch { storageWarning.value = true; }
}
watch(() => `${record.value?.run_id || ''}|${decisions.apiBase}`, restore, { immediate: true });
async function submit() {
  if (busy.value || !record.value || decisions.apiUp !== true || (!request.value && locked.value)) return;
  if (!request.value) {
    request.value = { command_id: `review-${crypto.randomUUID()}`, expected_version: record.value.workflow_version,
      reviewer: reviewer.value.trim(), reason: reason.value.trim(), disposition: disposition.value,
      destination_facility_id: destination.value || null };
    persist(request.value);
  }
  busy.value = true; error.value = '';
  try {
    const updated = await postJson(`${decisions.apiBase}/api/runs/${record.value.run_id}/review`, request.value);
    persist(null); request.value = null;
    history.runs = history.runs.map(r => r.run_id === updated.run_id ? updated : r);
    reason.value = '';
  } catch (e) { error.value = String(e.message || e); if ([404, 422].includes(e.status)) { persist(null); request.value = null; } await history.refresh(); }
  finally { busy.value = false; }
}
function discard() { if (window.confirm(L.value.review.discardConfirm)) { persist(null); request.value = null; history.refresh(); } }
const exportUrl = format => `${decisions.apiBase}/api/runs/${encodeURIComponent(record.value.run_id)}/audit?format=${format}&lang=${locale.value}`;
</script>

<template>
  <section v-if="record" class="review-panel">
    <h3>{{ L.review.title }}</h3><p>{{ L.review.disclosure }}</p>
    <dl><dt>{{ L.review.original }}</dt><dd>{{ record.automatic_assessment_available === false ? L.review.unassessed : label(record.disposition) }}</dd>
      <dt>{{ L.review.effective }}</dt><dd class="effective-decision">{{ record.review_status === 'pending' ? L.review.awaiting : label(record.effective_disposition) }} · {{ record.decision_source === 'manual_review' ? L.review.manualSource : L.review.ruleSource }}</dd>
    </dl>
    <p v-if="reasons.length" class="review-note">{{ reasons.join(' · ') }}<br>{{ record.review_request_reason }}</p>
    <p v-if="record.review_status === 'pending' && (record.effective_disposition === 'retest' || record.review_reasons?.includes('retest_result_required'))" class="review-note">{{ L.review.retestHold }}</p>
    <p v-if="locked">{{ L.review.locked }}</p>
    <p v-if="request">{{ L.review.retryNote }}</p>
    <p v-if="storageWarning" role="status">{{ L.review.storageWarning }}</p>
    <form v-if="!locked || request" @submit.prevent="submit">
      <fieldset :disabled="busy || !!request">
        <label>{{ L.review.reviewer }}<input v-model="reviewer" required maxlength="80" /></label>
        <label>{{ L.review.outcome }}<select v-model="disposition"><option v-for="key in ['quarantine','release','retest','scrap']" :key="key" :value="key">{{ label(key) }}</option></select></label>
        <label v-if="!record.event.destination_facility_id">{{ L.review.destination }}<select v-model="destination"><option value="">—</option><option v-for="node in routes.nodes.filter(n => n.role === 'customer')" :key="node.facility_id" :value="node.facility_id">{{ node.name }}</option></select></label>
        <label class="review-reason">{{ L.review.reason }}<textarea v-model="reason" rows="3" required minlength="3" maxlength="2000" /></label>
      </fieldset>
      <button type="submit" :disabled="busy || decisions.apiUp !== true || (!request && (!reviewer.trim() || reason.trim().length < 3 || (disposition === 'scrap' && !destination)))">{{ busy ? L.review.saving : request ? L.review.retry : L.review.submit }}</button>
      <button v-if="request && !busy" type="button" @click="discard">{{ L.review.discard }}</button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p>
    <ol class="review-history"><li v-for="action in record.review_history || []" :key="action.command_id">{{ action.at }} · {{ action.reviewer }} · {{ label(action.disposition) }}<p>{{ action.reason }}</p></li></ol>
    <div class="audit-exports" v-if="decisions.apiUp === true">
      <a :href="exportUrl('html')">{{ L.review.exportHtml }}</a><a :href="exportUrl('json')">{{ L.review.exportJson }}</a>
    </div>
    <p>{{ L.review.printHelp }}</p><p>{{ L.review.graphScope }}</p>
  </section>
</template>

<style scoped>
.review-panel { border:1px solid #94a3b8; border-radius:10px; padding:14px; margin-bottom:14px; background:#f8fafc; }
h3 { margin:0 0 8px; } p, dl, li { font-size:12px; } dl { display:grid; grid-template-columns:140px 1fr; gap:8px; } dd { margin:0; }
.review-note { background:#fffbeb; padding:8px; color:#92400e; } fieldset { border:0; padding:0; display:flex; flex-wrap:wrap; gap:10px; }
label { display:grid; gap:4px; font-size:12px; } .review-reason { width:100%; } input, select, textarea { min-width:0; max-width:100%; box-sizing:border-box; padding:6px; }
button, .audit-exports a { margin:8px 8px 0 0; padding:6px 9px; border:1px solid #94a3b8; border-radius:5px; font-size:12px; }
.audit-exports { display:flex; flex-wrap:wrap; gap:8px; } .review-history { padding-left:20px; overflow-wrap:anywhere; }
</style>
