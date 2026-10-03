<script setup>
import { computed, ref, watch } from "vue";
import { useHistoryStore } from "../stores/history.js";
import { useDispatchStore } from "../stores/dispatch.js";
import { locale, bundle } from "../i18n/index.js";
import { STATUS_COLORS } from "../lib/incidentWorkflow.js";
import { dispatchReasonText } from "../lib/dispatchReasons.js";
import routes from "../data/singaporeRoutes.json";

const history = useHistoryStore();
const dispatch = useDispatchStore();
const L = computed(() => bundle(locale.value));
const record = computed(() => history.currentRun);
const status = computed(() => record.value ? history.statusOf(record.value) : "pending");
const reship = computed(() => record.value?.effective_reshipment_required ?? record.value?.reshipment_required);
const awaitingReview = computed(() => record.value?.review_status === 'pending');
const preview = computed(() => dispatch.branch?.run_id === record.value?.run_id ? dispatch.branch : null);
const note = ref("");
const policy = ref("minimize_disruption");
const names = Object.fromEntries(routes.nodes.map((n) => [n.facility_id, n.name]));
const name = (id) => names[id] || id || L.value.workflow.unknownLocation;
const clock = (min) => min == null ? "—" : `${String(Math.floor(min / 60) % 24).padStart(2, "0")}:${String(Math.round(min % 60)).padStart(2, "0")}`;
const kind = (value) => L.value.singapore[{
  spare_vehicle: "branchKindSpare", add_stop_in_transit: "branchKindAddStop",
  return_to_depot: "branchKindReturn", load_before_departure: "branchKindLoadFirst",
}[value]] || value;
const reason = (entry) => dispatchReasonText(entry, L.value.singapore, clock);
watch(() => record.value?.run_id, () => { note.value = ""; history.workflowError = ""; });
function compare() { return dispatch.previewBranch(record.value.run_id, policy.value, { inline: true }); }
async function choose(candidate) {
  const id = record.value.run_id;
  const result = await dispatch.commitReshipment(id, {
    candidate_kind: candidate.kind, vehicle_id: candidate.vehicle_id,
  });
  if (result) await history.refresh();
}
</script>

<template>
  <section v-if="record" class="case-actions">
    <h3>{{ L.workflow.title }}</h3>
    <p><span class="workflow-badge" :style="{ background: STATUS_COLORS[status] }">{{ L.workflow[status] }}</span></p>
    <dl class="workflow-details">
      <dt>{{ L.workflow.orderLink }}</dt><dd>{{ record.event.dispatch_id || record.handling_dispatch_id || L.workflow.unlinked }} · {{ record.event.order_id || '—' }}</dd>
      <dt>{{ L.workflow.location }}</dt><dd>{{ name(record.event.facility_id) }}</dd>
      <dt>{{ L.center.destination }}</dt><dd>{{ name(record.effective_destination_facility_id || record.event.destination_facility_id) }}</dd>
      <template v-if="record.linked_order">
        <dt>{{ L.workflow.quantityWindow }}</dt><dd>{{ record.linked_order.quantity_is_nominal ? L.urgent.nominal : record.linked_order.quantity }} · {{ clock(record.linked_order.earliest_min) }}–{{ clock(record.linked_order.latest_min) }}</dd>
      </template>
    </dl>
    <div class="workflow-controls">
      <button v-if="status === 'pending'" :disabled="history.workflowPending || awaitingReview" @click="history.changeStatus(record, 'processing', note)">{{ L.workflow.begin }}</button>
      <label v-if="reship && !['handled', 'closed'].includes(status)">
        {{ L.singapore.branchPolicy }}
        <select v-model="policy" :disabled="dispatch.pending">
          <option value="minimize_disruption">{{ L.singapore.policyDisruption }}</option>
          <option value="minimize_vehicles">{{ L.singapore.policyVehicles }}</option>
        </select>
      </label>
      <button v-if="reship && !['handled', 'closed'].includes(status)" :disabled="dispatch.pending || awaitingReview" @click="compare">{{ L.workflow.compare }}</button>
    </div>
    <p v-if="dispatch.branchError || dispatch.error" class="sg-error" role="status">{{ dispatch.branchError || dispatch.error }}</p>
    <template v-if="preview">
      <p v-if="preview.already_committed">{{ L.workflow.awaitDelivery }}</p>
      <p v-else-if="!preview.candidates?.length" class="sg-error">{{ L.workflow.noCandidates }} · {{ preview.reason || '—' }}</p>
      <div class="workflow-table-wrap" v-else>
        <table class="htable workflow-options">
          <thead><tr><th>{{ L.workflow.option }}</th><th>{{ L.workflow.distance }}</th><th>{{ L.workflow.arrival }}</th><th>{{ L.workflow.impact }}</th><th>{{ L.workflow.apply }}</th></tr></thead>
          <tbody><tr v-for="candidate in preview.candidates" :key="`${candidate.kind}-${candidate.vehicle_id}`">
            <td>{{ kind(candidate.kind) }}<br>{{ candidate.vehicle_id }}</td>
            <td>{{ (candidate.added_distance_m / 1000).toFixed(2) }} km</td>
            <td>{{ clock(candidate.eta_min) }}</td>
            <td>{{ candidate.affected_orders?.length || 0 }} · {{ Math.max(0, ...(candidate.affected_orders || []).map((o) => o.delay_min || 0)).toFixed(1) }} min
              <span v-for="entry in candidate.blocked_by || []" :key="entry.code">{{ reason(entry) }}</span>
            </td>
            <td><button :disabled="dispatch.pending || candidate.feasible === false" @click="choose(candidate)">{{ L.workflow.apply }}</button></td>
          </tr></tbody>
        </table>
      </div>
    </template>
    <p v-if="reship && status === 'processing'">{{ L.workflow.awaitDelivery }}</p>
    <label v-if="status !== 'closed'" class="workflow-note">{{ L.workflow.note }}<textarea v-model="note" rows="2" /></label>
    <button v-if="!reship && ['pending', 'processing'].includes(status)" :disabled="history.workflowPending || awaitingReview || !note.trim()" @click="history.changeStatus(record, 'handled', note)">{{ L.workflow.markHandled }}</button>
    <button v-if="status === 'handled'" :disabled="history.workflowPending || !note.trim()" @click="history.changeStatus(record, 'closed', note)">{{ L.workflow.close }}</button>
    <p v-if="history.workflowError" class="sg-error" role="status">{{ history.workflowError }}</p>
    <ul v-if="record.workflow_history?.length"><li v-for="(action, index) in record.workflow_history" :key="index">{{ L.workflow[action.status] }} · {{ action.at }} · {{ action.remark }}</li></ul>
  </section>
</template>

<style scoped>
.case-actions { border: 1px solid #cbd5e1; border-radius: 10px; padding: 14px; margin-bottom: 18px; background: #f8fafc; }
.case-actions h3 { margin-top: 0; }
.workflow-badge { color: white; border-radius: 12px; padding: 4px 10px; }
.workflow-details { display: grid; grid-template-columns: minmax(100px, 1fr) 3fr; gap: 8px; overflow-wrap: anywhere; }
.workflow-details dd { margin: 0; }
.workflow-controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.workflow-table-wrap { overflow-x: auto; }
.workflow-options { min-width: 520px; }
.workflow-note { display: grid; gap: 5px; margin: 12px 0; }
.workflow-note textarea { width: 100%; box-sizing: border-box; }
</style>
