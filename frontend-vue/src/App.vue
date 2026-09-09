<script setup>
/* App shell — the vanilla three-column layout: presets+config (left), decision
   sandbox (center), re-routing+Q&A (right), then the audit trail and footer.
   Boot mirrors the vanilla init(): open scenario R03, then start backend mode
   if a ?api= base was supplied (decisions.init handles the health check). */
import { computed, onMounted } from "vue";
import HeaderBar from "./components/HeaderBar.vue";
import ScenarioList from "./components/ScenarioList.vue";
import RuleConfig from "./components/RuleConfig.vue";
import ExcursionInputs from "./components/ExcursionInputs.vue";
import DecisionBanner from "./components/DecisionBanner.vue";
import Timeline from "./components/Timeline.vue";
import ZonePlot from "./components/ZonePlot.vue";
import RulePath from "./components/RulePath.vue";
import RuleList from "./components/RuleList.vue";
import RiskIndex from "./components/RiskIndex.vue";
import EvidencePanel from "./components/EvidencePanel.vue";
import ReroutePanel from "./components/ReroutePanel.vue";
import QAPanel from "./components/QAPanel.vue";
import AuditTable from "./components/AuditTable.vue";
import { SCENARIOS } from "./data/realData.mjs";
import { useSandboxStore } from "./stores/sandbox.js";
import { useDecisionsStore } from "./stores/decisions.js";
import { locale, bundle } from "./i18n/index.js";

const sandbox = useSandboxStore();
const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));

onMounted(() => {
  sandbox.applyScenario(SCENARIOS[2]);   // open on R03 (retest-boundary case)
  decisions.init();                      // no-op offline; health-check + prime caches in ?api= mode
});
</script>

<template>
  <HeaderBar />

  <main>
    <!-- LEFT: presets + config -->
    <aside class="card">
      <h2>{{ L.left.presetsTitle }}</h2>
      <ScenarioList />
      <RuleConfig />
    </aside>

    <!-- CENTER: decision sandbox -->
    <section class="card">
      <h2>{{ L.center.sandboxTitle }}</h2>
      <DecisionBanner />

      <div class="section-label">{{ L.center.sectionTimeline }}</div>
      <Timeline />

      <div class="section-label">{{ L.center.sectionInputs }}</div>
      <ExcursionInputs />

      <div class="section-label">{{ L.center.sectionZone }}</div>
      <ZonePlot />

      <div class="section-label">{{ L.center.sectionRulePath }}</div>
      <RulePath />

      <div class="section-label">{{ L.center.sectionRules }}</div>
      <RuleList />

      <div class="section-label">{{ L.center.sectionRisk }} <span class="h2-note">{{ L.center.riskNote }}</span></div>
      <RiskIndex />

      <div class="section-label">{{ L.center.sectionEvidence }}</div>
      <EvidencePanel />
    </section>

    <!-- RIGHT: reroute + QA -->
    <aside class="card">
      <h2>{{ L.right.rerouteTitle }}</h2>
      <ReroutePanel />

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

  <footer>{{ L.footer }}</footer>
</template>
