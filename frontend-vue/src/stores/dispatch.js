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
import { ref, computed } from "vue";
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
      .then((data) => { branch.value = null; return apply(data); })
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
  const policy = ref("minimize_disruption");
  const POLICIES = ["minimize_disruption", "minimize_vehicles"];

  function previewBranch(runId, nextPolicy = policy.value) {
    if (!ready() || !runId) return Promise.resolve(null);
    if (POLICIES.includes(nextPolicy)) policy.value = nextPolicy;
    pending.value = true;
    branchError.value = "";
    needsDailyPlan.value = false;
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
      dailyPreview.value = await postJson(
        `${decisions.apiBase}/api/dispatch/plan`, batch.plan);
      return batch;
    } catch (e) {
      dailyError.value = String(e.message || e);
      return null;
    } finally {
      pending.value = false;
    }
  }

  async function confirmDailyPlan() {    if (!ready() || !dailyBatch.value) return null;
    const dispatchId = `PLAN-${Math.floor(Date.now() / 1000)}`;
    pending.value = true;
    dailyError.value = "";
    try {
      const data = await postJson(`${decisions.apiBase}/api/dispatch/runs`, {
        ...dailyBatch.value.plan,
        dispatch_id: dispatchId,
        command_id: `create-${dispatchId}`,
      });
      return apply(data);
    } catch (e) {
      dailyError.value = String(e.message || e);
      return null;
    } finally {
      pending.value = false;
    }
  }
  const setSpeed = (speed) => command("speed", { speed });

  /* Advance the operation to the simulated clock. The backend applies any
     arrivals that are due (idempotently), so this is safe to poll. */
  function tick() {
    if (!run.value || run.value.status !== "in_transit") return Promise.resolve(null);
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
      if (!run.value || run.value.status !== "in_transit") { stopClock(); return; }
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
    tick, watchClock, stopClock,
    branch, branchError, needsDailyPlan, policy, POLICIES,
    previewBranch, setPolicy,
    branchVehicle, branchCandidate, branchOverlays, branchNodeIds, incidentNodeId,
    dailyBatch, dailyPreview, dailyError,
    loadDailyPlan, confirmDailyPlan, oneClickDailyPlan, rerollDailyPlan,
  };
});
