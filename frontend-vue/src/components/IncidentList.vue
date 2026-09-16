<script setup>
/* Map-first event rail.  The archive is currently the only durable event data
   source, so every item here is a closed case.  Status-specific colours stay a
   second-batch task until the backend exposes a processing-status contract. */
import { computed } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { useHistoryStore } from "../stores/history.js";
import { useSandboxStore } from "../stores/sandbox.js";
import { useOverlayStore } from "../stores/overlay.js";
import routes from "../data/singaporeRoutes.json";
import { locale, bundle } from "../i18n/index.js";
import { DISPO_COLOR } from "../data/products.js";

const decisions = useDecisionsStore();
const history = useHistoryStore();
const sandbox = useSandboxStore();
const overlay = useOverlayStore();
const L = computed(() => bundle(locale.value));
const names = Object.fromEntries(routes.nodes.map((n) => [n.facility_id, n.name]));

const events = computed(() => history.runs.map((run) => {
  const ev = run.event || {};
  return {
    run,
    id: run.run_id,
    facility: names[ev.destination_facility_id] || ev.destination_facility_id || L.value.workspace.unknownFacility,
    product: L.value.products[ev.product_id] || ev.product_id,
    temp: ev.excursion_temp_c,
    duration: ev.duration_min,
    disposition: L.value.dispo[run.disposition]?.label || run.disposition,
    color: DISPO_COLOR[run.disposition] || "#dc2626",
    when: String(run.created_at || "").replace("T", " "),
  };
}));

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

  <p v-if="!decisions.useApi" class="incident-empty">{{ L.history.offline }}</p>
  <p v-else-if="history.loading && !events.length" class="incident-empty">{{ L.history.loading }}</p>
  <p v-else-if="history.error && !events.length" class="incident-empty">{{ L.history.error }}</p>
  <p v-else-if="history.loaded && !events.length" class="incident-empty">{{ L.history.empty }}</p>

  <div v-if="events.length" class="incident-list">
    <button v-for="item in events" :key="item.id" class="incident-card"
      :class="{ active: sandbox.currentRunId === item.id }" @click="openEvent(item)">
      <span class="incident-dot" :style="{ background: item.color }"></span>
      <span class="incident-copy">
        <span class="incident-row"><b>{{ item.facility }}</b><em>{{ L.workspace.closed }}</em></span>
        <span>{{ item.product }} · {{ item.temp }} °C / {{ item.duration }} {{ L.workspace.minutes }}</span>
        <span class="incident-row"><small>{{ item.when }}</small><strong :style="{ color: item.color }">{{ item.disposition }}</strong></span>
      </span>
    </button>
  </div>
</template>
