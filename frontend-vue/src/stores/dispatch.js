/* dispatch store — the ONE live delivery operation.

   Before this store the page told two unrelated stories: a fixed demo route
   drawn from a static file, and a dispatch console with real orders/stock that
   the map knew nothing about. Everything here comes from a single backend
   view (`route_view` on every dispatch response), so the map, the stop lists,
   the order table and the stock ledger cannot disagree with each other.

   Offline (no ?api=) there is no operation to show; the panel falls back to the
   committed demo plan, exactly as the decision panels fall back to the local
   engine. */
import { defineStore } from "pinia";
import { ref, reactive, computed } from "vue";
import { useDecisionsStore } from "./decisions.js";
import { postJson } from "../lib/api.js";
import data from "../data/singaporeRoutes.json";

export const useDispatchStore = defineStore("dispatch", () => {
  const decisions = useDecisionsStore();

  const run = ref(null);       // full dispatch response (state + context + route_view)
  const pending = ref(false);
  const error = ref("");       // human-readable reason the last action failed

  const live = computed(() => run.value?.route_view || null);
  const orders = computed(() => Object.values(run.value?.orders || {}));
  const vehicles = computed(() => Object.values(run.value?.vehicles || {}));
  const stock = computed(() =>
    Object.values(run.value?.available_by_lot || {}).reduce((a, b) => a + b, 0));

  function ready() {
    return decisions.useApi && decisions.apiUp === true;
  }

  function apply(data) {
    run.value = data;
    error.value = "";
    return data;
  }

  /* GET the shared operation. A 404 simply means nothing has been dispatched
     yet — that is a normal empty state, not an error worth showing. */
  function refresh() {
    if (!ready()) { run.value = null; return Promise.resolve(null); }
    return fetch(`${decisions.apiBase}/api/dispatch/active`)
      .then((r) => {
        if (r.status === 404) { run.value = null; return null; }
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json().then(apply);
      })
      .catch(() => { error.value = ""; return null; });
  }

  /* Commit one closed reshipment case into the day's plan as a BRANCH event:
     reserves stock and assigns a vehicle, unlike the stateless /api/route
     preview. `choice` ({ candidate_kind, vehicle_id }) applies the option the
     operator picked from the comparison card; without it the backend takes the
     best option under the current policy.

     There is no longer any bootstrap: with no open daily plan the backend
     answers 409 and `needsDailyPlan` is set, so the panel can tell the operator
     what to do instead of showing "HTTP 409". */
  function commitReshipment(runId, choice = null) {
    if (!ready() || !runId) return Promise.resolve(null);
    pending.value = true;
    error.value = "";
    needsDailyPlan.value = false;
    const body = { run_id: runId, policy: policy.value };
    if (choice) Object.assign(body, choice);
    return postJson(`${decisions.apiBase}/api/dispatch/reshipments`, body)
      .then((data) => { branch.value = null; branchOpen.value = false; return apply(data); })
      .catch((e) => {
        needsDailyPlan.value = e.status === 409;
        error.value = String(e.message || e);
        return null;
      })
      .finally(() => { pending.value = false; });
  }

  /* ---- branch events: what could be done, before committing to anything ----
     Read-only. This is the decision the whole module is about — change the route
     of a vehicle that is already rolling, or send another one — so the operator
     sees every option's distance, ETA and knock-on delays and picks one
     (docs/C_配送模块.md §4.2, §5 D3). */
  const branch = ref(null);          // preview response: order + candidates
  const branchError = ref("");
  const needsDailyPlan = ref(false); // last branch action was refused for 409
  /* The comparison popup is a store flag rather than component state so the
     commit path can close it, and so the "compare" button and the popup cannot
     disagree about whether a comparison is on screen. */
  const branchOpen = ref(false);
  const policy = ref("minimize_disruption");
  const POLICIES = ["minimize_disruption", "minimize_vehicles"];

  function previewBranch(runId, nextPolicy = policy.value) {
    if (!ready() || !runId) return Promise.resolve(null);
    if (POLICIES.includes(nextPolicy)) policy.value = nextPolicy;
    pending.value = true;
    branchError.value = "";
    needsDailyPlan.value = false;
    /* Open the comparison popup straight away: the operator asked to compare, so
       the popup shows either the options or the reason there are none. */
    branchOpen.value = true;
    return postJson(`${decisions.apiBase}/api/dispatch/reshipments/preview`, {
      run_id: runId, policy: policy.value,
    })
      .then((data) => { branch.value = data; return data; })
      .catch((e) => {
        branch.value = null;
        needsDailyPlan.value = e.status === 409;
        branchError.value = String(e.message || e);
        return null;
      })
      .finally(() => { pending.value = false; });
  }

  function closeBranchCompare() {
    branchOpen.value = false;
  }

  /* Switching the ranking must re-rank what is already on screen, or the policy
     selector would look like it did something when it did not. */
  function setPolicy(next) {
    policy.value = next;
    const runId = branch.value?.run_id || null;
    return runId ? previewBranch(runId, next) : Promise.resolve(null);
  }

  /* ---- what the map needs to draw a branch event -------------------------
     Kept here rather than in each map so the small map and the transport view
     cannot disagree about which lines and stops a branch event touches. */
  const NODE_ID_BY_FACILITY = Object.fromEntries(
    data.nodes.map((node) => [node.facility_id, node.node_id]));

  /// Which vehicle the overlays are about: the focused one, else the top option.
  const branchVehicle = ref(null);

  /// The hospital whose goods were affected (the case names where they go).
  const incidentNodeId = computed(() => {
    const facility = branch.value?.order?.destination_facility_id;
    return facility ? NODE_ID_BY_FACILITY[facility] ?? null : null;
  });

  const branchCandidate = computed(() => {
    const candidates = branch.value?.candidates || [];
    if (!candidates.length) return null;
    const vehicle = branchVehicle.value;
    return candidates.find((item) => item.vehicle_id === vehicle)
      || branch.value.selected_candidate || candidates[0];
  });

  /// "改道前 vs 改道后" as two drawable lines; `labelKey` is an i18n key.
  const branchOverlays = computed(() => {
    const candidate = branchCandidate.value;
    if (!candidate) return [];
    const baseline = branch.value.baselines?.[candidate.vehicle_id];
    const lines = [];
    if (baseline?.route_geojson) {
      lines.push({ id: "before", geojson: baseline.route_geojson,
                   color: "#64748b", dashed: true, labelKey: "beforeRoute" });
    }
    if (candidate.route_geojson) {
      lines.push({ id: "after", geojson: candidate.route_geojson,
                   color: "#dc2626", weight: 5, labelKey: "afterRoute" });
    }
    return lines;
  });

  /// The stop a branch event introduces, plus the affected hospital.
  const branchNodeIds = computed(() => {
    const touched = new Set();
    if (incidentNodeId.value !== null) touched.add(incidentNodeId.value);
    const candidate = branchCandidate.value;
    if (candidate?.node_sequence?.length > 1) touched.add(candidate.node_sequence[1]);
    return [...touched];
  });

  function command(path, body) {
    if (!run.value) return Promise.resolve(null);
    pending.value = true;
    error.value = "";
    return postJson(
      `${decisions.apiBase}/api/dispatch/runs/${run.value.dispatch_id}/${path}`, body)
      .then(apply)
      .catch((e) => { error.value = String(e.message || e); return null; })
      .finally(() => { pending.value = false; });
  }

  function depart() { return command("depart", { command_id: `depart-${Date.now()}` }); }

  /* ---- today's delivery plan (doc §4.1) --------------------------------
     A *batch* of ordinary hospital orders is the only input that exercises the
     multi-stop planner. Committing a reshipment case always plans exactly one
     order (the backend calls plan_delivery_orders((order,), …)), so every
     vehicle served exactly one hospital and greedy / OR-Tools / GA had nothing
     to disagree about — the structural problem in docs/C_配送模块.md §3.2.

     Two read-only steps, then one write:
       loadDailyPlan()   → GET  /api/dispatch/daily-orders  (nothing persisted)
                         → POST /api/dispatch/plan         (nothing reserved)
       confirmDailyPlan()→ POST /api/dispatch/runs          (reserves stock + vehicles)
  */
  const dailyBatch = ref(null);     // { note, plan: {orders, inventory, vehicles} }
  const dailyPreview = ref(null);   // POST /api/dispatch/plan response
  const dailyError = ref("");

  /* Operator-editable hard limits (B3, 2026-09-16).

     These are the three knobs the delivery logic actually reacts to: how many
     trucks exist, how far each one may drive in a day, and which nodes a truck
     is allowed to finish at (an allowed node makes the route OPEN — the truck
     parks there instead of driving back to the warehouse).

     ``mileageLimitKm`` is a string because it is bound to a text input where
     "empty" must stay distinguishable from "0 km"; the request builder turns it
     into metres, or null for "no cap". */
  const constraintsForm = reactive({
    max_vehicles: 3,
    max_stops_per_vehicle: 4,
    mileageLimitKm: "",
    terminal_facility_ids: [],
    // "grouped" ties one truck to one source; "pickup_delivery" lets one run
    // collect at several supply points before delivering. The value travels with
    // the plan, so switching it re-plans instead of being assumed (PDPTW step 4).
    routing_model: "grouped",
  });

  function constraintSnapshot() {
    return {
      max_vehicles: Number(constraintsForm.max_vehicles) || 0,
      max_stops_per_vehicle: Number(constraintsForm.max_stops_per_vehicle) || 0,
      mileageLimitKm: constraintsForm.mileageLimitKm,
      terminal_facility_ids: [...constraintsForm.terminal_facility_ids].sort(),
      routing_model: constraintsForm.routing_model,
    };
  }
  let absorbed = null;

  /* Take the batch's own limits, but never overwrite what the operator typed:
     fetching another batch must not silently undo "25 km per truck". */
  function absorbConstraints(fromPlan) {
    if (absorbed !== null
        && JSON.stringify(constraintSnapshot()) !== JSON.stringify(absorbed)) {
      return;
    }
    const c = fromPlan?.constraints || {};
    constraintsForm.max_vehicles = c.max_vehicles || constraintsForm.max_vehicles;
    constraintsForm.max_stops_per_vehicle =
      c.max_stops_per_vehicle || constraintsForm.max_stops_per_vehicle;
    constraintsForm.mileageLimitKm = c.mileage_limit_m
      ? String(c.mileage_limit_m / 1000) : "";
    constraintsForm.terminal_facility_ids = [...(c.terminal_facility_ids || [])];
    constraintsForm.routing_model = c.routing_model || "grouped";
    absorbed = constraintSnapshot();
  }

  /* The exact body /api/dispatch/plan and /api/dispatch/runs accept: the batch
     the backend proposed, with the operator's limits on top. */
  function planBody() {
    if (!dailyBatch.value) return null;
    const km = Number(constraintsForm.mileageLimitKm);
    return {
      ...dailyBatch.value.plan,
      constraints: {
        ...dailyBatch.value.plan.constraints,
        max_vehicles: Number(constraintsForm.max_vehicles) || null,
        max_stops_per_vehicle: Number(constraintsForm.max_stops_per_vehicle) || null,
        mileage_limit_m: constraintsForm.mileageLimitKm !== "" && km > 0
          ? Math.round(km * 1000) : null,
        // An empty selection means "no parking nodes": every truck drives back,
        // which is the legacy closed route.
        terminal_facility_ids: constraintsForm.terminal_facility_ids.length
          ? [...constraintsForm.terminal_facility_ids] : null,
        routing_model: constraintsForm.routing_model,
      },
    };
  }

  async function previewDailyPlan() {
    const body = planBody();
    if (!ready() || !body) return null;
    pending.value = true;
    dailyError.value = "";
    try {
      dailyPreview.value = await postJson(
        `${decisions.apiBase}/api/dispatch/plan`, body);
      return dailyPreview.value;
    } catch (e) {
      dailyError.value = String(e.message || e);
      return null;
    } finally {
      pending.value = false;
    }
  }

  /* Where the fleet should spend the night (B5).

     Read-only: the backend plans tomorrow's fixed orders once to learn each
     truck's first stop, then picks the allowed parking node closest to it. We
     pass today's driven distance per truck when a live operation knows it, so
     the repositioning drive is charged against the remaining mileage cap. */
  const overnightPlan = ref(null);

  async function loadOvernightPlan() {
    const body = planBody();
    if (!ready() || !body) return null;
    const facilityByNode = Object.fromEntries(
      data.nodes.map((node) => [node.node_id, node.facility_id]));

    /* Where each truck actually is NOW, not where the batch assumed it starts.

       After a day of open routes (B2) the fleet is parked at supply points, and
       that is exactly what decides tonight's repositioning. Without a live
       operation we fall back to the batch's own positions. */
    const todayDistance = {};
    const routes = live.value?.routes || [];
    const vehiclesNow = (body.vehicles || []).map((vehicle) => {
      const route = routes.find((r) => r.vehicle_id === vehicle.vehicle_id);
      if (!route) return vehicle;
      todayDistance[vehicle.vehicle_id] = Math.round((route.total_distance || 0) * 1000);
      const legs = route.legs || [];
      const lastNode = legs.length ? legs[legs.length - 1].to : null;
      const facility = lastNode === null ? null : facilityByNode[lastNode];
      return facility ? { ...vehicle, start_facility_id: facility } : vehicle;
    });

    pending.value = true;
    dailyError.value = "";
    try {
      overnightPlan.value = await postJson(
        `${decisions.apiBase}/api/dispatch/overnight-plan`,
        { ...body, vehicles: vehiclesNow, today_distance_m: todayDistance });
      return overnightPlan.value;
    } catch (e) {
      dailyError.value = String(e.message || e);
      return null;
    } finally {
      pending.value = false;
    }
  }

  async function loadDailyPlan(seed = null) {
    if (!ready()) return null;
    pending.value = true;
    dailyError.value = "";
    try {
      const query = seed === null ? "" : `?seed=${encodeURIComponent(seed)}`;
      const response = await fetch(
        `${decisions.apiBase}/api/dispatch/daily-orders${query}`);
      if (!response.ok) throw new Error("HTTP " + response.status);
      const batch = await response.json();
      dailyBatch.value = batch;
      absorbConstraints(batch.plan);
      dailyPreview.value = await postJson(
        `${decisions.apiBase}/api/dispatch/plan`, planBody());
      return batch;
    } catch (e) {
      dailyError.value = String(e.message || e);
      return null;
    } finally {
      pending.value = false;
    }
  }

  async function confirmDailyPlan() {
    const body = planBody();
    if (!ready() || !body) return null;
    const dispatchId = `PLAN-${Math.floor(Date.now() / 1000)}`;
    pending.value = true;
    dailyError.value = "";
    try {
      const data = await postJson(`${decisions.apiBase}/api/dispatch/runs`, {
        ...body,
        dispatch_id: dispatchId,
        command_id: `create-${dispatchId}`,
      });
      const applied = apply(data);
      // The batch is only a plan until the fleet rolls, and an undeparted plan
      // has no clock, no truck and no branch candidates — which looks exactly
      // like "nothing happened". Depart as part of the same button.
      await depart();
      return applied;
    } catch (e) {
      dailyError.value = String(e.message || e);
      return null;
    } finally {
      pending.value = false;
    }
  }
  const setSpeed = (speed) => command("speed", { speed });

  /* Nobody watching → freeze.

     Simulated time is derived from the wall clock, so a demo left open in a
     background tab races through the whole day and is over before anyone looks
     — which is exactly what a visitor is most likely to do. Pausing on hide and
     resuming on show makes the clock wait for its audience; the pause is the
     real one (speed 0), so the map does not silently keep moving either. */
  let hiddenSpeed = null;
  function watchVisibility() {
    if (typeof document === "undefined") return;
    document.addEventListener("visibilitychange", () => {
      if (!run.value || run.value.status !== "in_transit") return;
      if (document.hidden) {
        hiddenSpeed = run.value.clock?.speed ?? 60;
        if (hiddenSpeed > 0) setSpeed(0);
      } else if (hiddenSpeed) {
        const resume = hiddenSpeed;
        hiddenSpeed = null;
        setSpeed(resume);
      }
    });
  }

  /* ---- replaying an operation -------------------------------------------
     A finished run is history, and the panel used to fall back to the demo plan
     in silence, so a demo that ran to the end could not be watched again. Replay
     plans the SAME stored batch afresh and departs it, so nothing has to be
     invented to see it a second time. */
  const recent = ref([]);          // recent operations: [{dispatch_id, status}]
  const replayError = ref("");

  async function loadRecent() {
    if (!ready()) return null;
    try {
      const response = await fetch(`${decisions.apiBase}/api/dispatch/runs?limit=5`);
      if (!response.ok) throw new Error("HTTP " + response.status);
      recent.value = (await response.json()).runs || [];
      return recent.value;
    } catch (e) {
      replayError.value = String(e.message || e);
      return null;
    }
  }

  /// Replay the operation on screen, else the most recent one.
  async function replay(dispatchId = null) {
    const source = dispatchId || run.value?.dispatch_id || recent.value[0]?.dispatch_id;
    if (!ready() || !source) return null;
    pending.value = true;
    replayError.value = "";
    try {
      const data = await postJson(
        `${decisions.apiBase}/api/dispatch/runs/${source}/replay`,
        { speed: run.value?.clock?.speed || 60 });
      branch.value = null;
      return apply(data);
    } catch (e) {
      replayError.value = String(e.message || e);
      return null;
    } finally {
      pending.value = false;
    }
  }

  /* Advance the operation to the simulated clock. The backend applies any
     arrivals that are due (idempotently), so this is safe to poll. */
  /// True while at least one truck is still on the road — including the drive
  /// home after the last order is delivered, when the run is already "completed".
  const stillReturning = computed(() =>
    (run.value?.route_view?.routes || []).some((r) => r.track && !r.track.finished));

  function tick() {
    if (!run.value) return Promise.resolve(null);
    if (run.value.status !== "in_transit" && !stillReturning.value) {
      return Promise.resolve(null);
    }
    return postJson(
      `${decisions.apiBase}/api/dispatch/runs/${run.value.dispatch_id}/tick`, {})
      .then(apply).catch(() => null);
  }

  /* One poller for the whole app: started when an operation is under way,
     stopped as soon as it completes so a finished demo costs nothing. */
  let timer = null;
  function watchClock(intervalMs = 1000) {
    stopClock();
    timer = setInterval(() => {
      if (!run.value || (run.value.status !== "in_transit" && !stillReturning.value)) {
        stopClock();
        return;
      }
      tick();
    }, intervalMs);
  }
  function stopClock() { if (timer) { clearInterval(timer); timer = null; } }
  const deliverNext = (vehicleId) => command("deliver-next", {
    vehicle_id: vehicleId, command_id: `deliver-${vehicleId}-${Date.now()}`,
  });

  /* Testing/demo shortcut: one press = batch on screen AND an operation created.
     Kept next to the two-step path rather than replacing it, because the demo
     wants to *show* the plan before committing (doc §4.1) while a test run wants
     data immediately. */
  async function oneClickDailyPlan(seed = "today") {
    const batch = await loadDailyPlan(seed);
    if (!batch) return null;
    return confirmDailyPlan();
  }

  /* A different batch from the same generator, for eyeballing several days'
     worth quickly. Random seed only — replay it by passing the printed seed. */
  function rerollDailyPlan() {
    return loadDailyPlan(Math.floor(Math.random() * 1_000_000_000));
  }

  return {
    run, pending, error, live, orders, vehicles, stock,
    refresh, commitReshipment, depart, deliverNext, setSpeed,
    tick, watchClock, stopClock, stillReturning,
    branch, branchError, needsDailyPlan, policy, POLICIES,
    previewBranch, setPolicy, branchOpen, closeBranchCompare,
    branchVehicle, branchCandidate, branchOverlays, branchNodeIds, incidentNodeId,
    recent, replayError, loadRecent, replay, watchVisibility,
    dailyBatch, dailyPreview, dailyError,
    constraintsForm, previewDailyPlan, overnightPlan, loadOvernightPlan,
    loadDailyPlan, confirmDailyPlan, oneClickDailyPlan, rerollDailyPlan,
  };
});
