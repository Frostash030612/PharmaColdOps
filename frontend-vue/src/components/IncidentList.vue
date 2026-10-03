<script setup>
/* Map-first event rail. Archived quality assessments carry independent,
   durable processing progress; status colours are not disposition colours.

   The scope ("today" / "case" / "all") lives in the history store rather than
   here, because the map overlay in ReroutePanel draws the same set of cases:
   keeping one source of truth is what stops other excursions from staying on
   the map after the operator narrows the view. */
import { computed } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { useHistoryStore } from "../stores/history.js";
import { useSandboxStore } from "../stores/sandbox.js";
import { useOverlayStore } from "../stores/overlay.js";
import routes from "../data/singaporeRoutes.json";
import { locale, bundle } from "../i18n/index.js";
import { interp } from "../lib/format.js";
import { localDay } from "../lib/dayScope.js";
import { DISPO_COLOR } from "../data/products.js";
import { STATUS_COLORS } from "../lib/incidentWorkflow.js";
import IncidentFilters from "./IncidentFilters.vue";

const decisions = useDecisionsStore();
const history = useHistoryStore();
const sandbox = useSandboxStore();
const overlay = useOverlayStore();
const L = computed(() => bundle(locale.value));
const names = Object.fromEntries(routes.nodes.map((n) => [n.facility_id, n.name]));

function shape(run) {
  const ev = run.event || {};
  return {
    run,
    id: run.run_id,
    facility: names[run.effective_destination_facility_id || ev.destination_facility_id] || run.effective_destination_facility_id || ev.destination_facility_id || L.value.workspace.unknownFacility,
    product: L.value.products[ev.product_id] || ev.product_id,
    temp: ev.excursion_temp_c ?? '—',
    duration: ev.duration_min ?? '—',
    disposition: run.review_status === 'pending' ? L.value.review.awaiting : L.value.dispo[run.effective_disposition || run.disposition]?.label || run.disposition,
    dispositionColor: DISPO_COLOR[run.effective_disposition || run.disposition],
    color: STATUS_COLORS[history.statusOf(run)],
    status: L.value.workflow[history.statusOf(run)],
    location: names[ev.facility_id] || ev.facility_id || L.value.workflow.unknownLocation,
    when: String(run.created_at || "").replace("T", " "),
  };
}

/* Scope and day resolution come from the store (shared with the map). */
const events = computed(() => history.scopedRuns.map(shape));
/* The "this case" scope has nothing to show when no record is loaded. */
const caseScopeEmpty = computed(() => history.scope === "case" && !history.currentRun);

/* Button labels carry the date and count, so no one has to guess which day is
   on screen. */
const labels = computed(() => {
  const l = L.value.workspace;
  return {
    today: history.isToday
      ? l.eventsToday
      : interp(l.eventsTodayLatest, { date: history.shownDay }),
    case: history.currentRun ? l.eventsCase : l.eventsCaseNone,
    all: interp(l.eventsAll, { n: history.runs.length }),
  };
});

/* Explain an empty "today" tab instead of leaving a bare empty rail. */
const todayFallback = computed(() =>
  interp(L.value.workspace.eventsTodayFallback, { date: localDay(new Date()) }));

function openEvent(item) {
  sandbox.restoreCase(item.run);
  overlay.openCase();
}
</script>

<template>
  <div class="incident-head">
    <div>
      <strong>{{ L.workspace.eventsTitle }}</strong>
      <p>{{ L.workspace.eventsNote }}</p>
    </div>
    <button v-if="decisions.useApi" :disabled="history.loading || decisions.apiUp !== true"
      @click="history.refresh()">{{ L.history.refresh }}</button>
  </div>

  <IncidentFilters v-if="decisions.useApi" />
  <!-- Scope. Filters the event rail AND the map overlay (ReroutePanel reads the
       same store value). Shown even with no archive, so the operator can tell
       "nothing happened today" apart from "history is not loaded". -->
  <div v-if="decisions.useApi" class="incident-scope" role="group" :aria-label="L.workspace.eventsTitle">
    <button :class="{ on: history.scope === 'today' }" @click="history.scope = 'today'">{{ labels.today }}</button>
    <button :class="{ on: history.scope === 'case' }" :title="history.currentRun ? history.currentRun.run_id : L.workspace.eventsCaseNone"
      @click="history.scope = 'case'">{{ labels.case }}</button>
    <button :class="{ on: history.scope === 'all' }" @click="history.scope = 'all'">{{ labels.all }}</button>
  </div>

  <p v-if="!decisions.useApi" class="incident-empty">{{ L.history.offline }}</p>
  <p v-else-if="history.loading && !history.runs.length" class="incident-empty">{{ L.history.loading }}</p>
  <p v-else-if="history.error && !history.runs.length" class="incident-empty">{{ L.history.error }}</p>
  <p v-else-if="history.loaded && !history.runs.length" class="incident-empty">{{ L.history.empty }}</p>
  <!-- "This case" selected but no record is open: say so instead of showing an
       empty rail that looks broken. -->
  <div v-else-if="caseScopeEmpty" class="incident-empty">
    <p>{{ L.workspace.eventsNoneCase }}</p>
    <button class="incident-more" @click="history.scope = 'today'">{{ labels.today }}</button>
  </div>
  <div v-else-if="!events.length" class="incident-empty">
    <p>{{ L.workflow.noMatches }}</p>
    <button class="incident-more" @click="history.resetFilters(); history.scope = 'all'">{{ L.workflow.reset }}</button>
  </div>

  <div v-else class="incident-list">
    <button v-for="item in events" :key="item.id" class="incident-card"
      :class="{ active: sandbox.currentRunId === item.id }" @click="openEvent(item)">
      <span class="incident-dot" :style="{ background: item.color }"></span>
      <span class="incident-copy">
        <span class="incident-row"><b>{{ item.facility }}</b><em>{{ item.status }}</em></span>
        <small>{{ L.workflow.location }}: {{ item.location }}</small>
        <span>{{ item.product }} · {{ item.temp }} °C / {{ item.duration }} {{ L.workspace.minutes }}</span>
        <span class="incident-row"><small>{{ item.when }}</small><strong :style="{ color: item.dispositionColor }">{{ item.disposition }}</strong></span>
      </span>
    </button>
  </div>
</template>
