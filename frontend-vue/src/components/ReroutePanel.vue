<script setup>
/* Delivery panel — ONE operation, not two stories.

   In API mode the map and every number below it come from the live dispatch
   state (orders, reserved stock, vehicle queues). Offline, or before anything
   has been dispatched, it falls back to the committed Singapore demo plan and
   says so, so a fixed sample is never mistaken for a live operation. */
import { computed, ref, watch, onBeforeUnmount } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { useSandboxStore } from "../stores/sandbox.js";
import { useDispatchStore } from "../stores/dispatch.js";
import { useHistoryStore } from "../stores/history.js";
import { eventPayload, overridePayload, postJson } from "../lib/api.js";
import data from "../data/singaporeRoutes.json";
import LeafletMap from "./LeafletMap.vue";
import { locale, bundle } from "../i18n/index.js";

const decisions = useDecisionsStore();
const sandbox = useSandboxStore();
const dispatch = useDispatchStore();
const history = useHistoryStore();
const busy = ref(false);
const text = computed(() => bundle(locale.value).singapore);
const mode = ref("ortools");
const selectedId = ref(null);

const isLive = computed(() => !!dispatch.live);
const nodes = data.nodes;                       // facility names/coords: same ids either way
const names = Object.fromEntries(nodes.map((n) => [n.node_id, n.name]));

/* The plan the map draws: live operation when there is one, else the demo. */
const plan = computed(() => dispatch.live || data.plans[mode.value]);

/* The current decision needs a resupply and the backend can act on it. */
const needsReshipment = computed(() => decisions.decisionFor.reshipment);
const online = computed(() => decisions.useApi && decisions.apiUp === true);

const thisCaseOrderId = computed(() =>
  sandbox.currentRunId ? `RO-${sandbox.currentRunId}` : null);
const alreadyCommitted = computed(() =>
  !!thisCaseOrderId.value &&
  dispatch.orders.some((o) => o.order_id === thisCaseOrderId.value));

/* Two ways in, so the action is never hidden behind another panel:
   - an unarchived sandbox decision closes the case first, then dispatches;
   - an already-archived case (restored from history) just dispatches. */
const canDispatchArchived = computed(() =>
  online.value && needsReshipment.value && !!sandbox.currentRunId && !alreadyCommitted.value);
const canCloseAndDispatch = computed(() =>
  online.value && needsReshipment.value && !sandbox.currentRunId);

async function closeAndDispatch() {
  if (busy.value) return;
  busy.value = true;
  try {
    const record = await postJson(decisions.apiBase + "/api/case_close", {
      ...eventPayload(sandbox.current),
      spec_override: overridePayload(sandbox.spec),
      started_at: new Date().toISOString(),
    });
    sandbox.restoreCase(record);     // the page now shows an archived case
    history.refresh();
    await dispatch.commitReshipment(record.run_id);
  } catch (e) {
    dispatch.error = String(e.message || e);
  } finally {
    busy.value = false;
  }
}

const SPEEDS = [
  { value: 1, key: "speedReal" },
  { value: 60, key: "speedFast" },
  { value: 300, key: "speedFaster" },
];
const speed = computed(() => dispatch.run?.clock?.speed || 60);
const selectedVehicle = ref(null);
function pickVehicle(id) {
  selectedVehicle.value = selectedVehicle.value === id ? null : id;
}
const underway = computed(() => dispatch.run?.status === "in_transit");
const canDepart = computed(() =>
  dispatch.vehicles.some((v) => v.status === "reserved"));

/* Keep the trucks moving while an operation is under way. */
watch(underway, (on) => { on ? dispatch.watchClock() : dispatch.stopClock(); },
      { immediate: true });
onBeforeUnmount(() => dispatch.stopClock());

function simClock() {
  const minutes = dispatch.live?.sim_now_min;
  if (minutes == null) return "";
  return clock(((minutes % 1440) + 1440) % 1440);
}

/* Load the shared operation whenever the backend becomes reachable. */
watch(() => [decisions.useApi, decisions.apiUp], () => { dispatch.refresh(); },
      { immediate: true });

const colors = ["#0d9488", "#7c3aed", "#d97706"];
const color = (index) => colors[index % colors.length];

const selected = computed(() => {
  if (selectedId.value === null) return null;
  const node = nodes.find((n) => n.node_id === selectedId.value);
  for (const route of plan.value.routes) {
    const index = route.stops.findIndex((s) => s.node_id === selectedId.value);
    if (index >= 0) {
      return { node, stop: route.stops[index], index: index + 1,
               vehicle: route.vehicle_id };
    }
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
    <p class="sg-source" :class="{ live: isLive }">
      {{ isLive ? text.liveOperation : text.demoRoute }}
    </p>

    <!-- Algorithm choice only means something for the committed demo plan;
         a live operation's routes are the ones actually assigned. -->
    <div v-if="!isLive" class="route-toggle" role="group" :aria-label="text.title">
      <button v-for="key in ['greedy', 'ortools']" :key="key" :class="{ on: mode === key }"
        :aria-pressed="mode === key" @click="mode = key">{{ text[key] }}</button>
    </div>

    <LeafletMap :nodes="nodes" :plan="plan" :selected-id="selectedId" :text="text"
      :selected-vehicle="selectedVehicle"
      @select="selectedId = $event" @select-vehicle="pickVehicle($event)" />

    <div v-if="isLive" class="sg-metrics">
      <div><b>{{ dispatch.run.status }}</b><span>{{ text.dispatchStatus }}</span></div>
      <div><b>{{ dispatch.live.metrics.orders_delivered }}/{{ dispatch.live.metrics.orders_total }}</b><span>{{ text.ordersDelivered }}</span></div>
      <div><b>{{ dispatch.live.metrics.vehicles_used }}</b><span>{{ text.vehicles }}</span></div>
      <div><b>{{ dispatch.live.metrics.stock_remaining }}</b><span>{{ text.stockLeft }}</span></div>
    </div>
    <div v-else class="sg-metrics">
      <div><b>{{ plan.metrics.total_distance.toFixed(2) }}</b><span>{{ text.distance }} · {{ text.km }}</span></div>
      <div><b>{{ plan.metrics.vehicles_used }}</b><span>{{ text.vehicles }}</span></div>
      <div><b>{{ plan.metrics.served_customers }}/{{ nodes.length - 1 }}</b><span>{{ text.served }}</span></div>
      <div><b>{{ plan.metrics.time_window_violations + plan.metrics.capacity_violations + plan.metrics.depot_return_violations + plan.metrics.vehicle_limit_violations }}</b><span>{{ text.violations }}</span></div>
    </div>

    <!-- The bridge: this case's resupply joins the same operation, checked
         against real stock and real vehicle capacity. Always says what the
         next action is (or why there is none) — a decision that needs a
         resupply must never dead-end in a banner. -->
    <div class="sg-commit">
      <button v-if="canCloseAndDispatch" :disabled="busy || dispatch.pending"
        @click="closeAndDispatch()">
        {{ (busy || dispatch.pending) ? text.committing : text.closeAndDispatch }}
      </button>
      <button v-else-if="canDispatchArchived" :disabled="dispatch.pending"
        @click="dispatch.commitReshipment(sandbox.currentRunId)">
        {{ dispatch.pending ? text.committing : text.commitReshipment }}
      </button>
      <span v-else-if="alreadyCommitted" class="done">{{ text.committed }}</span>
      <span v-else-if="needsReshipment && !online" class="hint">{{ text.needsApi }}</span>
      <span v-else class="hint">{{ text.noReshipment }}</span>
    </div>
    <p v-if="dispatch.error" class="sg-error" role="status">{{ dispatch.error }}</p>

    <!-- Operating the run: depart, then the simulated clock drives arrivals. -->
    <div v-if="isLive" class="sg-ops">
      <button v-if="canDepart" :disabled="dispatch.pending" @click="dispatch.depart()">
        {{ text.depart }}
      </button>
      <template v-if="dispatch.run?.clock">
        <span class="sim">{{ text.simClock }} {{ simClock() }}</span>
        <span class="speeds">
          <button v-for="s in SPEEDS" :key="s.value" :class="{ on: speed === s.value }"
            @click="dispatch.setSpeed(s.value)">{{ text[s.key] }}</button>
        </span>
      </template>
    </div>

    <div v-for="(route, index) in plan.routes" :key="route.vehicle_id" class="sg-vehicle"
      :class="{ picked: selectedVehicle === route.vehicle_id }">
      <b :style="{ color: color(index) }" class="veh-name" role="button" tabindex="0"
        @click="pickVehicle(route.vehicle_id)" @keydown.enter="pickVehicle(route.vehicle_id)">
        ● {{ text.vehicle }} {{ route.vehicle_id }}
        <em v-if="route.track">· {{ route.track.reached_stops }}/{{ route.customer_ids.length }}</em>
      </b>
      <span v-if="route.total_distance != null">{{ route.total_distance.toFixed(2) }} {{ text.km }}</span>
      <div class="sg-stops">
        <button :class="{ selected: selectedId === 0 }" @click="selectedId = 0">{{ text.depot }}</button>
        <button v-for="(id, i) in route.customer_ids" :key="`${route.vehicle_id}-${id}-${i}`"
          :title="names[id]" :aria-label="`${text.stop} ${i + 1}: ${names[id]}`"
          :class="{ selected: selectedId === id, done: route.stops[i]?.delivered,
                    mine: route.stops[i]?.order_id === thisCaseOrderId }"
          @click="selectedId = id">{{ i + 1 }} · {{ nodes[id].facility_id.replace(/^H-/, '') }}</button>
        <span>→ {{ text.depot }}</span>
      </div>
    </div>

    <div class="sg-detail" aria-live="polite">
      <template v-if="selected">
        <b>{{ selected.node.name }}</b>
        <template v-if="selected.stop">
          <div>{{ text.vehicle }} {{ selected.vehicle }} · {{ text.stop }} {{ selected.index }}</div>
          <!-- A live stop knows its order and window; a demo stop knows its schedule. -->
          <div v-if="selected.stop.order_id">
            {{ selected.stop.order_id }}<template v-if="selected.stop.source_run_id"> · {{ text.fromCase }} {{ selected.stop.source_run_id }}</template>
          </div>
          <div v-if="selected.stop.arrival != null">
            {{ text.arrival }} {{ clock(selected.stop.arrival) }} · {{ text.service }} {{ clock(selected.stop.service_start) }}
          </div>
          <div>{{ text.demand }} {{ selected.stop.quantity ?? selected.node.demand }} {{ text.units }} ·
            {{ text.window }} {{ clock(selected.stop.earliest_min ?? selected.node.earliest_min) }}–{{ clock(selected.stop.latest_min ?? selected.node.latest_min) }}</div>
        </template>
        <div v-else>{{ text.noStop }} · {{ clock(selected.node.earliest_min) }}–{{ clock(selected.node.latest_min) }}</div>
      </template>
      <span v-else>{{ text.select }}</span>
    </div>

    <p class="sg-disclaimer">{{ text.assumption }}</p>
  </div>
</template>

<style scoped>
.sg-routing { min-width: 0; font-size: 12px; }
.sg-note { color: #64748b; line-height: 1.5; margin: 7px 0 10px; }
.sg-source { display: inline-block; margin: 0 0 9px; padding: 3px 7px; border-radius: 999px; background: #f1f5f9; color: #64748b; font-weight: 700; }
.sg-source.live { background: #ccfbf1; color: #0f766e; }
.sg-metrics { display: grid; grid-template-columns: repeat(2, 1fr); gap: 7px; margin-top: 10px; }
.sg-metrics > div { padding: 8px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; }
.sg-metrics b { display: block; font-size: 18px; color: #0f172a; }
.sg-metrics span { color: #64748b; font-size: 11px; }
.sg-commit { margin-top: 10px; }
.sg-commit button { background: #0d9488; color: #fff; border: 1px solid #0d9488; border-radius: 7px; padding: 7px 11px; cursor: pointer; font-size: 12px; font-weight: 600; }
.sg-commit button:disabled { opacity: .6; cursor: default; }
.sg-commit .done { color: #0f766e; font-weight: 600; }
.sg-commit .hint { color: #64748b; }
.sg-stops button.mine { border-color: #0d9488; box-shadow: 0 0 0 2px rgba(13,148,136,.18); }
.sg-error { color: #b91c1c; line-height: 1.5; }
.sg-ops { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 10px 0 4px; }
.sg-ops > button { background: #0f172a; color: #fff; border: 0; border-radius: 7px; padding: 6px 11px; cursor: pointer; font-size: 12px; font-weight: 600; }
.sg-ops .sim { font-variant-numeric: tabular-nums; color: #0f766e; font-weight: 700; }
.sg-ops .speeds button { border: 1px solid #cbd5e1; background: #fff; color: #475569; border-radius: 5px; padding: 3px 7px; font-size: 10px; cursor: pointer; }
.sg-ops .speeds button.on { border-color: #0d9488; color: #0f766e; background: #f0fdfa; }
.sg-vehicle { border-top: 1px solid #e2e8f0; padding: 10px 0; }
.sg-vehicle.picked { background: #f0fdfa; }
.sg-vehicle .veh-name { cursor: pointer; }
.sg-vehicle .veh-name em { font-style: normal; color: #64748b; font-weight: 500; }
.sg-vehicle > span { float: right; color: #64748b; }
.sg-stops { display: flex; gap: 5px; flex-wrap: wrap; align-items: center; margin-top: 7px; }
.sg-stops button { border: 1px solid #cbd5e1; background: white; padding: 4px 6px; border-radius: 5px; color: #475569; cursor: pointer; font-size: 10px; }
.sg-stops button.selected { color: #0f766e; border-color: #0d9488; background: #f0fdfa; }
.sg-stops button.done { text-decoration: line-through; opacity: .65; }
.sg-detail { background: #f8fafc; border-radius: 8px; padding: 10px; line-height: 1.7; color: #475569; }
.sg-detail b { color: #0f172a; overflow-wrap: anywhere; }
.sg-disclaimer { margin-bottom: 0; padding-top: 9px; border-top: 1px solid #e2e8f0; color: #64748b; font-size: 11px; line-height: 1.6; }
</style>
