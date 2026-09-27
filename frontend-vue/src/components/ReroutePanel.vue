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

/* Network size, computed from the committed road network rather than typed into
   the locale files: the counts changed twice (09-15, 09-16) and the labels went
   stale both times, so every place that shows a size reads it from here. */
const customerNodes = computed(() => nodes.filter((n) => n.role === "customer"));
const counts = computed(() => ({
  nodes: nodes.length,
  hospitals: customerNodes.value.length,
  depots: nodes.filter((n) => n.role === "depot").length,
  thirdParty: nodes.filter((n) => n.role === "third_party").length,
  distribution: nodes.filter((n) => n.role === "distribution").length,
}));

/* Archived cases drawn as markers. Scoped by the shared day filter
   (history.scope), the same value the event rail uses: leaving old excursions
   on the map buried the current day's markers under them. */
const incidentEvents = computed(() => history.scopedRuns.flatMap((run) => {
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
   kinds; the wording is local, like every other decision in this app. The
   candidate list itself now lives in BranchCompareModal, which owns its own
   copy of this mapping — this one still labels the commits shown in the
   operation's own order list. */
const KIND_LABELS = {
  add_stop_in_transit: "branchKindAddStop",
  load_before_departure: "branchKindLoadFirst",
  return_to_depot: "branchKindReturn",
  spare_vehicle: "branchKindSpare",
};
/* The preview lists a route's own stops, so a pickup-delivery run reads as
   "↑W-WESTGATE → H-NUH → ↑D-HOUGANG → H-SKH" instead of pretending the truck
   starts loaded at one place (2026-09-16, PDPTW step 4). Grouped routes have
   delivery stops only, which is what this printed before. */
function routeSequence(route) {
  const stops = route.stops?.length
    ? route.stops
    : (route.customer_ids || []).map((node_id) => ({ node_id, kind: "delivery" }));
  return stops
    .map((stop) => `${stop.kind === "pickup" ? "↑" : ""}${names[stop.node_id] || stop.node_id}`)
    .join(" → ");
}

function stopKindLabel(stop) {
  if (!stop || !stop.kind) return text.value.stop;
  return stop.kind === "pickup" ? text.value.stopPickup : text.value.stopDelivery;
}

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

/* Why an order did not fit (B7). The backend returns stable codes plus the
   measured numbers; the wording lives here, like every other code in this app. */
const unservedOrders = computed(() => dispatch.dailyPreview?.zones?.[0]?.unserved || []);

const REASON_KEYS = {
  mileage_limit_exceeded: "reasonMileage",
  time_window_infeasible: "reasonTimeWindow",
  capacity_exceeded: "reasonCapacity",
  closing_window_exceeded: "reasonClosing",
  stop_limit_exceeded: "reasonStops",
  no_vehicle_available: "reasonNoVehicle",
  placeable_in_isolation: "reasonPlaceable",
};
const km = (metres) => (Number(metres || 0) / 1000).toFixed(1);
function safeClock(minutes) {
  return minutes === undefined || minutes === null ? "—" : clock(minutes);
}
function reasonText(reason) {
  const d = reason.detail || {};
  return interp(text.value[REASON_KEYS[reason.code]] || reason.code, {
    needed: km(d.needed_distance_m), limit: km(d.limit_m),
    earliest: safeClock(d.earliest_arrival_min), latest: safeClock(d.latest_min),
    late: d.late_by_min ?? "", units: d.needed_units ?? "",
    capacity: d.capacity_units ?? "", max: d.max_stops_per_vehicle ?? "",
    closing: safeClock(d.closing_min),
  });
}

/* Where the fleet should spend the night (B5). */
const overnight = computed(() => dispatch.overnightPlan);
const OVERNIGHT_NOTES = {
  mileage_budget_exhausted: "overnightBudget",
  no_terminal_given: "overnightNoTerminal",
  unused_tomorrow: "overnightUnused",
  kept_position: "overnightKept",
};
function overnightNoteText(note) {
  return text.value[OVERNIGHT_NOTES[note]] || note;
}
function facilityName(facilityId) {
  return nameByFacility[facilityId] || facilityId;
}

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
    <p class="sg-note">{{ interp(text.note, counts) }}</p>
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
      <div><b>{{ plan.metrics.served_customers }}/{{ counts.hospitals }}</b><span>{{ text.served }}</span></div>
      <div><b>{{ plan.metrics.time_window_violations + plan.metrics.capacity_violations + plan.metrics.depot_return_violations + plan.metrics.vehicle_limit_violations }}</b><span>{{ text.violations }}</span></div>
    </div>

    <!-- Today's delivery plan (doc §4.1). The demo path is deliberately two
         steps: generate the batch (read-only), review it, then confirm — the
         confirmation is the only write. The one-press shortcut that skips the
         review is kept for debugging, folded away so it cannot be mistaken for
         a second equally-important primary button (item 4, 2026-09-27). -->
    <div v-if="online" class="sg-daily">
      <button :disabled="dispatch.pending" @click="dispatch.loadDailyPlan('today')">
        {{ dispatch.pending ? text.dailyCreating : text.dailyPlan }}
      </button>
      <details class="sg-advanced">
        <summary>{{ text.dailyAdvanced }}</summary>
        <button class="sg-secondary" :disabled="dispatch.pending" @click="dispatch.oneClickDailyPlan()">
          {{ text.dailyOneClick }}
        </button>
        <p class="sg-note">{{ text.dailyOneClickNote }}</p>
      </details>
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
          <label>
            <span>{{ text.dailyModel }}</span>
            <select v-model="dispatch.constraintsForm.routing_model">
              <option value="grouped">{{ text.dailyModelGrouped }}</option>
              <option value="pickup_delivery">{{ text.dailyModelPaired }}</option>
            </select>
          </label>
          <p v-if="dispatch.constraintsForm.routing_model === 'pickup_delivery'"
            class="sg-note">{{ text.dailyModelHint }}</p>
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
        <div v-if="unservedOrders.length" class="sg-unserved" role="status">
          <p class="sg-error">{{ interp(text.dailyUnserved, { n: unservedOrders.length }) }}</p>
          <ul>
            <li v-for="entry in unservedOrders" :key="entry.node_id">
              <b>{{ names[entry.node_id] || entry.facility_id }}</b>
              <span v-for="reason in entry.reasons" :key="reason.code" class="sg-reason">
                {{ reasonText(reason) }}
              </span>
            </li>
          </ul>
        </div>
        <p v-if="dailyOutcome && dailyOutcome.overLimit" class="sg-error">{{ text.dailyOverLimit }}</p>
        <ul class="sg-daily-stops">
          <li v-for="route in dispatch.dailyPreview.zones[0].routes" :key="route.vehicle_id">
            <b>{{ route.vehicle_id }}</b>:
            <em class="sg-origin">{{ dispatch.dailyPreview.zones[0].origin_facility_id
              ? interp(text.dailyFrom, {
                  origin: facilityName(dispatch.dailyPreview.zones[0].origin_facility_id) })
              : text.dailyFromMany }}</em>
            {{ routeSequence(route) }}
            <span class="sg-route-end">
              → {{ text.dailyEndsAt }}
              <b>{{ route.end_facility_id ? (terminalName(route.end_facility_id) || route.end_facility_id) : text.dailyBackToDepot }}</b>
              · {{ route.total_distance.toFixed(1) }} {{ text.km }}
              <em v-if="route.mileage_limit_violation"> ⚠ {{ text.dailyOverLimit }}</em>
            </span>
          </li>
        </ul>
        <button class="sg-primary" :disabled="dispatch.pending" @click="dispatch.confirmDailyPlan()">
          {{ text.dailyConfirm }}
        </button>
        <button :disabled="dispatch.pending" @click="dispatch.rerollDailyPlan()">
          {{ text.dailyReroll }}
        </button>

        <!-- Optional read-only analysis, folded away and placed after the action
             it belongs to: it used to sit mid-panel looking like a required
             step 3, so operators clicked it expecting to have to (item 3). -->
        <details class="sg-advanced">
          <summary>{{ text.overnightToggle }}</summary>
          <div class="sg-overnight">
            <button class="sg-secondary" :disabled="dispatch.pending" @click="dispatch.loadOvernightPlan()">
              {{ dispatch.pending ? text.dailyCreating : text.overnightPlan }}
            </button>
            <p class="sg-note">{{ text.overnightOptional }}</p>
            <template v-if="overnight">
              <p class="sg-note">{{ text.overnightNote }}</p>
              <ul class="sg-daily-stops">
                <li v-for="choice in overnight.choices" :key="choice.vehicle_id">
                  <b>{{ choice.vehicle_id }}</b>:
                  {{ facilityName(choice.from_facility_id) }} → {{ text.overnightPark }}
                  <b>{{ facilityName(choice.park_facility_id) }}</b>
                  · {{ text.overnightReposition }} {{ km(choice.reposition_m) }} {{ text.km }}
                  · {{ text.overnightFirstStop }}
                  {{ choice.tomorrow_origin_facility_id ? facilityName(choice.tomorrow_origin_facility_id) : text.overnightIdle }}
                  · {{ text.overnightSaved }} {{ km(choice.saved_m) }} {{ text.km }}
                  <em v-if="choice.note">（{{ overnightNoteText(choice.note) }}）</em>
                </li>
              </ul>
              <p class="sg-constraints">{{ interp(text.overnightTotals, {
                reposition: km(overnight.totals.reposition_m),
                saved: km(overnight.totals.saved_m),
                net: km(overnight.totals.net_two_day_m),
              }) }}</p>
            </template>
          </div>
        </details>
      </template>
      <p v-if="dispatch.dailyError" class="sg-error" role="status">{{ dispatch.dailyError }}</p>
    </div>

    <!-- This case's resupply joins the SAME operation the day's plan created,
         checked against real stock and real vehicle capacity. There is no
         one-press "commit the default" button here any more: that button wrote
         stock and assigned a vehicle while wearing a "safe" green, which let an
         operator commit to the first-ranked option without ever seeing the
         alternatives. Comparing first is now the only way in (item 1, 2026-09-27). -->
    <div class="sg-commit">
      <button v-if="canCloseAndDispatch" :disabled="busy || dispatch.pending"
        @click="closeAndDispatch()">
        {{ (busy || dispatch.pending) ? text.committing : text.closeAndDispatch }}
      </button>
      <span v-else-if="alreadyCommitted" class="done">{{ text.committed }}</span>
      <span v-else-if="needsReshipment && !online" class="hint">{{ text.needsApi }}</span>
      <span v-else-if="!needsReshipment" class="hint">{{ text.noReshipment }}</span>
    </div>

    <!-- Branch event: change a running vehicle's route, or send another one.
         The backend already ranks the options; the popup is where the operator
         compares them (distance, ETA, who else gets delayed — doc §4.2, §5 D3)
         and commits the one they picked, so this block is the primary action. -->
    <div v-if="canDispatchArchived" class="sg-branch">
      <strong>{{ text.branchTitle }}</strong>
      <p class="sg-note">{{ text.branchHint }}</p>
      <div class="sg-branch-actions">
        <button :disabled="dispatch.pending"
          @click="dispatch.previewBranch(sandbox.currentRunId)">
          {{ dispatch.pending ? text.branchPreviewing : text.branchCompare }}
        </button>
      </div>
      <p v-if="dispatch.needsDailyPlan" class="sg-error" role="status">{{ text.branchNeedsPlan }}</p>
      <p v-else-if="dispatch.branchError" class="sg-error" role="status">{{ dispatch.branchError }}</p>

      <!-- The options themselves open in a popup (BranchCompareModal): choosing
           between them is a map-and-timeline decision, which a table row cannot
           show. This keeps a way back into it once it has been closed. -->
      <p v-if="dispatch.branch?.candidates.length && !dispatch.branchOpen" class="sg-note">
        <button class="sg-reopen" :disabled="dispatch.pending"
          @click="dispatch.branchOpen = true">{{ text.compareReopen }}</button>
      </p>
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
        <!-- A pickup-delivery run interleaves collecting and delivering, so a stop
             says which one it is: an unmarked stop list would read as if the truck
             handed goods over at a supply point (2026-09-16, PDPTW step 4). -->
        <button v-for="(id, i) in route.customer_ids" :key="`${route.vehicle_id}-${id}-${i}`"
          :title="names[id]" :aria-label="`${stopKindLabel(route.stops[i])} ${i + 1}: ${names[id]}`"
          :class="{ selected: selectedId === id, done: route.stops[i]?.delivered,
                    pickup: route.stops[i]?.kind === 'pickup',
                    mine: route.stops[i]?.order_id === thisCaseOrderId }"
          @click="selectedId = id">{{ i + 1 }} · {{ nodes[id].facility_id.replace(/^H-/, '') }}
          <em v-if="route.stops[i]?.kind === 'pickup'">↑{{ text.stopPickup }}</em></button>
        <span>→ {{ text.depot }}</span>
      </div>
    </div>

    <div class="sg-detail" aria-live="polite">
      <template v-if="selected">
        <b>{{ selected.node.name }}</b>
        <template v-if="selected.stop">
          <div>{{ text.vehicle }} {{ selected.vehicle }} · {{ text.stop }} {{ selected.index }}
            <template v-if="selected.stop.kind"> · {{ stopKindLabel(selected.stop) }}</template>
          </div>
          <!-- A live stop knows its order and window; a demo stop knows its schedule. -->
          <div v-if="selected.stop.order_id">
            {{ selected.stop.order_id }}<template v-if="selected.stop.source_run_id"> · {{ text.fromCase }} {{ selected.stop.source_run_id }}</template>
          </div>
          <div v-if="selected.stop.kind === 'pickup'" class="sg-pickup">{{ text.stopPickupHint }}</div>
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
/* One primary action per step: "generate the batch" and "confirm it" carry the
   dark fill, everything secondary is outlined. Two equally loud buttons made the
   two-step demo path read as two competing choices (2026-09-27). */
.sg-daily > button { background: #0f172a; color: #fff; border: 0; border-radius: 7px; padding: 6px 11px; cursor: pointer; font-size: 12px; font-weight: 600; }
.sg-daily > button:disabled { opacity: .6; cursor: default; }
.sg-daily > button + button { margin-left: 8px; }
.sg-daily > button.sg-primary { display: block; margin: 8px 0 0; padding: 8px 14px; font-size: 12.5px; }
.sg-secondary { background: #fff; color: #0f766e; border: 1px solid #0d9488; border-radius: 7px;
  padding: 5px 10px; cursor: pointer; font-size: 11.5px; font-weight: 600; }
.sg-secondary:hover:not(:disabled) { background: #f0fdfa; }
.sg-secondary:disabled { opacity: .6; cursor: default; }
/* Folded-away extras: a <details> keeps them reachable without letting them
   look like required steps of the demo flow. */
.sg-advanced { margin: 8px 0 4px; }
.sg-advanced > summary { cursor: pointer; color: #64748b; font-size: 11px; font-weight: 600; }
.sg-advanced > summary:hover { color: #0f766e; }
.sg-advanced .sg-note { margin: 6px 0 0; }
.sg-constraints { display: inline-block; margin: 0 0 7px; padding: 4px 8px; border-radius: 999px;
  background: #eef2ff; color: #4338ca; font-size: 11px; font-weight: 700; }
.sg-daily-stops { list-style: none; padding: 0; margin: 6px 0 9px; color: #475569; line-height: 1.7; }
.sg-daily-stops b { color: #0f172a; }
.sg-origin { color: #0f766e; font-style: normal; font-weight: 600; margin-right: 4px; }
.sg-unserved { margin: 6px 0; }
.sg-unserved ul { list-style: none; padding: 0; margin: 4px 0 0; }
.sg-unserved li { color: #7f1d1d; font-size: 12px; line-height: 1.6; }
.sg-reason { display: inline-block; margin-left: 6px; padding: 1px 6px; border-radius: 999px;
  background: #fee2e2; color: #991b1b; font-size: 11px; }
.sg-overnight { margin: 6px 0 6px; padding: 8px 10px; border: 1px dashed #94a3b8; border-radius: 9px;
  background: #f8fafc; }
.sg-overnight > button:disabled { opacity: 0.55; cursor: default; }
.sg-overnight em { color: #b45309; font-style: normal; font-weight: 600; }
.sg-route-end { margin-left: 6px; color: #0f766e; }
.sg-route-end em { color: #b91c1c; font-style: normal; font-weight: 700; }
.sg-limits { margin: 8px 0 6px; padding: 8px 10px 10px; border: 1px solid #cbd5e1; border-radius: 9px;
  background: #f8fafc; display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: flex-end; }
.sg-limits legend { padding: 0 6px; font-size: 11px; font-weight: 700; color: #334155; }
.sg-limits label { display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: #475569; }
.sg-limits select { padding: 5px 7px; border: 1px solid #cbd5e1; border-radius: 6px;
  font-size: 11px; background: #fff; }
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
/* Way back into the comparison popup after closing it (the options themselves
   live in BranchCompareModal, not in a table here). */
.sg-reopen { border: 1px solid var(--teal); background: #fff; color: var(--teal); border-radius: 8px;
  padding: 5px 10px; font-size: 11.5px; font-weight: 600; cursor: pointer; }
.sg-reopen:hover:not(:disabled) { background: #f0fdfa; }
.sg-reopen:disabled { opacity: .6; cursor: default; }
.sg-pickup { margin-top: 2px; color: #0f766e; font-size: 10px; }
/* A collection stop: same strip, visibly different job. */
.sg-stops button.pickup { border-style: dashed; border-color: #0f766e; }
.sg-stops button.pickup em { font-style: normal; margin-left: 3px; color: #0f766e; font-size: 9px; }
</style>
