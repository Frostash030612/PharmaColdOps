<script setup>
/* Map-first operations shell.  The dispatch map is the working surface; a
   selected incident opens its own decision sandbox in a drawer. */
import { computed, onMounted } from "vue";
import HeaderBar from "./components/HeaderBar.vue";
import ReroutePanel from "./components/ReroutePanel.vue";
import QAPanel from "./components/QAPanel.vue";
import AuditTable from "./components/AuditTable.vue";
import HistoryPanel from "./components/HistoryPanel.vue";
import NewInboundModal from "./components/NewInboundModal.vue";
import HistoryModal from "./components/HistoryModal.vue";
import IncidentList from "./components/IncidentList.vue";
import CaseDrawer from "./components/CaseDrawer.vue";
import { SCENARIOS } from "./data/realData.mjs";
import { useSandboxStore } from "./stores/sandbox.js";
import { useDecisionsStore } from "./stores/decisions.js";
import { useHistoryStore } from "./stores/history.js";
import { useOverlayStore } from "./stores/overlay.js";
import { locale, bundle } from "./i18n/index.js";

const sandbox = useSandboxStore();
const decisions = useDecisionsStore();
const history = useHistoryStore();
const overlay = useOverlayStore();
const L = computed(() => bundle(locale.value));

onMounted(() => {
  sandbox.applyScenario(SCENARIOS[2]);   // open on R03 (retest-boundary case)
  decisions.init();                      // no-op offline; health-check + prime caches in ?api= mode
  history.load();                        // offline → clears; ?api= → pulls /api/runs when the API is up
});
</script>

<template>
  <HeaderBar />

  <main class="operations-layout">
    <section class="card operations-map">
      <h2>{{ L.workspace.mapTitle }}</h2>
      <ReroutePanel primary />
    </section>
    <aside class="card operations-side">
      <IncidentList />
      <div class="qa">
        <h2>{{ L.right.qaTitle }} <span class="h2-note">{{ L.right.qaNote }}</span></h2>
        <QAPanel />
      </div>
    </aside>
  </main>

  <section class="audit">
    <div class="card">
      <AuditTable />
    </div>
  </section>

  <section class="audit">
    <div class="card">
      <HistoryPanel />
    </div>
  </section>

  <footer>{{ L.footer }}</footer>

  <!-- centred modals (blurred backdrop) — only one is open at a time -->
  <NewInboundModal v-if="overlay.newInboundOpen" />
  <HistoryModal v-if="overlay.historyOpen" />
  <CaseDrawer v-if="overlay.caseOpen" />
</template>
