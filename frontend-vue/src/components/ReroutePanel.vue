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
import { useOverlayStore } from "../stores/overlay.js";
import { eventPayload, overridePayload, postJson } from "../lib/api.js";
import data from "../data/singaporeRoutes.json";
import LeafletMap from "./LeafletMap.vue";
import TransportView from "./TransportView.vue";
import { locale, bundle } from "../i18n/index.js";
import { DISPO_COLOR } from "../data/products.js";
import { interp } from "../lib/format.js";

const props = defineProps({ primary: { type: Boolean, default: false } });

const decisions = useDecisionsStore();
const sandbox = useSandboxStore();
const dispatch = useDispatchStore();
const history = useHistoryStore();
const overlay = useOverlayStore();
const busy = ref(false);
const text = computed(() => bundle(locale.value).singapore);
const mode = ref("ortools");
const selectedId = ref(null);
const transportOpen = ref(false);

const isLive = computed(() => !!dispatch.live);
const nodes = data.nodes;                       // facility names/coords: same ids either way
const names = Object.fromEntries(nodes.map((n) => [n.node_id, n.name]));
const nodeByFacility = Object.fromEntries(nodes.map((n) => [n.facility_id, n.node_id]));

const incidentEvents = computed(() => history.runs.flatMap((run) => {
  const facilityId = run.event?.destination_facility_id;
  const nodeId = nodeByFacility[facilityId];
  if (nodeId == null) return [];
  return [{
    id: run.run_id,
    nodeId,
    color: DISPO_COLOR[run.disposition] || "#dc2626",
    label: `${run.run_id} · ${names[nodeId]}`,
  }];
}));

function openIncident(runId) {
  const record = history.runs.find((run) => run.run_id === runId);
  if (!record) return;
  sandbox.restoreCase(record);
  selectedId.value = nodeByFacility[record.event?.destination_facility_id] ?? null;
  overlay.openCase();
}

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
    // Show HOW it could be handled instead of silently picking for the operator:
    // this is the moment the branch event becomes visible on the map (the
    // affected hospital and the stop it would add), and committing is then a
    // deliberate choice. "把本次补发纳入配送作业" stays as the one-press default.
    await dispatch.previewBranch(record.run_id);
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
  dispatch.branchVehicle = selectedVehicle.value;
}
const underway = computed(() => dispatch.run?.status === "in_transit");
/* Keep polling while anything is still on the road, which includes the drive
   home after the last delivery (the run is already "completed" by then). */
const moving = computed(() => underway.value || dispatch.stillReturning);
const canDepart = computed(() =>
  dispatch.vehicles.some((v) => v.status === "reserved"));

/* Keep the trucks moving while an operation is under way. */
watch(moving, (on) => { on ? dispatch.watchClock() : dispatch.stopClock(); },
      { immediate: true });
onBeforeUnmount(() => dispatch.stopClock());

/* …and stop the clock while the tab is in the background: a demo left open
   would otherwise be over before anyone came back to it. */
dispatch.watchVisibility();

function simClock() {
  const minutes = dispatch.live?.sim_now_min;
  if (minutes == null) return "";
  return clock(((minutes % 1440) + 1440) % 1440);
}

/* Load the shared operation whenever the backend becomes reachable, and the
   recent-operation list with it: after a run finishes nothing is "active" any
   more, and the console offers to replay what just happened. */
watch(() => [decisions.useApi, decisions.apiUp], () => {
  dispatch.refresh();
  dispatch.loadRecent();
}, { immediate: true });

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

/* Which way of serving the branch event this row is. The backend names the
   kinds; the wording is local, like every other decision in this app. */
const KIND_LABELS = {
  add_stop_in_transit: "branchKindAddStop",
  load_before_departure: "branchKindLoadFirst",
  return_to_depot: "branchKindReturn",
  spare_vehicle: "branchKindSpare",
};
function kindLabel(kind) {
  return text.value[KIND_LABELS[kind]] || kind;
}
const dailyConstraintText = computed(() => {
  const c = dispatch.dailyBatch?.plan?.constraints;
  if (!c?.max_vehicles || !c?.max_stops_per_vehicle) return "";
  return interp(text.value.dailyConstraints, {
    vehicles: c.max_vehicles, stops: c.max_stops_per_vehicle,
  });
});

/* Parking nodes: everything in the network that is not a receiving site.
   Warehouses and distribution points are what a truck may finish at — that set
   is exactly what turns the route open (no drive home). */
const terminalOptions = computed(() =>
  nodes.filter((n) => n.role !== "customer")
    .map((n) => ({ facility_id: n.facility_id, name: n.name, role: n.role })));

const nameByFacility = Object.fromEntries(nodes.map((n) => [n.facility_id, n.name]));
function terminalName(facilityId) {
  return nameByFacility[facilityId];
}

const dailyEndsText = computed(() => interp(text.value.dailyMileageLine, {
  mileage: dispatch.constraintsForm.mileageLimitKm || text.value.dailyUnlimited,
  terminals: dispatch.constraintsForm.terminal_facility_ids.length
    || text.value.dailyNoTerminal,
}));

/* The daily preview answers whether the limits actually bite: it can come back
   with fewer trucks, more trucks, or orders it could not place at all. */
const dailyOutcome = computed(() => {
  const zone = dispatch.dailyPreview?.zones?.[0];
  if (!zone) return null;
  return {
    vehicles: zone.routes.length,
    unserved: zone.unserved_customer_ids?.length || 0,
    mileageViolations: zone.mileage_violations || 0,
    overLimit: zone.routes.some((r) => r.mileage_limit_violation),
  };
});
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

    <div v-if="!props.primary" class="sg-map-head">
      <button class="sg-expand" @click="transportOpen = true">{{ text.transportOpen }}</button>
    </div>
    <LeafletMap :nodes="nodes" :plan="plan" :selected-id="selectedId" :text="text"
      :height="props.primary ? '520px' : '290px'" :legend="props.primary"
      :selected-vehicle="selectedVehicle"
      :overlays="dispatch.branchOverlays" :branch-node-ids="dispatch.branchNodeIds"
      :incident-node-id="dispatch.incidentNodeId"
      :incident-events="incidentEvents"
      :compare-vehicle="dispatch.branchOverlays.length ? dispatch.branchCandidate?.vehicle_id : null"
      @select="selectedId = $event" @select-vehicle="pickVehicle($event)"
      @select-incident="openIncident" />

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

    <!-- Today's delivery plan (doc §4.1). A reshipment case always plans ONE
         order, so a vehicle served one hospital; a *batch* is what makes the
         multi-stop planner do its job. Simulated, and it says so. -->
    <div v-if="online" class="sg-daily">
      <button :disabled="dispatch.pending" @click="dispatch.loadDailyPlan('today')">
        {{ dispatch.pending ? text.dailyCreating : text.dailyPlan }}
      </button>
      <button :disabled="dispatch.pending" @click="dispatch.oneClickDailyPlan()">
        {{ text.dailyOneClick }}
      </button>
      <template v-if="dispatch.dailyPreview && dispatch.dailyPreview.zones.length">
        <p class="sg-note">{{ text.dailySimulated }}</p>
        <p v-if="dailyConstraintText" class="sg-constraints">{{ dailyConstraintText }}</p>

        <!-- The three knobs the delivery rule reacts to (B3). One truck may take
             several orders only while it stays under the mileage cap; a parking
             node lets it stop there instead of driving back. -->
        <fieldset class="sg-limits">
          <legend>{{ text.dailyLimits }}</legend>
          <label>
            <span>{{ text.dailyMaxVehicles }}</span>
            <input type="number" min="1" max="12" step="1"
              v-model="dispatch.constraintsForm.max_vehicles" />
          </label>
          <label>
            <span>{{ text.dailyMileageCap }}</span>
            <input type="number" min="1" step="1" :placeholder="text.dailyUnlimited"
              v-model="dispatch.constraintsForm.mileageLimitKm" />
          </label>
          <label>
            <span>{{ text.dailyMaxStops }}</span>
            <input type="number" min="1" max="14" step="1"
              v-model="dispatch.constraintsForm.max_stops_per_vehicle" />
          </label>
          <div class="sg-terminals">
            <span>{{ text.dailyTerminals }}</span>
            <label v-for="option in terminalOptions" :key="option.facility_id" class="sg-terminal">
              <input type="checkbox" :value="option.facility_id"
                v-model="dispatch.constraintsForm.terminal_facility_ids" />
              <span>{{ option.name }}</span>
            </label>
          </div>
          <button :disabled="dispatch.pending" @click="dispatch.previewDailyPlan()">
            {{ dispatch.pending ? text.dailyCreating : text.dailyApply }}
          </button>
        </fieldset>
        <p class="sg-constraints">{{ dailyEndsText }}</p>
        <p class="sg-source">
          {{ text.dailyPreview }}<template v-if="dispatch.dailyBatch && dispatch.dailyBatch.seed != null"> · {{ text.dailySeed }} {{ dispatch.dailyBatch.seed }}</template>:
          <b>{{ dispatch.dailyPreview.zones[0].total_distance.toFixed(2) }}</b> {{ text.km }} ·
          <b>{{ dispatch.dailyPreview.zones[0].routes.length }}</b> {{ text.vehicles }} ·
          {{ dispatch.dailyPreview.zones[0].served_facilities }}/{{ dispatch.dailyPreview.zones[0].target_facilities }} {{ text.served }}
        </p>
        <p v-if="dailyOutcome && (dailyOutcome.unserved || dailyOutcome.overLimit)"
          class="sg-error" role="status">
          <template v-if="dailyOutcome.unserved">{{ interp(text.dailyUnserved, { n: dailyOutcome.unserved }) }}</template>
          <template v-if="dailyOutcome.overLimit"> {{ text.dailyOverLimit }}</template>
        </p>
        <ul class="sg-daily-stops">
          <li v-for="route in dispatch.dailyPreview.zones[0].routes" :key="route.vehicle_id">
            <b>{{ route.vehicle_id }}</b>:
            {{ route.customer_ids.map((id) => names[id] || id).join(" → ") }}
            <span class="sg-route-end">
              → {{ text.dailyEndsAt }}
              <b>{{ route.end_facility_id ? (terminalName(route.end_facility_id) || route.end_facility_id) : text.dailyBackToDepot }}</b>
              · {{ route.total_distance.toFixed(1) }} {{ text.km }}
              <em v-if="route.mileage_limit_violation"> ⚠ {{ text.dailyOverLimit }}</em>
            </span>
          </li>
        </ul>
        <button :disabled="dispatch.pending" @click="dispatch.confirmDailyPlan()">
          {{ text.dailyConfirm }}
        </button>
        <button :disabled="dispatch.pending" @click="dispatch.rerollDailyPlan()">
          {{ text.dailyReroll }}
        </button>
      </template>
      <p v-if="dispatch.dailyError" class="sg-error" role="status">{{ dispatch.dailyError }}</p>
    </div>

    <!-- The bridge: this case's resupply joins the SAME operation the day's plan
         created, checked against real stock and real vehicle capacity. Always
         says what the next action is (or why there is none) — a decision that
         needs a resupply must never dead-end in a banner. -->
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

    <!-- Branch event: change a running vehicle's route, or send another one.
         The backend already ranks the options; this is the operator's view of
         that decision — distance, ETA and who else gets delayed (doc §4.2, §5 D3). -->
    <div v-if="canDispatchArchived" class="sg-branch">
      <strong>{{ text.branchTitle }}</strong>
      <p class="sg-note">{{ text.branchHint }}</p>
      <div class="sg-branch-actions">
        <button :disabled="dispatch.pending"
          @click="dispatch.previewBranch(sandbox.currentRunId)">
          {{ dispatch.pending ? text.branchPreviewing : text.branchPreview }}
        </button>
        <label class="sg-branch-policy">
          {{ text.branchPolicy }}
          <select :value="dispatch.policy" :disabled="dispatch.pending"
            @change="dispatch.setPolicy($event.target.value)">
            <option value="minimize_disruption">{{ text.policyDisruption }}</option>
            <option value="minimize_vehicles">{{ text.policyVehicles }}</option>
          </select>
        </label>
      </div>
      <p v-if="dispatch.needsDailyPlan" class="sg-error" role="status">{{ text.branchNeedsPlan }}</p>
      <p v-else-if="dispatch.branchError" class="sg-error" role="status">{{ dispatch.branchError }}</p>

      <table v-if="dispatch.branch?.candidates.length" class="sg-candidates">
        <thead>
          <tr>
            <th>{{ text.branchOption }}</th>
            <th>{{ text.branchVehicle }}</th>
            <th>{{ text.branchExtra }}</th>
            <th>{{ text.branchEta }}</th>
            <th>{{ text.branchAffected }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(c, index) in dispatch.branch.candidates" :key="`${c.kind}-${c.vehicle_id}`"
            :class="{ chosen: index === 0, late: !c.on_time }">
            <td>{{ kindLabel(c.kind) }}<em v-if="!c.on_time"> · {{ text.branchLateness }} {{ c.lateness_min }} {{ text.branchMinutes }}</em></td>
            <td>{{ c.vehicle_id.replace(/^VEH-|^V-/, '') }}</td>
            <td>
              <!-- What the option COSTS, not the length of its final hop: every
                   option ends at the same hospital, so showing that leg made
                   all three read "26.28 km" and look identical. -->
              +{{ (c.added_distance_m / 1000).toFixed(2) }} {{ text.km }}
            </td>
            <td>{{ clock(c.eta_min) }}</td>
            <td>
              <span v-if="!c.affected_orders.length">{{ text.branchNoAffected }}</span>
              <span v-for="a in c.affected_orders" :key="a.order_id" class="sg-affected">
                {{ a.order_id }} +{{ a.delay_min }} {{ text.branchMinutes }}
                <em v-if="a.newly_late">（{{ text.branchNewlyLate }}）</em>
                <em v-else-if="a.already_late">（{{ text.branchAlreadyLate }}）</em>
              </span>
            </td>
            <td>
              <button :disabled="dispatch.pending"
                @click="dispatch.commitReshipment(sandbox.currentRunId,
                  { candidate_kind: c.kind, vehicle_id: c.vehicle_id })">
                {{ text.branchChoose }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="dispatch.branch" class="sg-note">{{ text.branchNoAffected }}</p>
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
      <button class="sg-replay" :disabled="dispatch.pending" @click="dispatch.replay()">
        {{ text.replay }}
      </button>
    </div>

    <!-- A finished operation is history, and the panel used to fall back to the
         demo plan without saying so. Say it, and offer to run it again. -->
    <div v-if="online && !isLive" class="sg-ops">
      <span v-if="dispatch.recent.length" class="hint">
        {{ text.lastRunOver }} <b>{{ dispatch.recent[0].dispatch_id }}</b>
      </span>
      <button v-if="dispatch.recent.length" :disabled="dispatch.pending"
        @click="dispatch.replay(dispatch.recent[0].dispatch_id)">
        {{ text.replayLast }}
      </button>
      <span v-else class="hint">{{ text.noRunYet }}</span>
    </div>
    <p v-if="dispatch.replayError" class="sg-error" role="status">{{ dispatch.replayError }}</p>

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

  <!-- The transport view: the same map, large, with a real pause. -->
  <TransportView v-if="transportOpen" @close="transportOpen = false" />
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
.sg-daily { margin-top: 10px; padding-top: 10px; border-top: 1px solid #e2e8f0; }
.sg-daily > button { background: #0f172a; color: #fff; border: 0; border-radius: 7px; padding: 6px 11px; cursor: pointer; font-size: 12px; font-weight: 600; }
.sg-daily > button:disabled { opacity: .6; cursor: default; }
.sg-daily > button + button { margin-left: 8px; background: #0d9488; }
.sg-constraints { display: inline-block; margin: 0 0 7px; padding: 4px 8px; border-radius: 999px;
  background: #eef2ff; color: #4338ca; font-size: 11px; font-weight: 700; }
.sg-daily-stops { list-style: none; padding: 0; margin: 6px 0 9px; color: #475569; line-height: 1.7; }
.sg-daily-stops b { color: #0f172a; }
.sg-route-end { margin-left: 6px; color: #0f766e; }
.sg-route-end em { color: #b91c1c; font-style: normal; font-weight: 700; }
.sg-limits { margin: 8px 0 6px; padding: 8px 10px 10px; border: 1px solid #cbd5e1; border-radius: 9px;
  background: #f8fafc; display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: flex-end; }
.sg-limits legend { padding: 0 6px; font-size: 11px; font-weight: 700; color: #334155; }
.sg-limits label { display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: #475569; }
.sg-limits input[type="number"] { width: 74px; padding: 5px 7px; border: 1px solid #cbd5e1;
  border-radius: 6px; font-size: 12px; }
.sg-terminals { flex: 1 1 100%; display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center;
  font-size: 11px; color: #475569; }
.sg-terminal { flex-direction: row; align-items: center; gap: 5px; }
.sg-terminal input { margin: 0; }
.sg-limits button { margin-left: auto; background: #1d4ed8; color: #fff; border: 1px solid #1d4ed8;
  border-radius: 7px; padding: 6px 10px; cursor: pointer; font-size: 12px; font-weight: 600; }
.sg-limits button:disabled { opacity: 0.55; cursor: default; }
.sg-commit { margin-top: 10px; }
.sg-commit button { background: #0d9488; color: #fff; border: 1px solid #0d9488; border-radius: 7px; padding: 7px 11px; cursor: pointer; font-size: 12px; font-weight: 600; }
.sg-commit button:disabled { opacity: .6; cursor: default; }
.sg-commit .done { color: #0f766e; font-weight: 600; }
.sg-commit .hint { color: #64748b; }
.sg-stops button.mine { border-color: #0d9488; box-shadow: 0 0 0 2px rgba(13,148,136,.18); }
.sg-error { color: #b91c1c; line-height: 1.5; }
.sg-ops { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 10px 0 4px; }
.sg-ops > button { background: #0f172a; color: #fff; border: 0; border-radius: 7px; padding: 6px 11px; cursor: pointer; font-size: 12px; font-weight: 600; }
.sg-ops .sg-replay { background: #7c3aed; }
.sg-ops .hint { color: #64748b; }
.sg-ops .hint b { color: #0f172a; }
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
.sg-map-head { display: flex; justify-content: flex-end; margin-bottom: 5px; }
.sg-expand { background: #fff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 4px 9px; cursor: pointer; font-size: 11px; color: #334155; font-weight: 600; }
.sg-expand:hover { border-color: #0d9488; color: #0f766e; }
.sg-branch { margin-top: 10px; padding-top: 10px; border-top: 1px solid #e2e8f0; }
.sg-branch > strong { color: #0f172a; }
.sg-branch-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.sg-branch-actions > button { background: #7c3aed; color: #fff; border: 0; border-radius: 7px; padding: 6px 11px; cursor: pointer; font-size: 12px; font-weight: 600; }
.sg-branch-actions > button:disabled { opacity: .6; cursor: default; }
.sg-branch-policy { color: #64748b; }
.sg-branch-policy select { margin-left: 4px; border: 1px solid #cbd5e1; border-radius: 5px; padding: 3px 5px; font-size: 11px; color: #334155; background: #fff; }
.sg-candidates { width: 100%; border-collapse: collapse; margin-top: 4px; }
.sg-candidates th { text-align: left; color: #64748b; font-size: 10px; font-weight: 700; padding: 4px 6px; border-bottom: 1px solid #e2e8f0; }
.sg-candidates td { padding: 6px; border-bottom: 1px solid #f1f5f9; color: #475569; vertical-align: top; line-height: 1.5; }
.sg-candidates tr.chosen td { background: #f0fdfa; }
.sg-candidates tr.late td:first-child { color: #b91c1c; }
.sg-candidates em { font-style: normal; color: #b45309; }
.sg-candidates button { background: #0d9488; color: #fff; border: 0; border-radius: 6px; padding: 4px 8px; cursor: pointer; font-size: 11px; font-weight: 600; white-space: nowrap; }
.sg-candidates button:disabled { opacity: .6; cursor: default; }
.sg-affected { display: block; color: #475569; }
</style>
