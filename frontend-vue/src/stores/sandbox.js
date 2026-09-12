/* sandbox store — the mutable demo state that used to be module-level `let`
   variables in the vanilla pages: product spec + current excursion event +
   timeline scrub state + re-route selection + audit rows. Mutations here drive
   the decisions store (see its watchers) exactly where the vanilla
   `renderAll()` tail used to call `maybeSync()`/`maybeSyncGrid()`. */
import { defineStore } from "pinia";
import { ref } from "vue";
import { PRODUCT_NUM, DEFAULT_EVENT, TEMP_RANGE } from "../data/products.js";
import { genProfile } from "../lib/timeline.js";

export const useSandboxStore = defineStore("sandbox", () => {
  /* ---- state ---- */
  const spec = ref({ ...PRODUCT_NUM.vaccine_2_8 });
  const current = ref({ product_id: "vaccine_2_8", ...DEFAULT_EVENT.vaccine_2_8 });

  const nowTime = ref(0);
  const playing = ref(false);
  const routeMode = ref("optimized");
  const selectedPharm = ref(null);
  const activeId = ref(null);          // highlighted scenario card (like .active)
  const currentRunId = ref(null);      // archived case currently shown, if any
  const auditRows = ref([]);           // html <tr> strings, newest first, cap 8

  let animTimer = null;

  /* ---- timeline replay ---- */
  function stopTimeline() {
    if (animTimer) { clearInterval(animTimer); animTimer = null; }
    playing.value = false;
  }

  function toggleTimeline() {
    if (playing.value) { stopTimeline(); return; }
    const start = Date.now();
    const durMs = 3600;
    playing.value = true;
    animTimer = setInterval(() => {
      const p = genProfile(current.value, spec.value);
      nowTime.value = Math.min(p.total, p.total * ((Date.now() - start) / durMs));
      if (nowTime.value >= p.total) stopTimeline();
    }, 30);
  }

  function scrubTo(totalMs) {            // total already = profile.total
    nowTime.value = totalMs;
  }

  /* ---- scenario / spec switches (vanilla switchProduct / setEvent) ---- */
  function switchProduct(pid) {
    currentRunId.value = null;
    stopTimeline();
    current.value = { product_id: pid, ...DEFAULT_EVENT[pid] };
    spec.value = { ...PRODUCT_NUM[pid] };
    nowTime.value = 0;
  }

  function applyScenario(sc) {
    currentRunId.value = null;
    stopTimeline();
    current.value = {
      product_id: sc.product_id, excursion_temp_c: sc.excursion_temp_c,
      duration_min: sc.duration_min, mkt_c: sc.mkt_c,
      packaging: sc.packaging, stage: sc.stage,
    };
    spec.value = { ...PRODUCT_NUM[sc.product_id] };
    nowTime.value = 0;
    activeId.value = sc.id;
  }

  /* ---- event input mutations ---- */
  function setStage(v) { currentRunId.value = null; current.value.stage = v; }
  function setPackaging(v) { currentRunId.value = null; current.value.packaging = v; }
  function setTemp(v) { currentRunId.value = null; current.value.excursion_temp_c = v; }
  function setDur(v) { currentRunId.value = null; current.value.duration_min = v; }
  function setMkt(v) { currentRunId.value = null; current.value.mkt_c = v; }

  /* ---- rule-config overrides ---- */
  function setAllowable(v) { if (v > 0) { currentRunId.value = null; spec.value.allowable = v; } }
  function setMktThreshold(v) { if (!Number.isNaN(v)) { currentRunId.value = null; spec.value.mktThreshold = v; } }
  function setRetestable(b) { currentRunId.value = null; spec.value.retestable = b; }
  function resetCfg() { currentRunId.value = null; spec.value = { ...PRODUCT_NUM[current.value.product_id] }; }

  /* ---- 🎲 randomize (mirror of the vanilla button) ---- */
  function randomize() {
    currentRunId.value = null;
    stopTimeline();
    const [tLo, tHi] = TEMP_RANGE[current.value.product_id];
    current.value.excursion_temp_c = Math.round((tLo + Math.random() * (tHi - tLo)) * 10) / 10;
    current.value.duration_min = Math.round(Math.random() * 2.5 * spec.value.allowable);
    current.value.mkt_c = Math.round((spec.value.mktThreshold - 4 + Math.random() * 10) * 10) / 10;
    current.value.packaging = Math.random() < 0.15 ? "compromised" : "intact";
    nowTime.value = 0;
    activeId.value = null;
  }

  /* ---- load an archived case back into the sandbox (backend run record) ----
     The main-page flow panels (timeline / banner / boundary map / rule path /
     evidence / risk) re-derive everything from event + spec, so restoring those
     two is enough to show that case's whole workflow again. */
  function restoreCase(record) {
    stopTimeline();
    const ev = record.event || {};
    const sp = record.spec || {};
    const pid = ev.product_id || current.value.product_id;
    const base = PRODUCT_NUM[pid] || PRODUCT_NUM.vaccine_2_8;
    current.value = {
      product_id: pid,
      excursion_temp_c: ev.excursion_temp_c != null ? ev.excursion_temp_c : base.max,
      duration_min: ev.duration_min != null ? ev.duration_min : base.allowable,
      mkt_c: ev.mkt_c != null ? ev.mkt_c : base.mktThreshold,
      packaging: ev.packaging || "intact",
      stage: ev.stage || "transit",
    };
    spec.value = {
      ...base,
      id: pid,
      min: sp.storage_min_c != null ? sp.storage_min_c : base.min,
      max: sp.storage_max_c != null ? sp.storage_max_c : base.max,
      allowable: sp.allowable_duration_min != null ? sp.allowable_duration_min : base.allowable,
      mktThreshold: sp.mkt_threshold_c != null ? sp.mkt_threshold_c : base.mktThreshold,
      retestable: sp.retestable != null ? sp.retestable : base.retestable,
      freezeSensitive: sp.freeze_sensitive != null ? sp.freeze_sensitive : base.freezeSensitive,
    };
    nowTime.value = 0;
    activeId.value = null;
    selectedPharm.value = null;
    currentRunId.value = record.run_id || null;
  }

  /* ---- re-route panel selection ---- */
  function setRouteMode(m) { routeMode.value = m; }
  function togglePharm(id) { selectedPharm.value = selectedPharm.value === id ? null : id; }

  /* ---- audit trail (html rows; newest first, capped at 8) ---- */
  function pushAudit(rowHtml) {
    auditRows.value = [rowHtml, ...auditRows.value].slice(0, 8);
  }

  return {
    spec, current, nowTime, playing, routeMode, selectedPharm, activeId, currentRunId, auditRows,
    switchProduct, applyScenario, restoreCase,
    setStage, setPackaging, setTemp, setDur, setMkt,
    setAllowable, setMktThreshold, setRetestable, resetCfg, randomize,
    toggleTimeline, stopTimeline, scrubTo,
    setRouteMode, togglePharm, pushAudit,
  };
});
