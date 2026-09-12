<script setup>
import { computed, ref, watch } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { useSandboxStore } from "../stores/sandbox.js";
import data from "../data/singaporeRoutes.json";
import LeafletMap from "./LeafletMap.vue";
import { locale, bundle } from "../i18n/index.js";
import { postJson } from "../lib/api.js";

const decisions = useDecisionsStore();
const sandbox = useSandboxStore();
const text = computed(() => bundle(locale.value).singapore);
const mode = ref("ortools");
const selectedId = ref(null);
const dispatchFacilityIds = ref(["H-NUH", "H-CGH"]);
const dispatchPlan = ref(null);
const dispatchPending = ref(false);
const dispatchError = ref("");
const canUseLiveRoute = computed(() =>
  decisions.useApi && decisions.apiUp === true &&
  !!sandbox.currentRunId && decisions.decisionFor.reshipment
);
const liveKey = computed(() => sandbox.currentRunId
  ? `${sandbox.currentRunId}|${mode.value}` : null);
const livePlan = computed(() => liveKey.value
  ? decisions.routeResults[liveKey.value] : null);
const isDispatch = computed(() => !!dispatchPlan.value);
const isLive = computed(() => !!livePlan.value && !isDispatch.value);
const plan = computed(() => dispatchPlan.value || (livePlan.value ? {
  routes: livePlan.value.routes,
  geojson: livePlan.value.geojson,
  metrics: {
    total_distance: livePlan.value.total_distance,
    vehicles_used: livePlan.value.vehicles_used,
    served_customers: livePlan.value.served_customers,
    target_customers: livePlan.value.target_customers,
    time_window_violations: livePlan.value.time_window_violations,
    capacity_violations: livePlan.value.capacity_violations,
    depot_return_violations: livePlan.value.depot_return_violations,
    vehicle_limit_violations: livePlan.value.vehicle_limit_violations,
  },
} : data.plans[mode.value]));
const colors = ["#0d9488", "#7c3aed", "#d97706"];
const color = (index) => colors[index % colors.length];
const names = Object.fromEntries(data.nodes.map(n => [n.node_id, n.name]));
const liveGreedy = computed(() => sandbox.currentRunId
  ? decisions.routeResults[`${sandbox.currentRunId}|greedy`] : null);
const baselineDistance = computed(() => isLive.value
  ? liveGreedy.value?.total_distance
  : isDispatch.value ? null : data.plans.greedy.metrics.total_distance);
const saving = computed(() => baselineDistance.value
  ? 100 * (1 - plan.value.metrics.total_distance / baselineDistance.value) : null);
const routePending = computed(() => liveKey.value
  ? decisions.routePending.has(liveKey.value) : false);
const selectableNodes = data.nodes.slice(1, 6);
const mapNodes = computed(() => {
  if (!isDispatch.value && !isLive.value) return data.nodes;
  const ids = new Set([0, ...plan.value.routes.flatMap(route => route.customer_ids)]);
  return data.nodes.filter(node => ids.has(node.node_id));
});

function toggleDispatchFacility(facilityId) {
  dispatchFacilityIds.value = dispatchFacilityIds.value.includes(facilityId)
    ? dispatchFacilityIds.value.filter(id => id !== facilityId)
    : [...dispatchFacilityIds.value, facilityId];
}

async function planDispatch() {
  if (!decisions.useApi || decisions.apiUp !== true || !dispatchFacilityIds.value.length) return;
  dispatchPending.value = true;
  dispatchError.value = "";
  try {
    const selected = data.nodes.filter(node => dispatchFacilityIds.value.includes(node.facility_id));
    const response = await postJson(decisions.apiBase + "/api/dispatch/plan", {
      orders: selected.map((node, index) => ({
        order_id: `DEMO-${index + 1}-${node.facility_id}`,
        product_id: "vaccine_2_8", destination_facility_id: node.facility_id,
        quantity: node.demand, earliest_min: node.earliest_min,
        latest_min: node.latest_min, temperature_zone: "chilled",
      })),
      inventory: [{ lot_id: "DEMO-LOT", product_id: "vaccine_2_8",
        facility_id: "W-KN-PIONEER", available_quantity: 300,
        temperature_zone: "chilled", status: "available" }],
      vehicles: [{ vehicle_id: "SG-CHILL-01", capacity: 200,
        temperature_zone: "chilled", start_facility_id: "W-KN-PIONEER",
        status: "available" }],
      algorithm: mode.value,
    });
    const zone = response.zones[0];
    dispatchPlan.value = {
      routes: zone.routes, geojson: zone.geojson,
      metrics: { total_distance: zone.total_distance,
        vehicles_used: zone.routes.length, served_customers: zone.served_facilities,
        target_customers: zone.target_facilities, time_window_violations: 0,
        capacity_violations: 0, depot_return_violations: 0, vehicle_limit_violations: 0 },
    };
    selectedId.value = null;
  } catch {
    dispatchError.value = text.value.dispatchError;
  } finally {
    dispatchPending.value = false;
  }
}

watch([canUseLiveRoute, mode], () => {
  if (canUseLiveRoute.value) decisions.fetchRoute(sandbox.currentRunId, mode.value);
}, { immediate: true });
watch(canUseLiveRoute, (can) => {
  if (can) {
    decisions.fetchRoute(sandbox.currentRunId, "greedy");
    decisions.fetchRoute(sandbox.currentRunId, "ortools");
  }
}, { immediate: true });
const selected = computed(() => {
  if (selectedId.value === null) return null;
  const node = data.nodes.find(n => n.node_id === selectedId.value);
  for (const route of plan.value.routes) {
    const index = route.stops.findIndex(s => s.node_id === selectedId.value);
    if (index >= 0) return { node, stop: route.stops[index], index: index + 1, vehicle: route.vehicle_id };
  }
  return { node };
});
function clock(minutes) {
  const total = Math.round(minutes);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}
</script>

<template>
  <div class="sg-routing">
    <strong>{{ text.title }}</strong>
    <p class="sg-note">{{ text.note }}</p>
    <section class="dispatch-demo">
      <b>{{ text.dispatchTitle }}</b>
      <p>{{ text.dispatchHelp }}</p>
      <div class="dispatch-sites">
        <label v-for="node in selectableNodes" :key="node.facility_id">
          <input type="checkbox" :checked="dispatchFacilityIds.includes(node.facility_id)"
            @change="toggleDispatchFacility(node.facility_id)" /> {{ node.facility_id.replace(/^H-/, '') }}
        </label>
      </div>
      <button class="dispatch-plan" :disabled="dispatchPending || !dispatchFacilityIds.length || decisions.apiUp !== true"
        @click="planDispatch">{{ dispatchPending ? text.dispatchLoading : text.dispatchPlan }}</button>
      <span v-if="dispatchError" class="dispatch-error">{{ dispatchError }}</span>
    </section>
    <p class="sg-source" :class="{ live: isLive || isDispatch }">
      {{ isDispatch ? text.dispatchRoute : isLive ? text.liveRoute : routePending ? text.loadingRoute : text.demoRoute }}
    </p>
    <div class="route-toggle" role="group" :aria-label="text.title">
      <button v-for="key in ['greedy', 'ortools']" :key="key" :class="{ on: mode === key }"
        :aria-pressed="mode === key" @click="mode = key">{{ text[key] }}</button>
    </div>
    <LeafletMap :nodes="mapNodes" :plan="plan" :selected-id="selectedId" :text="text" @select="selectedId = $event" />
    <div class="sg-metrics">
      <div><b>{{ plan.metrics.total_distance.toFixed(2) }}</b><span>{{ text.distance }} · {{ text.km }}</span></div>
      <div><b>{{ plan.metrics.vehicles_used }}</b><span>{{ text.vehicles }}</span></div>
      <div><b>{{ plan.metrics.served_customers ?? "—" }}<template v-if="plan.metrics.served_customers != null">/{{ plan.metrics.target_customers ?? data.nodes.length - 1 }}</template></b><span>{{ text.served }}</span></div>
      <div><b>{{ plan.metrics.time_window_violations == null ? "—" : plan.metrics.time_window_violations + plan.metrics.capacity_violations + plan.metrics.depot_return_violations + plan.metrics.vehicle_limit_violations }}</b><span>{{ text.violations }}</span></div>
    </div>
    <p v-if="mode === 'ortools' && saving != null" class="sg-saving">{{ text.savings }} {{ saving.toFixed(2) }}%</p>
    <div v-for="(route, index) in plan.routes" :key="route.vehicle_id" class="sg-vehicle">
      <b :style="{ color: color(index) }">● {{ text.vehicle }} {{ route.vehicle_id }}</b>
      <span>{{ route.total_distance.toFixed(2) }} {{ text.km }}</span>
      <div class="sg-stops">
        <button :class="{ selected: selectedId === 0 }" @click="selectedId = 0">{{ text.depot }}</button>
        <button v-for="(id, i) in route.customer_ids" :key="id" :title="names[id]" :aria-label="`${text.stop} ${i + 1}: ${names[id]}`"
          :class="{ selected: selectedId === id }" @click="selectedId = id">{{ i + 1 }} · {{ data.nodes[id].facility_id.replace(/^H-/, '') }}</button>
        <span>→ {{ text.depot }}</span>
      </div>
    </div>
    <div class="sg-detail" aria-live="polite">
      <template v-if="selected">
        <b>{{ selected.node.name }}</b>
        <template v-if="selected.stop">
          <div>{{ text.vehicle }} {{ selected.vehicle }} · {{ text.stop }} {{ selected.index }}</div>
          <div>{{ text.arrival }} {{ clock(selected.stop.arrival) }} · {{ text.service }} {{ clock(selected.stop.service_start) }}</div>
          <div>{{ text.demand }} {{ selected.node.demand }} {{ text.units }} · {{ text.window }} {{ clock(selected.node.earliest_min) }}–{{ clock(selected.node.latest_min) }}</div>
        </template>
        <div v-else>{{ text.noStop }} · {{ clock(selected.node.earliest_min) }}–{{ clock(selected.node.latest_min) }}</div>
      </template>
      <span v-else>{{ text.select }}</span>
    </div>
    <p class="sg-note">{{ isDispatch ? text.dispatchActive : isLive ? text.activeLive : decisions.decisionFor.reshipment ? text.active : text.idle }}</p>
    <p class="sg-disclaimer">{{ text.assumption }}</p>
  </div>
</template>

<style scoped>
.sg-routing { min-width: 0; font-size: 12px; }
.sg-note { color: #64748b; line-height: 1.5; margin: 7px 0 10px; }
.sg-source { display: inline-block; margin: 0 0 9px; padding: 3px 7px; border-radius: 999px; background: #f1f5f9; color: #64748b; font-weight: 700; }
.sg-source.live { background: #ccfbf1; color: #0f766e; }
.dispatch-demo { margin: 8px 0; padding: 10px; border: 1px solid #99f6e4; border-radius: 8px; background: #f0fdfa; }
.dispatch-demo p { margin: 4px 0 7px; color: #475569; }
.dispatch-sites { display: flex; flex-wrap: wrap; gap: 5px 10px; }
.dispatch-sites label { cursor: pointer; }
.dispatch-plan { margin-top: 8px; padding: 6px 9px; border: 0; border-radius: 6px; background: #0f766e; color: white; cursor: pointer; }
.dispatch-plan:disabled { opacity: .45; cursor: not-allowed; }
.dispatch-error { margin-left: 8px; color: #b91c1c; }
.sg-metrics { display: grid; grid-template-columns: repeat(2, 1fr); gap: 7px; margin-top: 10px; }
.sg-metrics > div { padding: 8px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; }
.sg-metrics b { display: block; font-size: 18px; color: #0f172a; }
.sg-metrics span { color: #64748b; font-size: 11px; }
.sg-saving { color: #0f766e; font-weight: 600; }
.sg-vehicle { border-top: 1px solid #e2e8f0; padding: 10px 0; }
.sg-vehicle > span { float: right; color: #64748b; }
.sg-stops { display: flex; gap: 5px; flex-wrap: wrap; align-items: center; margin-top: 7px; }
.sg-stops button { border: 1px solid #cbd5e1; background: white; padding: 4px 6px; border-radius: 5px; color: #475569; cursor: pointer; font-size: 10px; }
.sg-stops button.selected { color: #0f766e; border-color: #0d9488; background: #f0fdfa; }
.sg-detail { background: #f8fafc; border-radius: 8px; padding: 10px; line-height: 1.7; color: #475569; }
.sg-detail b { color: #0f172a; overflow-wrap: anywhere; }
.sg-disclaimer { margin-bottom: 0; padding-top: 9px; border-top: 1px solid #e2e8f0; color: #64748b; font-size: 11px; line-height: 1.6; }
</style>
