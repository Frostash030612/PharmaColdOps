<script setup>
import { computed, onMounted, watch } from "vue";
import { useDispatchStore } from "../stores/dispatch.js";
import { locale, bundle } from "../i18n/index.js";
import { dispatchReasonText } from "../lib/dispatchReasons.js";
import routes from "../data/singaporeRoutes.json";
const dispatch = useDispatchStore();
const L = computed(() => bundle(locale.value));
const active = computed(() => ["accepted", "in_transit"].includes(dispatch.run?.status));
const paired = computed(() => dispatch.run?.input?.constraints?.routing_model === "pickup_delivery");
const names = Object.fromEntries(routes.nodes.map((n) => [n.facility_id, n.name]));
const byNode = Object.fromEntries(routes.nodes.map((n) => [n.node_id, n.name]));
const clock = (min) => min == null ? "—" : `${String(Math.floor(min / 60) % 24).padStart(2, "0")}:${String(Math.round(min % 60)).padStart(2, "0")}`;
const kind = (value) => L.value.singapore[{
  spare_vehicle: "branchKindSpare", add_stop_in_transit: "branchKindAddStop", return_to_depot: "branchKindReturn", load_before_departure: "branchKindLoadFirst",
}[value]] || value;
const reason = (entry) => dispatchReasonText(entry, L.value.singapore, clock);
onMounted(dispatch.loadUrgentOptions);
watch(() => dispatch.urgentForm.product_id, (pid) => {
  const sources = dispatch.urgentOptions?.warehouses || [];
  if (!sources.find((s) => s.facility_id === dispatch.urgentForm.origin_facility_id)?.product_ids.includes(pid)) {
    const eligible = sources.find((s) => s.product_ids.includes(pid));
    if (eligible) dispatch.urgentForm.origin_facility_id = eligible.facility_id;
  }
});
</script>

<template>
  <section class="urgent-panel">
    <h3>{{ L.urgent.title }}</h3>
    <p class="sg-note">{{ L.urgent.demo }}</p>
    <p v-if="!active" class="sg-note">{{ L.urgent.needsRun }}</p>
    <p v-else-if="paired" class="sg-error">{{ L.urgent.paired }}</p>
    <p v-if="dispatch.run">{{ L.urgent.day }}: {{ dispatch.run.operating_date }} · {{ dispatch.run.dispatch_id }}</p>
    <form @submit.prevent="dispatch.previewUrgent()">
      <fieldset :disabled="!active || paired || dispatch.pending || !dispatch.urgentOptions">
        <div class="urgent-fields">
          <label>{{ L.center.product }}<select v-model="dispatch.urgentForm.product_id" required><option v-for="product in dispatch.urgentOptions?.products || []" :key="product.product_id" :value="product.product_id">{{ L.products[product.product_id] || product.name_en }}</option></select></label>
          <label>{{ L.urgent.origin }}<select v-model="dispatch.urgentForm.origin_facility_id" required><option v-for="warehouse in dispatch.urgentOptions?.warehouses || []" :key="warehouse.facility_id" :value="warehouse.facility_id" :disabled="!warehouse.product_ids.includes(dispatch.urgentForm.product_id)">{{ warehouse.name }}{{ warehouse.product_ids.includes(dispatch.urgentForm.product_id) ? '' : ` · ${L.urgent.unavailableSource}` }}</option></select></label>
          <label>{{ L.workflow.hospital }}<select v-model="dispatch.urgentForm.destination_facility_id" required><option v-for="destination in dispatch.urgentOptions?.destinations || []" :key="destination.facility_id" :value="destination.facility_id">{{ destination.name }}</option></select></label>
          <label>{{ L.urgent.latest }}<input v-model="dispatch.urgentForm.latest_time" type="time" required /></label>
          <label>{{ L.urgent.earliest }}<input v-model="dispatch.urgentForm.earliest_time" type="time" /></label>
          <label>{{ L.singapore.branchPolicy }}<select v-model="dispatch.urgentForm.policy"><option value="minimize_disruption">{{ L.singapore.policyDisruption }}</option><option value="minimize_vehicles">{{ L.singapore.policyVehicles }}</option></select></label>
        </div>
        <button type="submit" class="sg-primary">{{ dispatch.pending ? L.urgent.loading : L.urgent.preview }}</button>
      </fieldset>
    </form>
    <p v-if="dispatch.urgentError" class="sg-error" role="status">{{ dispatch.urgentError }}</p>
    <p v-if="dispatch.urgentSuccess" class="urgent-success" role="status">{{ L.urgent.success }} · {{ dispatch.urgentSuccess }}</p>
    <template v-if="dispatch.urgent">
      <p v-if="!dispatch.urgentInputsCurrent" class="sg-error">{{ L.urgent.changed }}</p>
      <p v-if="!dispatch.urgent.candidates.length" class="sg-error">{{ L.urgent.none }} · {{ dispatch.urgent.reason || '—' }}</p>
      <div v-else class="urgent-table-wrap">
        <table class="htable urgent-options">
          <thead><tr><th>{{ L.workflow.option }}</th><th>{{ L.workflow.distance }}</th><th>{{ L.workflow.arrival }}</th><th>{{ L.workflow.impact }}</th><th>{{ L.urgent.terminal }}</th></tr></thead>
          <tbody><tr v-for="(candidate, index) in dispatch.urgent.candidates" :key="`${candidate.kind}-${candidate.vehicle_id}`" :class="{ chosen: dispatch.urgentPicked === index }">
            <td><label><input v-model="dispatch.urgentPicked" type="radio" :value="index" name="urgent-candidate" :disabled="dispatch.pending || !dispatch.urgentInputsCurrent" />{{ kind(candidate.kind) }} · {{ candidate.vehicle_id }}</label></td>
            <td>{{ (candidate.added_distance_m / 1000).toFixed(2) }} km</td>
            <td>{{ clock(candidate.eta_min) }}</td>
            <td>{{ candidate.affected_orders.length }} · {{ Math.max(0, ...candidate.affected_orders.map((o) => o.delay_min || 0)).toFixed(1) }} min
              <span v-for="entry in candidate.blocked_by" :key="entry.code" class="sg-error">{{ reason(entry) }}</span></td>
            <td>{{ byNode[candidate.end_node_id] || '—' }}</td>
          </tr></tbody>
        </table>
      </div>
      <button v-if="dispatch.urgent.candidates.length" :disabled="dispatch.pending || !dispatch.urgentInputsCurrent || !dispatch.urgentCandidate?.feasible" @click="dispatch.acceptUrgent()">{{ L.urgent.accept }}</button>
    </template>
  </section>
</template>

<style scoped>
.urgent-panel { border: 1px solid #fed7aa; background: #fff7ed; border-radius: 10px; padding: 12px; margin: 12px 0; }
.urgent-panel h3 { margin: 0 0 8px; }
.urgent-panel fieldset { padding: 0; border: none; }
.urgent-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.urgent-fields label { display: grid; gap: 4px; min-width: 0; font-size: 12px; }
.urgent-fields input, .urgent-fields select { width: 100%; min-width: 0; box-sizing: border-box; }
.urgent-table-wrap { overflow-x: auto; }
.urgent-options { min-width: 750px; }
.urgent-options td { font-size: 11px; }
.chosen { background: #ffedd5; }
.urgent-success { color: #15803d; }
@media (max-width: 520px) { .urgent-fields { grid-template-columns: 1fr; } }
</style>
