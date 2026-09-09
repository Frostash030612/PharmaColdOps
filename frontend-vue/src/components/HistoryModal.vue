<script setup>
/* Full-view history modal (opened from the history panel's "expand" button):
   the archive centred on a blurred backdrop. Selecting a row loads that case
   back into the main-page sandbox and closes the modal. */
import { computed } from "vue";
import { useHistoryStore } from "../stores/history.js";
import { useOverlayStore } from "../stores/overlay.js";
import { locale, bundle } from "../i18n/index.js";
import { interp } from "../lib/format.js";
import HistoryTable from "./HistoryTable.vue";

const history = useHistoryStore();
const overlay = useOverlayStore();
const L = computed(() => bundle(locale.value));

const countLabel = computed(() => interp(L.value.history.count, { n: history.count }));
</script>

<template>
  <div class="modal-overlay" @click.self="overlay.closeHistory()">
    <div class="modal-panel wide" role="dialog" aria-modal="true">
      <div class="modal-head">
        <div>
          <div class="modal-title">{{ L.history.title }}</div>
          <div class="modal-sub">{{ L.history.sub }}</div>
        </div>
        <div class="hm-tools">
          <span v-if="history.count" class="hist-count">{{ countLabel }}</span>
          <button
            class="hist-refresh"
            :disabled="history.loading"
            @click="history.refresh()"
          >{{ history.loading ? L.history.loading : L.history.refresh }}</button>
          <button class="modal-x" :title="L.modal.close" @click="overlay.closeHistory()">×</button>
        </div>
      </div>

      <div class="modal-body">
        <HistoryTable />
      </div>
    </div>
  </div>
</template>
