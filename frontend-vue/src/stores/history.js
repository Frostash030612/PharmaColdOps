/* history store — the cross-session case archive behind the history panel.

   A new inbound case is entered in a modal and archived there with one explicit
   POST /api/case_close (which appends ONE record per closed case to the backend
   run log, data/audit/runs.jsonl). This store only reads the archive: it pulls
   GET /api/runs when the API comes up, and the modal / table call refresh()
   right after a successful close so the new case appears immediately.

   It also owns `scope` (today / case / all): the event rail and the map overlay
   both read it, so filtering actually removes the other excursions from the map
   instead of leaving them drawn on top of what the operator is looking at. */
import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { useDecisionsStore } from "./decisions.js";
import { useSandboxStore } from "./sandbox.js";
import { fetchRuns, postJson } from "../lib/api.js";
import { useDispatchStore } from "./dispatch.js";
import { filterIncidents, incidentStatus } from "../lib/incidentWorkflow.js";
import { localDay, resolveShownDay, isReallyToday } from "../lib/dayScope.js";

export const useHistoryStore = defineStore("history", () => {
  const decisions = useDecisionsStore();
  const sandbox = useSandboxStore();
  const dispatch = useDispatchStore();
  const dateFilter = ref("");
  const hospitalFilter = ref("");
  const statusFilter = ref("");
  const sort = ref("newest");
  const workflowPending = ref(false);
  const workflowError = ref("");
  const statusOf = (record) => incidentStatus(record, dispatch.run);

  /* ---- archive state ---- */
  const runs = ref([]);        // raw /api/runs records, newest first (server order)
  const count = ref(0);
  const loading = ref(false);
  const loaded = ref(false);   // a fetch has completed (so "no rows" = genuinely empty)
  const error = ref(false);

  /* ---- day scope (shared by the event rail and the map overlay) ----
     "today"  the day the demo clock is on (falls back to the newest recorded day)
     "case"   only the case currently loaded in the sandbox — the one the operator
              is examining — so a single excursion can be isolated on the map
     "all"    the whole archive */
  const scope = ref("today");                 // "today" | "case" | "all"

  const dayOfRun = (run) => String(run?.created_at || "").slice(0, 10);
  const days = computed(() =>
    [...new Set(runs.value.map(dayOfRun).filter(Boolean))].sort());
  const isToday = computed(() => isReallyToday(days.value));
  const shownDay = computed(() => resolveShownDay(days.value));
  const todayRuns = computed(() =>
    runs.value.filter((run) => dayOfRun(run) === shownDay.value));

  /* The case under examination. Read from the sandbox so the rail and the map
     agree with the decision sandbox about which record is open. */
  const currentRun = computed(() => {
    const id = sandbox.currentRunId;
    return id ? (runs.value.find((run) => run.run_id === id) || null) : null;
  });
  const caseRuns = computed(() => (currentRun.value ? [currentRun.value] : []));

  /* What every scoped view renders. */
  const scopeRuns = computed(() => {
    if (scope.value === "case") return caseRuns.value;
    if (scope.value === "all") return runs.value;
    return todayRuns.value;
  });
  const scopedRuns = computed(() => filterIncidents(scopeRuns.value, {
    date: dateFilter.value, hospital: hospitalFilter.value,
    status: statusFilter.value, sort: sort.value,
  }, dispatch.run));
  function resetFilters() {
    dateFilter.value = ""; hospitalFilter.value = ""; statusFilter.value = ""; sort.value = "newest";
  }
  async function changeStatus(record, status, remark) {
    if (workflowPending.value) return;
    workflowPending.value = true; workflowError.value = "";
    try {
      const updated = await postJson(`${decisions.apiBase}/api/runs/${record.run_id}/workflow`, {
        status, expected_version: record.workflow_version || 0, remark,
      });
      runs.value = runs.value.map((r) => r.run_id === record.run_id ? updated : r);
    } catch (e) { workflowError.value = String(e.message || e); refresh(); }
    finally { workflowPending.value = false; }
  }

  /* One GET /api/runs. Requests arriving mid-flight queue one follow-up so a
     close that landed while a fetch ran is never dropped. Idempotent read — a
     manual double-click is harmless. */
  let inflight = false;
  let rerun = false;
  function fetchOnce() {
    if (inflight) { rerun = true; return; }
    if (!decisions.useApi || decisions.apiUp !== true) return;
    inflight = true;
    loading.value = true;
    error.value = false;
    return fetchRuns(decisions.apiBase)
      .then((res) => {
        runs.value = res.runs;
        count.value = res.count;
      })
      .catch(() => { error.value = true; })
      .finally(() => {
        inflight = false;
        loading.value = false;
        loaded.value = true;
        if (rerun) { rerun = false; fetchOnce(); }
      });
  }

  function refresh() { return fetchOnce(); }

  /* Boot / reconnect entry. Offline mode has no archive to show. */
  function load() {
    if (!decisions.useApi) {
      runs.value = [];
      count.value = 0;
      loaded.value = false;
      error.value = false;
      return;
    }
    refresh();
  }

  /* Re-load when the API comes up (boot health-check or reconnect). */
  let timer = null;
  watch(() => decisions.apiUp, (up) => {
    if (up === true) {
      clearTimeout(timer);
      timer = setTimeout(refresh, 200);
    }
  });
  // Route acceptance and delivered checkpoints update both rail and map immediately.
  watch(() => JSON.stringify(dispatch.orders.map((o) => [o.order_id, o.status])), refresh);
  watch(() => sandbox.currentRunId, (id) => {
    if (dispatch.branch?.run_id !== id) {
      dispatch.branch = null; dispatch.branchOpen = false; dispatch.branchError = "";
    }
  });

  return { runs, count, loading, loaded, error, refresh, load,
           scope, shownDay, todayRuns, scopedRuns, days, isToday, dayOfRun,
           currentRun, caseRuns, dateFilter, hospitalFilter, statusFilter, sort,
           statusOf, resetFilters, changeStatus, workflowPending, workflowError };
});
