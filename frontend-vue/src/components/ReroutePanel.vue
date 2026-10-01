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
import SimulationGenerator from "./SimulationGenerator.vue";
import UrgentOrderPanel from "./UrgentOrderPanel.vue";
import { warehouseOptions } from "../lib/urgent.js";
import { locale, bundle } from "../i18n/index.js";
import { DISPO_COLOR } from "../data/products.js";
import { STATUS_COLORS, summarizeZones, previewMap } from "../lib/incidentWorkflow.js";
import { interp } from "../lib/format.js";
import { dispatchReasonText } from "../lib/dispatchReasons.js";

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
  const facilityId = run.event?.facility_id || run.event?.destination_facility_id;
  const nodeId = nodeByFacility[facilityId];
  if (nodeId == null) return [];
  return [{
    id: run.run_id,
    nodeId,
    color: STATUS_COLORS[history.statusOf(run)],
    label: `${run.run_id} · ${bundle(locale.value).workflow[history.statusOf(run)]} · ${run.event?.facility_id ? names[nodeId] : bundle(locale.value).workflow.unknownLocation}`,
  }];
}));

function openIncident(runId) {
  const record = history.runs.find((run) => run.run_id === runId);
  if (!record) return;
  sandbox.restoreCase(record);
  selectedId.value = nodeByFacility[record.event?.facility_id || record.event?.destination_facility_id] ?? null;
  overlay.openCase();
}

/* The plan the map draws: live operation when there is one, else the demo. */
const plan = computed(() => dispatch.live || (dispatch.dailyPreview
  ? previewMap(dispatch.dailyPreview.zones) : data.plans[mode.value]));
const mapOverlays = computed(() => dispatch.urgentOverlays.length ? dispatch.urgentOverlays : dispatch.branchOverlays);
const mapBranchNodes = computed(() => dispatch.urgentOverlays.length ? [
  nodeByFacility[dispatch.urgentForm.origin_facility_id], nodeByFacility[dispatch.urgentForm.destination_facility_id],
].filter((id) => id != null) : dispatch.branchNodeIds);
const mapCompareVehicle = computed(() => dispatch.urgentOverlays.length ? dispatch.urgentCandidate?.vehicle_id : dispatch.branchCandidate?.vehicle_id);

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
const speed = computed(() => dispatch.run?.clock?.speed ?? 60);
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
  warehouseOptions(nodes)
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
const dailyZones = computed(() => dispatch.dailyPreview?.zones || []);
const dailyTotals = computed(() => summarizeZones(dailyZones.value));
const unservedOrders = computed(() => dailyZones.value.flatMap((zone, index) =>
  (zone.unserved || []).map((entry) => ({ ...entry, zoneIndex: index, temperature_zone: zone.temperature_zone,
    origin_facility_id: zone.origin_facility_id }))));
const unservedOrderCount = computed(() => unservedOrders.value.reduce((sum, entry) =>
  sum + (entry.order_ids?.length || 1), 0));

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
  return dispatchReasonText(reason, text.value, clock);
}

/* Where the fleet should spend the night (B5). */
const overnight = computed(() => dispatch.overnightPlan);
const OVERNIGHT_NOTES = {
  mileage_budget_exhausted: "overnightBudget",
  no_terminal_given: "overnightNoTerminal",
  unused_tomorrow: "overnightUnused",
  kept_position: "overnightKept",
  warehouse_required: "overnightWarehouseRequired",
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
  const zones = dailyZones.value;
  if (!zones.length) return null;
  return {
    vehicles: dailyTotals.value.vehicles,
    unserved: unservedOrderCount.value,
    mileageViolations: zones.reduce((sum, zone) => sum + (zone.mileage_violations || 0), 0),
    overLimit: zones.some((zone) => zone.routes.some((r) => r.mileage_limit_violation)),
  };
});
</script>

<template>
  <div class="sg-routing">
    <strong>{{ text.title }}</strong>
    <p class="sg-note">{{ interp(text.note, counts) }}</p>
    <p class="sg-source" :class="{ live: isLive }">
      {{ isLive ? text.liveOperation : dispatch.dailyPreview ? text.dailyPreview : text.demoRoute }}
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
      :overlays="mapOverlays" :branch-node-ids="mapBranchNodes"
      :incident-node-id="dispatch.incidentNodeId"
      :incident-events="incidentEvents"
      :compare-vehicle="mapOverlays.length ? mapCompareVehicle : null"
      @select="selectedId = $event" @select-vehicle="pickVehicle($event)"
      @select-incident="openIncident" />

    <div v-if="isLive" class="sg-metrics">
      <div><b>{{ dispatch.run.status }}</b><span>{{ text.dispatchStatus }}</span></div>
      <div><b>{{ dispatch.live.metrics.orders_delivered }}/{{ dispatch.live.metrics.orders_total }}</b><span>{{ text.ordersDelivered }}</span></div>
      <div v-if="dispatch.live.metrics.orders_failed"><b>{{ dispatch.live.metrics.orders_failed }}</b><span>{{ text.ordersFailed }}</span></div>
      <div><b>{{ dispatch.live.metrics.vehicles_used }}</b><span>{{ text.vehicles }}</span></div>
    </div>
    <div v-else class="sg-metrics">
      <div><b>{{ plan.metrics.total_distance.toFixed(2) }}</b><span>{{ text.distance }} · {{ text.km }}</span></div>
      <div><b>{{ plan.metrics.vehicles_used }}</b><span>{{ text.vehicles }}</span></div>
      <div><b>{{ plan.metrics.served_customers }}/{{ plan.metrics.target_customers ?? counts.hospitals }}</b><span>{{ text.served }}</span></div>
      <div><b>{{ plan.metrics.time_window_violations + plan.metrics.capacity_violations + plan.metrics.depot_return_violations + plan.metrics.vehicle_limit_violations }}</b><span>{{ text.violations }}</span></div>
    </div>

    <!-- Today's delivery plan (doc §4.1). The demo path is deliberately two
         steps: generate the batch (read-only), review it, then confirm — the
         confirmation is the only write. The one-press shortcut that skips the
         review is kept for debugging, folded away so it cannot be mistaken for
         a second equally-important primary button (item 4, 2026-09-27). -->
    <div v-if="online" class="sg-daily">
      <SimulationGenerator />
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
          <b>{{ dailyTotals.distance.toFixed(2) }}</b> {{ text.km }} ·
          <b>{{ dailyTotals.vehicles }}</b> {{ text.vehicles }} ·
          {{ dailyTotals.served }}/{{ dailyTotals.target }} {{ text.served }}
        </p>
        <div v-if="unservedOrders.length" class="sg-unserved" role="status">
          <p class="sg-error">{{ interp(text.dailyUnserved, { n: unservedOrderCount }) }}</p>
          <ul>
            <li v-for="entry in unservedOrders" :key="`${entry.zoneIndex}-${entry.node_id}`">
              <b>{{ names[entry.node_id] || entry.facility_id }}</b>
              · {{ text[entry.temperature_zone] || entry.temperature_zone }} · {{ facilityName(entry.origin_facility_id) }}
              <small>{{ (entry.order_ids || []).join(', ') }}</small>
              <span v-for="reason in entry.reasons" :key="reason.code" class="sg-reason">
                {{ reasonText(reason) }}
              </span>
            </li>
          </ul>
        </div>
        <p v-if="dailyOutcome && dailyOutcome.overLimit" class="sg-error">{{ text.dailyOverLimit }}</p>
        <section v-for="(zone, zoneIndex) in dailyZones" :key="`${zone.temperature_zone}-${zone.origin_facility_id}-${zoneIndex}`" class="sg-daily-zone">
        <h4>{{ text[zone.temperature_zone] || zone.temperature_zone }} · {{ zone.origin_facility_id ? facilityName(zone.origin_facility_id) : text.dailyFromMany }}</h4>
        <p>{{ zone.served_facilities }}/{{ zone.target_facilities }} {{ text.served }} · {{ zone.total_distance.toFixed(2) }} {{ text.km }}</p>
        <ul class="sg-daily-stops">
          <li v-for="route in zone.routes" :key="route.vehicle_id">
            <b>{{ route.vehicle_id }}</b>:
            <span v-if="route.start_facility_id" class="sg-origin">{{ interp(text.dailyVehicleStart, { start: facilityName(route.start_facility_id) }) }}</span>
            <em class="sg-origin">{{ zone.origin_facility_id
              ? interp(text.dailyFrom, {
                  origin: facilityName(zone.origin_facility_id) })
              : text.dailyFromMany }}</em>
            {{ routeSequence(route) }}
            <span class="sg-route-end">
              → {{ text.dailyEndsAt }}
              <b>{{ facilityName(route.actual_end_facility_id || route.end_facility_id || route.start_facility_id) }}</b>
              · {{ route.total_distance.toFixed(1) }} {{ text.km }}
              <em v-if="route.mileage_limit_violation"> ⚠ {{ text.dailyOverLimit }}</em>
            </span>
          </li>
        </ul>
        </section>
        <button class="sg-primary" :disabled="dispatch.pending || !dispatch.dailyPreview.feasible || !dispatch.simulationInputsCurrent" @click="dispatch.confirmDailyPlan()">
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
    <UrgentOrderPanel v-if="online" />
    <p v-if="dispatch.error" class="sg-error" role="status">{{ dispatch.error }}</p>

    <div v-if="isLive && dispatch.run.status === 'completed'" class="sg-overnight sg-end-day">
      <strong>{{ text.endDayTitle }} · {{ dispatch.run.operating_date }}</strong>
      <p class="sg-note">{{ text.endDayHint }}</p>
      <p v-if="!dispatch.run.overnight" class="sg-note">{{ text.endDayDemoSupply }}</p>
      <button v-if="!dispatch.run.overnight" :disabled="dispatch.pending || dispatch.stillReturning"
        @click="dispatch.previewEndOfDay()">{{ text.endDayPreview }}</button>
      <template v-if="dispatch.endOfDayPreview">
        <ul class="sg-daily-stops">
          <li v-for="choice in dispatch.endOfDayPreview.choices" :key="choice.vehicle_id">
            <b>{{ choice.vehicle_id }}</b> · {{ facilityName(choice.from_facility_id) }} →
            <select v-model="dispatch.parkingOverrides[choice.vehicle_id]" :disabled="dispatch.pending">
              <option v-for="facility in (dispatch.endOfDayPreview.tomorrow.constraints.terminal_facility_ids || terminalOptions.map((n) => n.facility_id)).filter((id) => terminalOptions.some((n) => n.facility_id === id))"
                :key="facility" :value="facility">{{ facilityName(facility) }}</option>
            </select>
            · {{ text.overnightReposition }} {{ km(choice.reposition_m) }} {{ text.km }}
            · {{ text.endDayDeadhead }} {{ km(choice.deadhead_m) }} {{ text.km }}
            · {{ text.overnightFirstStop }} {{ choice.tomorrow_origin_facility_id ? facilityName(choice.tomorrow_origin_facility_id) : text.overnightIdle }}
            <span v-if="choice.blocked_by.length" class="sg-error">
              {{ choice.blocked_by.map(reasonText).join(' · ') }}
            </span>
          </li>
        </ul>
        <p>{{ text.endDayPlan }} · {{ dispatch.endOfDayPreview.next_operating_date }}</p>
        <ul class="sg-daily-stops">
          <li v-for="route in dispatch.endOfDayPreview.next_day_plan.zones.flatMap((zone) => zone.routes)" :key="route.vehicle_id">
            <b>{{ route.vehicle_id }}</b> · {{ facilityName(route.start_facility_id) }} →
            {{ routeSequence(route) }} → {{ facilityName(route.actual_end_facility_id || route.end_facility_id || route.start_facility_id) }}
            · {{ route.total_distance.toFixed(1) }} {{ text.km }}
          </li>
        </ul>
        <p class="sg-note">{{ text.endDayInventory }}</p>
        <button :disabled="dispatch.pending" @click="dispatch.previewEndOfDay()">{{ text.endDayRecalculate }}</button>
        <button :disabled="dispatch.pending || !dispatch.parkingPreviewCurrent || !dispatch.endOfDayPreview.feasible"
          @click="dispatch.acceptEndOfDay()">{{ text.endDayAccept }}</button>
        <p v-if="!dispatch.endOfDayPreview.feasible" class="sg-error">{{ text.endDayInfeasible }}</p>
      </template>
      <p v-if="dispatch.run.overnight?.status === 'repositioning'" role="status">{{ text.endDayMoving }}</p>
      <button v-if="dispatch.run.overnight?.status === 'parked'" :disabled="dispatch.pending"
        @click="dispatch.startNextDay()">{{ text.endDayStartNext }} · {{ dispatch.run.overnight.next_operating_date }}</button>
      <p v-if="dispatch.run.overnight?.status === 'next_day_created'" class="sg-note">
        <button :disabled="dispatch.pending" @click="dispatch.loadRun(dispatch.run.overnight.next_dispatch_id)">{{ text.endDayOpenNext }}</button>
      </p>
      <p v-if="dispatch.endOfDayError" class="sg-error" role="status">{{ dispatch.endOfDayError }}</p>
    </div>

    <!-- Operating the run: depart, then the simulated clock drives arrivals. -->
    <div v-if="isLive" class="sg-ops">
      <button v-if="canDepart" :disabled="dispatch.pending" @click="dispatch.depart()">
        {{ text.depart }}
      </button>
      <template v-if="dispatch.run?.clock">
        <span class="sim">{{ dispatch.run.operating_date }} · {{ text.simClock }} {{ simClock() }}</span>
        <span class="speeds">
          <button v-for="s in SPEEDS" :key="s.value" :class="{ on: speed === s.value }"
            @click="dispatch.setSpeed(s.value)">{{ text[s.key] }}</button>
        </span>
      </template>
      <button class="sg-replay" :disabled="dispatch.pending" @click="dispatch.replay()">
        {{ text.replay }}
      </button>
    </div>

    <!-- Independent B2 path: scan the running work before a late delivery is
         committed, compare each vehicle's remaining queue, then let the
         operator apply one verified improvement.  No route changes merely from
         pressing "inspect". -->
    <div v-if="underway" class="sg-delay">
      <strong>{{ text.delayTitle }}</strong>
      <p class="sg-note">{{ text.delayHint }}</p>
      <p v-if="dispatch.delayInspection?.predicted_late_order_count" class="sg-error" role="status">
        {{ interp(text.delayAutomaticRisk, { n: dispatch.delayInspection.predicted_late_order_count }) }}
      </p>
      <div class="sg-delay-controls">
        <label>
          <span>{{ text.delayInput }}</span>
          <input v-model.number="dispatch.delayMinutes" type="number" min="0" step="1" />
          <em>{{ text.branchMinutes }}</em>
        </label>
        <button :disabled="dispatch.pending" @click="dispatch.previewDelayRisk()">
          {{ dispatch.pending ? text.delayInspecting : text.delayInspect }}
        </button>
      </div>
      <p v-if="dispatch.delayError" class="sg-error" role="status">{{ dispatch.delayError }}</p>
      <template v-else-if="dispatch.delay">
        <p v-if="!dispatch.delay.predicted_late_order_count" class="sg-delay-clear" role="status">
          {{ text.delayClear }}
        </p>
        <div v-for="candidate in dispatch.delay.candidates" :key="`delay-${candidate.vehicle_id}`"
          class="sg-delay-candidate">
          <b>{{ candidate.vehicle_id }}</b>
          <span>{{ interp(text.delayFound, {
            n: candidate.baseline.predicted_late_order_count,
            min: candidate.baseline.total_lateness_min,
          }) }}</span>
          <div class="sg-delay-queues">
            <span>{{ text.delayBefore }} {{ candidate.original_order_ids.join(' → ') }}</span>
            <span>{{ text.delayAfter }} {{ candidate.remaining_order_ids_after.join(' → ') }}</span>
          </div>
          <ul class="sg-delay-effects">
            <li v-for="effect in candidate.affected_orders" :key="effect.order_id">
              {{ effect.order_id }} · {{ clock(effect.baseline_eta_min) }} →
              {{ clock(effect.replanned_eta_min) }} · {{ text.branchLateness }}
              {{ effect.baseline_lateness_min }} → {{ effect.replanned_lateness_min }} {{ text.branchMinutes }}
            </li>
          </ul>
          <p v-if="candidate.replan_available" class="sg-note">
            {{ interp(text.delayReplan, {
              n: candidate.replanned.predicted_late_order_count,
              min: candidate.replanned.total_lateness_min,
            }) }}
          </p>
          <p v-else class="sg-note">{{ text.delayNoBetter }}</p>
          <button v-if="candidate.replan_available" :disabled="dispatch.pending"
            @click="dispatch.acceptDelayReplan(candidate)">{{ text.delayApply }}</button>
        </div>
      </template>
    </div>

    <!-- Mechanical-failure rescue is deliberately explicit: the operator marks
         a truck failed, compares replacement-vehicle options, then accepts one.
         No cold-transfer path is implied when the model has not established it. -->
    <div v-if="underway" class="sg-failure">
      <strong>{{ text.failureTitle }}</strong>
      <p class="sg-note">{{ text.failureHint }}</p>
      <div class="sg-branch-actions">
        <button v-for="route in plan.routes.filter((r) => r.status === 'in_transit')"
          :key="`fail-${route.vehicle_id}`" :disabled="dispatch.pending"
          @click="dispatch.previewVehicleFailure(route.vehicle_id)">
          {{ interp(text.failurePreview, { vehicle: route.vehicle_id }) }}
        </button>
      </div>
      <p v-if="dispatch.failureError" class="sg-error" role="status">{{ dispatch.failureError }}</p>
      <template v-else-if="dispatch.failure">
        <p v-if="!dispatch.failure.feasible" class="sg-error" role="status">
          {{ text.failureNoRescue }}: {{ dispatch.failure.reason }}
        </p>
        <div v-else class="sg-failure-options">
          <p class="sg-note">{{ text.failureBoundary }}</p>
          <button v-for="candidate in dispatch.failure.candidates"
            :key="`failure-${candidate.vehicle_id}`" :disabled="dispatch.pending || !candidate.on_time"
            @click="dispatch.acceptVehicleFailure(candidate)">
            {{ interp(text.failureUse, { vehicle: candidate.vehicle_id }) }} ·
            {{ candidate.distance_m ? (candidate.distance_m / 1000).toFixed(2) : '0.00' }} {{ text.km }}
            <template v-if="!candidate.on_time"> · {{ text.branchLateness }} {{ candidate.lateness_min }} {{ text.branchMinutes }}</template>
          </button>
        </div>
      </template>
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
      <button v-if="dispatch.recent.length" :disabled="dispatch.pending"
        @click="dispatch.loadRun(dispatch.recent[0].dispatch_id)">{{ text.endDayOpenCompleted }}</button>
      <span v-else class="hint">{{ text.noRunYet }}</span>
    </div>
    <p v-if="dispatch.replayError" class="sg-error" role="status">{{ dispatch.replayError }}</p>

    <div v-for="(route, index) in plan.routes" :key="route.vehicle_id" class="sg-vehicle"
      :class="{ picked: selectedVehicle === route.vehicle_id }">
      <b :style="{ color: color(index) }" class="veh-name" role="button" tabindex="0"
        @click="pickVehicle(route.vehicle_id)" @keydown.enter="pickVehicle(route.vehicle_id)">
        ● {{ text.vehicle }} {{ route.vehicle_id }}
        <em v-if="route.status === 'failed'" class="sg-failed">· {{ text.failureVehicleFailed }}</em>
        <em v-if="route.track">· {{ route.track.reached_stops }}/{{ route.customer_ids.length }}</em>
      </b>
      <span v-if="route.total_distance != null">{{ route.total_distance.toFixed(2) }} {{ text.km }}</span>
      <div class="sg-stops">
        <button :class="{ selected: selectedId === (route.start_node_id ?? 0) }"
          @click="selectedId = route.start_node_id ?? 0">{{ route.start_facility_id ? facilityName(route.start_facility_id) : text.depot }}</button>
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
        <span v-if="route.status !== 'failed'">→ {{ route.end_facility_id ? facilityName(route.end_facility_id) : text.depot }}</span>
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
          <div>{{ text.window }} {{ clock(selected.stop.earliest_min ?? selected.node.earliest_min) }}–{{ clock(selected.stop.latest_min ?? selected.node.latest_min) }}</div>
          <p v-if="dispatch.run?.nominal_order_ids?.includes(selected.stop.order_id)" class="sg-note">{{ text.nominalUrgentTask }}</p>
          <details v-else class="sg-advanced"><summary>{{ text.modelQuantityOnly }}</summary>
            {{ text.demand }} {{ selected.stop.quantity ?? selected.node.demand }} {{ text.units }}
          </details>
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
.sg-failure { margin-top: 10px; padding: 10px; border: 1px solid #fbbf24; border-radius: 9px; background: #fffbeb; }
.sg-failure > strong { color: #92400e; }
.sg-failure-options { display: flex; flex-wrap: wrap; gap: 7px; }
.sg-failure-options button { border: 1px solid #d97706; background: #fff; color: #92400e; border-radius: 7px; padding: 6px 9px; cursor: pointer; font-size: 11.5px; font-weight: 700; }
.sg-failure-options button:disabled { opacity: .55; cursor: default; }
.sg-failed { color: #dc2626; font-style: normal; font-weight: 700; }
.sg-delay { margin-top: 10px; padding: 10px; border: 1px solid #93c5fd; border-radius: 9px; background: #eff6ff; }
.sg-delay > strong { color: #1d4ed8; }
.sg-delay-controls { display: flex; gap: 8px; align-items: end; flex-wrap: wrap; }
.sg-delay-controls label { display: grid; grid-template-columns: auto 62px auto; gap: 5px; align-items: center; color: #1e40af; font-size: 11.5px; }
.sg-delay-controls input { width: 62px; padding: 4px; border: 1px solid #93c5fd; border-radius: 5px; }
.sg-delay-controls em { color: #64748b; font-style: normal; }
.sg-delay-controls button, .sg-delay-candidate button { border: 1px solid #2563eb; background: #2563eb; color: #fff; border-radius: 7px; padding: 6px 9px; cursor: pointer; font-size: 11.5px; font-weight: 700; }
.sg-delay-controls button:disabled, .sg-delay-candidate button:disabled { opacity: .55; cursor: default; }
.sg-delay-clear { margin: 8px 0 0; color: #047857; font-weight: 700; }
.sg-delay-candidate { margin-top: 8px; padding: 8px; border-radius: 7px; background: #fff; color: #1e3a8a; }
.sg-delay-candidate > span { margin-left: 6px; font-size: 11.5px; }
.sg-delay-candidate .sg-note { margin: 5px 0; }
.sg-delay-queues { display: grid; gap: 3px; margin: 6px 0; color: #475569; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10.5px; }
.sg-delay-effects { padding-left: 16px; font-size: 11px; line-height: 1.7; color: #475569; }
.sg-end-day { margin-top: 12px; padding: 12px; border: 1px solid #a5b4fc; border-radius: 9px; background: #eef2ff; }
.sg-end-day button { margin: 4px 8px 4px 0; padding: 6px 9px; border: 1px solid #4f46e5; border-radius: 6px; background: white; color: #3730a3; cursor: pointer; }
.sg-end-day button:disabled { opacity: .5; cursor: default; }
.sg-end-day select { max-width: 210px; margin: 4px; }
.sg-end-restocks label { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: 5px 0; font-size: 11px; }
.sg-end-restocks input { width: 75px; padding: 4px; border: 1px solid #a5b4fc; border-radius: 5px; }
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
