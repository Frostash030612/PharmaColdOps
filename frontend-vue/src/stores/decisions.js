/* decisions store — the vanilla `view` object + every API orchestration
   function, restated reactively. Semantics unchanged:

   * fresh server result only when `useApi && apiUp && serverDecisionKey ===
     live decision key` — a debounced request is in flight otherwise, so a stale
     late response naturally stops being "fresh" (no sequence counter needed).
   * /api/grid refetched only when the spec key changes (468 cells — pure slider
     drags must not refetch).
   * 4 s health re-check after a drop; reconnects and back-fills.

   decisionFor / riskFor are computed getters: server-normalised while fresh,
   else the local engine — identical to vanilla `decisionFor()`. Locale-aware:
   wording is derived from the bundle at read time, so a mid-session language
   switch re-labels the decision without re-posting to the backend. */
import { defineStore } from "pinia";
import { ref, computed, watch } from "vue";
import { useSandboxStore } from "./sandbox.js";
import { SCENARIOS } from "../data/realData.mjs";
import { locale, bundle } from "../i18n/index.js";
import {
  decisionKey as liveKey, specKey as liveSpec, eventPayload, overridePayload,
  postJson, checkHealth, normalize,
} from "../lib/api.js";
import { evaluate } from "../lib/engine.js";
import { riskInfo, causeLabel } from "../lib/risk.js";
import { cellAxes } from "../lib/zone.js";

export const useDecisionsStore = defineStore("decisions", () => {
  const sandbox = useSandboxStore();

  /* ---- state ---- */
  const apiBase = ref("");
  const useApi = ref(false);
  const apiUp = ref(null);              // null = connecting, true/false
  const serverDecision = ref(null);     // raw FastAPI /api/decide response
  const serverDecisionKey = ref(null);
  const grid = ref(null);               // server rows[row][col]
  const gridKey = ref(null);
  const gridPending = ref(null);
  const presets = ref(null);            // { scenarioId: dispositionCode }
  const routeResults = ref({});         // { "runId|algorithm": RouteOut }
  const routePending = ref(new Set());

  /* ---- live keys (what the controls currently describe) ---- */
  const liveDecisionKey = computed(() => liveKey(sandbox.current, sandbox.spec));
  const liveSpecKey = computed(() => liveSpec(sandbox.current, sandbox.spec));

  /* ---- getters ---- */
  const freshServer = computed(() => {
    if (sandbox.offlinePreview) return null;
    if (sandbox.currentRunId && sandbox.archivedRecord?.run_id === sandbox.currentRunId) return sandbox.archivedRecord;
    if (!useApi.value || apiUp.value === false) return null;
    if (serverDecision.value && serverDecisionKey.value === liveDecisionKey.value)
      return serverDecision.value;
    return null;
  });

  const decisionFor = computed(() => {
    const srv = freshServer.value;
    const L = bundle(locale.value);
    if (srv) return normalize(srv, L);
    return evaluate(sandbox.current, sandbox.spec, L);
  });

  const riskFor = computed(() => {
    const srv = freshServer.value;
    const L = bundle(locale.value);
    if (srv) {
      const n = normalize(srv, L);
      return { risk: n.risk, topCause: n.topCause };
    }
    const ri = riskInfo(sandbox.current, sandbox.spec);
    return { risk: ri.risk, topCause: causeLabel(ri.topCauseCode, L) };
  });

  /* Server grid cells while the grid matches the live spec key, else null
     (the vanilla renderZonePlot srvGrid guard). */
  const currentGrid = computed(() =>
    (!sandbox.offlinePreview && !sandbox.currentRunId && useApi.value && grid.value && gridKey.value === liveSpecKey.value) ? grid.value : null
  );

  /* ---- API orchestration (mirrors the vanilla functions) ---- */
  function syncDecision() {
    if (sandbox.offlinePreview || sandbox.currentRunId || !useApi.value || apiUp.value === false) return;
    const k = liveDecisionKey.value;
    if (serverDecisionKey.value === k) return;   // already fresh for these inputs
    postJson(apiBase.value + "/api/decide", { ...eventPayload(sandbox.current), spec_override: overridePayload(sandbox.spec) })
      .then((res) => {
        apiUp.value = true;
        serverDecision.value = res;
        serverDecisionKey.value = k;
      })
      .catch(() => apiDown());
  }

  function syncGrid() {
    if (sandbox.offlinePreview || sandbox.currentRunId || !useApi.value || apiUp.value === false) return;
    const gk = liveSpecKey.value;
    if (gridPending.value === gk) return;
    gridPending.value = gk;
    const { durations, mkts } = cellAxes(sandbox.spec);
    postJson(apiBase.value + "/api/grid", {
      product_id: sandbox.current.product_id,
      excursion_temp_c: sandbox.spec.max,
      packaging: "intact",
      stage: "transit",
      spec_override: overridePayload(sandbox.spec),
      durations,
      mkts,
    })
      .then((res) => {
        apiUp.value = true;
        grid.value = res.rows;
        gridKey.value = gk;
        gridPending.value = null;
      })
      .catch(() => { gridPending.value = null; apiDown(); });
  }

  function syncPresets() {
    if (sandbox.offlinePreview || !useApi.value) return;
    postJson(apiBase.value + "/api/decide_batch", {
      events: SCENARIOS.map((sc) => ({
        product_id: sc.product_id, excursion_temp_c: sc.excursion_temp_c,
        duration_min: sc.duration_min, mkt_c: sc.mkt_c,
        packaging: sc.packaging || "intact", stage: sc.stage || "transit",
      })),
    })
      .then((res) => {
        apiUp.value = true;
        const m = {};
        res.decisions.forEach((d, i) => { m[SCENARIOS[i].id] = d.disposition; });
        presets.value = m;
      })
      .catch(() => apiDown());
  }

  function fetchRoute(runId, algorithm) {
    const key = `${runId}|${algorithm}`;
    if (routeResults.value[key] || routePending.value.has(key)) return;
    if (sandbox.offlinePreview || !useApi.value || apiUp.value !== true) return;
    routePending.value.add(key);
    postJson(apiBase.value + "/api/route", { run_id: runId, algorithm })
      .then((res) => {
        apiUp.value = true;
        routeResults.value = { ...routeResults.value, [key]: res };
      })
      // A rejected case/destination must not mark the whole decision API down.
      .catch(() => {})
      .finally(() => routePending.value.delete(key));
  }

  function apiDown() {
    if (apiUp.value !== false) apiUp.value = false;
    scheduleRecheck();
  }

  function scheduleRecheck() {
    setTimeout(() => {
      if (sandbox.offlinePreview) return;
      if (apiUp.value === true) return;
      checkHealth(apiBase.value)
        .then(() => { apiUp.value = true; syncDecision(); syncGrid(); syncPresets(); })
        .catch(() => scheduleRecheck());
    }, 4000);
  }

  /* ---- watchers: sandbox changes → sync (debounced decision, gated grid) ---- */
  let decisionTimer = null;
  watch(liveDecisionKey, (k) => {
    if (sandbox.offlinePreview || !useApi.value || apiUp.value === false) return;
    if (serverDecisionKey.value === k) return;
    clearTimeout(decisionTimer);
    decisionTimer = setTimeout(syncDecision, 80);
  });

  watch(liveSpecKey, (k) => {
    if (sandbox.offlinePreview || !useApi.value || apiUp.value === false) return;
    if (gridKey.value === k || gridPending.value === k) return;
    syncGrid();
  });

  watch(() => sandbox.offlinePreview, (local) => {
    clearTimeout(decisionTimer);
    if (!local && useApi.value) {
      if (apiUp.value === false) scheduleRecheck();
      else { syncDecision(); syncGrid(); }
    }
  });

  /* ---- boot: read ?api= once (vanilla API_BASE) ---- */
  function init() {
    const fromUrl = new URLSearchParams(window.location.search).get("api") || "";
    useApi.value = fromUrl !== "";
    apiBase.value = fromUrl;
    if (!useApi.value) return;
    checkHealth(apiBase.value)
      .then(() => {
        apiUp.value = true;
        syncDecision();
        syncGrid();
        syncPresets();
      })
      .catch(() => { apiDown(); });
  }

  return {
    apiBase, useApi, apiUp, serverDecision, serverDecisionKey,
    grid, gridKey, gridPending, presets, routeResults, routePending,
    liveDecisionKey, liveSpecKey, freshServer, decisionFor, riskFor, currentGrid,
    syncDecision, syncGrid, syncPresets, fetchRoute, apiDown, init,
  };
});
