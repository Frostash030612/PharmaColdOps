<script setup>
/* The decision sandbox is now contextual: it opens for the event selected on
   the map/event rail instead of occupying the centre of every page load. */
import { computed } from "vue";
import { useOverlayStore } from "../stores/overlay.js";
import { useSandboxStore } from "../stores/sandbox.js";
import ScenarioList from "./ScenarioList.vue";
import RuleConfig from "./RuleConfig.vue";
import DecisionBanner from "./DecisionBanner.vue";
import Timeline from "./Timeline.vue";
import ExcursionInputs from "./ExcursionInputs.vue";
import ZonePlot from "./ZonePlot.vue";
import RulePath from "./RulePath.vue";
import RuleList from "./RuleList.vue";
import RiskIndex from "./RiskIndex.vue";
import EvidencePanel from "./EvidencePanel.vue";
import { locale, bundle } from "../i18n/index.js";

const overlay = useOverlayStore();
const sandbox = useSandboxStore();
const L = computed(() => bundle(locale.value));
</script>

<template>
  <div class="case-backdrop" @click.self="overlay.closeCase()">
    <aside class="case-drawer" role="dialog" aria-modal="true" :aria-label="L.workspace.caseTitle">
      <div class="case-drawer-head">
        <div>
          <strong>{{ L.workspace.caseTitle }}</strong>
          <span>{{ sandbox.currentRunId || L.workspace.previewCase }}</span>
        </div>
        <button class="modal-x" :title="L.modal.close" @click="overlay.closeCase()">×</button>
      </div>
      <div class="case-drawer-body">
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
        <details class="case-advanced">
          <summary>{{ L.workspace.presetsAndRules }}</summary>
          <ScenarioList />
          <RuleConfig />
        </details>
      </div>
    </aside>
  </div>
</template>
