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

  /* Commit one closed reshipment case into the operation: reserves stock and
     assigns a vehicle, unlike the stateless /api/route preview. */
  function commitReshipment(runId) {
    if (!ready() || !runId) return Promise.resolve(null);
    pending.value = true;
    error.value = "";
    return postJson(`${decisions.apiBase}/api/dispatch/reshipments`, { run_id: runId })
      .then(apply)
      .catch((e) => { error.value = String(e.message || e); return null; })
      .finally(() => { pending.value = false; });
  }

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

  async function confirmDailyPlan() {
    if (!ready() || !dailyBatch.value) return null;
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

  return {
    run, pending, error, live, orders, vehicles, stock,
    refresh, commitReshipment, depart, deliverNext, setSpeed,
    tick, watchClock, stopClock,
    dailyBatch, dailyPreview, dailyError, loadDailyPlan, confirmDailyPlan,
  };
});
