<script setup>
/* Case history (#history panel) — inline section: header (title + count +
   reload + expand-to-full-view) over the shared HistoryTable. The archive is
   the backend run log (GET /api/runs), newest-first. Clicking a table row loads
   that case back into the main-page sandbox (see HistoryTable). Offline
   (?api= absent) there is nothing to fetch — an honest note is shown. */
import { computed } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { useHistoryStore } from "../stores/history.js";
import { useOverlayStore } from "../stores/overlay.js";
import { locale, bundle } from "../i18n/index.js";
import { interp } from "../lib/format.js";
import HistoryTable from "./HistoryTable.vue";

const decisions = useDecisionsStore();
const history = useHistoryStore();
const overlay = useOverlayStore();
const L = computed(() => bundle(locale.value));

const hasApi = computed(() => decisions.useApi);
const up = computed(() => decisions.apiUp === true);
const countLabel = computed(() => interp(L.value.history.count, { n: history.count }));
</script>

<template>
  <div>
    <h2>
      {{ L.history.title }}
      <span v-if="history.count" class="hist-count">{{ countLabel }}</span>
      <span class="hist-buttons">
        <button
          v-if="hasApi"
          class="hist-refresh"
          :disabled="!up || history.loading"
          @click="history.refresh()"
        >{{ history.loading ? L.history.loading : L.history.refresh }}</button>
        <button
          v-if="hasApi"
          class="hist-refresh"
          :disabled="!up"
          :title="L.history.expand"
          @click="overlay.openHistory()"
        >{{ L.history.expand }}</button>
      </span>
    </h2>

    <HistoryTable />
  </div>
</template>
