<script setup>
/* Shared archive table — used inline (page bottom) and inside the centred
   history modal. Renders the load/offline/empty notes and the newest-first
   rows. Clicking a row loads that case back into the main-page sandbox, closes
   the history overlay (no-op when inline) and scrolls up to the flow panels. */
import { computed } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { useHistoryStore } from "../stores/history.js";
import { useSandboxStore } from "../stores/sandbox.js";
import { useOverlayStore } from "../stores/overlay.js";
import { locale, bundle } from "../i18n/index.js";
import { DISPO_COLOR } from "../data/products.js";
import { fmt, interp } from "../lib/format.js";
import { filterIncidents } from "../lib/incidentWorkflow.js";
import { useDispatchStore } from "../stores/dispatch.js";
import IncidentFilters from "./IncidentFilters.vue";

const decisions = useDecisionsStore();
const history = useHistoryStore();
const dispatch = useDispatchStore();
const sandbox = useSandboxStore();
const overlay = useOverlayStore();
const L = computed(() => bundle(locale.value));

const hasApi = computed(() => decisions.useApi);
const up = computed(() => decisions.apiUp === true);

function riskColor(v) {
  return v >= 70 ? "var(--scrap)" : v >= 45 ? "var(--quarantine)" : "var(--release)";
}

/* Map one raw record into display cells (semantic codes → local words). */
function cells(run) {
  const ev = run.event || {};
  const dispo = run.effective_disposition || run.disposition;
  const stageWord = L.value.stages[ev.stage] || ev.stage;
  const rt = L.value.ruleText[run.rule_no] || {};
  const causeCode = run.risk && run.risk.cause_code;
  return {
    runId: run.run_id,
    when: String(run.created_at || "").replace("T", " "),
    product: L.value.products[ev.product_id] || ev.product_id || "",
    summary: interp(L.value.history.scenTmpl, {
      stage: stageWord,
      temp: ev.excursion_temp_c == null ? '—' : fmt(ev.excursion_temp_c),
      dur: ev.duration_min == null ? '—' : fmt(ev.duration_min),
      mkt: ev.mkt_c == null ? '—' : fmt(ev.mkt_c),
    }),
    dispoLabel: run.review_status === 'pending' ? L.value.review.awaiting : L.value.dispo[dispo].label,
    color: DISPO_COLOR[dispo],
    reship: !!(run.effective_reshipment_required ?? run.reshipment_required),
    risk: run.risk ? run.risk.score : null,
    riskCause: causeCode ? (L.value.causeText[causeCode] || causeCode) : "",
    why: run.review_status === 'pending' ? L.value.review.awaiting
      : run.review_history?.length ? `${L.value.review.manualSource}: ${run.review_history.at(-1).reason}` : rt.reason || run.reason || "",
  };
}

const rows = computed(() => filterIncidents(history.runs, {
  date: history.dateFilter, hospital: history.hospitalFilter,
  status: history.statusFilter, sort: history.sort,
}, dispatch.run).map(cells));

/* Rows render pre-computed display cells; the restore must target the RAW
   backend record (event + spec live on it), so look it up again by run_id. */
function select(cell) {
  const run = history.runs.find((x) => x.run_id === cell.runId);
  if (!run) return;
  sandbox.restoreCase(run);
  overlay.closeHistory();
  overlay.openCase();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
</script>

<template>
  <IncidentFilters v-if="hasApi" />
  <p v-if="!hasApi" class="hist-note">{{ L.history.offline }}</p>
  <p v-else-if="history.error && !rows.length" class="hist-note">{{ L.history.error }}</p>
  <p v-else-if="!up && !rows.length" class="hist-note">{{ L.history.waiting }}</p>
  <p v-else-if="history.loading && !rows.length" class="hist-note">{{ L.history.loading }}</p>

  <table v-if="rows.length" class="htable">
    <thead>
      <tr>
        <th>{{ L.history.colCase }}</th>
        <th>{{ L.history.colWhen }}</th>
        <th>{{ L.history.colProduct }}</th>
        <th>{{ L.history.colExcursion }}</th>
        <th>{{ L.history.colDispo }}</th>
        <th class="num">{{ L.history.colRisk }}</th>
        <th>{{ L.history.colWhy }}</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="r in rows" :key="r.runId" class="hist-row" :title="L.history.loadHint" @click="select(r)">
        <td class="mono">{{ r.runId }}</td>
        <td class="mono">{{ r.when }}</td>
        <td>{{ r.product }}</td>
        <td>{{ r.summary }}</td>
        <td>
          <span class="tag" :style="{ background: r.color + '1a', color: r.color }">{{ r.dispoLabel }}</span>
          <span v-if="r.reship" class="hist-reship" :title="L.banner.reshipHead">{{ L.history.reshipTag }}</span>
        </td>
        <td class="num">
          <span v-if="r.risk != null" class="hist-risk" :style="{ color: riskColor(r.risk) }"
                :title="r.riskCause">{{ r.risk }}</span>
        </td>
        <td class="hist-why">{{ r.why }}</td>
      </tr>
    </tbody>
  </table>

  <p v-else-if="hasApi && up && history.loaded && !rows.length && !history.loading" class="hist-note">
    {{ L.history.empty }}
  </p>
</template>
