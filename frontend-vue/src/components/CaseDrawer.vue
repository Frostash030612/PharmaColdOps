<script setup>
/* The decision sandbox is now contextual: it opens for the event selected on
   the map/event rail instead of occupying the centre of every page load. */
import { computed, onBeforeUnmount } from "vue";
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
import CaseActions from "./CaseActions.vue";
import M4Panel from './M4Panel.vue';
import M2Panel from './M2Panel.vue';
import ReviewPanel from './ReviewPanel.vue';
import EventV2Panel from './EventV2Panel.vue';
import { useDecisionsStore } from '../stores/decisions.js';
import { locale, bundle } from "../i18n/index.js";

const overlay = useOverlayStore();
const sandbox = useSandboxStore();
const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));
function close() { sandbox.exitOfflinePreview(); overlay.closeCase(); }
onBeforeUnmount(sandbox.exitOfflinePreview);
</script>

<template>
  <div class="case-backdrop" @click.self="close">
    <aside class="case-drawer" role="dialog" aria-modal="true" :aria-label="sandbox.offlinePreview ? L.localSandbox.title : L.workspace.caseTitle">
      <div class="case-drawer-head">
        <div>
          <strong>{{ sandbox.offlinePreview ? L.localSandbox.title : L.workspace.caseTitle }}</strong>
          <span>{{ sandbox.offlinePreview ? L.localSandbox.badge : sandbox.currentRunId || L.workspace.previewCase }}</span>
        </div>
        <button class="modal-x" :title="L.modal.close" @click="close">×</button>
      </div>
      <div class="case-drawer-body">
        <p v-if="sandbox.offlinePreview" class="local-sandbox-note">{{ L.localSandbox.note }}</p>
        <CaseActions v-else />
        <ReviewPanel v-if="!sandbox.offlinePreview && sandbox.currentRunId" />
        <EventV2Panel v-if="sandbox.currentRunId" :product-id="sandbox.archivedRecord?.event.product_id"
          :model-value="sandbox.archivedRecord?.event_v2_context" :saved="sandbox.archivedRecord?.event_v2_assessment" readonly />
        <EventV2Panel v-else-if="sandbox.offlinePreview" :product-id="sandbox.current.product_id" offline />
        <details v-if="sandbox.offlinePreview" open class="case-advanced">
          <summary>{{ L.workspace.presetsAndRules }}</summary><ScenarioList /><RuleConfig />
        </details>
        <p v-if="sandbox.currentRunId" class="section-label">{{ L.review.original }}</p>
        <DecisionBanner v-if="sandbox.archivedRecord?.automatic_assessment_available !== false || !sandbox.currentRunId" />
        <p v-else>{{ L.review.unassessed }}</p>
        <div class="section-label">{{ L.center.sectionTimeline }}</div>
        <M2Panel v-if="sandbox.currentRunId && sandbox.archivedRecord?.temperature_context"
          :product-id="sandbox.archivedRecord.event.product_id" :model-value="sandbox.archivedRecord.temperature_context"
          :saved="sandbox.archivedRecord.temperature_assessment" readonly />
        <Timeline v-else />
        <template v-if="sandbox.archivedRecord?.automatic_assessment_available !== false || !sandbox.currentRunId">
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
        <M4Panel :model-value="sandbox.current.ml_contexts || []" @update:model-value="sandbox.current.ml_contexts = $event"
          :saved="sandbox.currentRunId ? sandbox.archivedRecord?.ml_assessments || [] : []"
          :readonly="!!sandbox.currentRunId" :offline="sandbox.offlinePreview || !decisions.useApi || decisions.apiUp !== true" />
        <div class="section-label">{{ L.center.sectionEvidence }}</div>
        <EvidencePanel />
        </template>
        <details v-if="!sandbox.offlinePreview" class="case-advanced">
          <summary>{{ L.workspace.presetsAndRules }}</summary>
          <ScenarioList />
          <RuleConfig />
        </details>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.local-sandbox-note { padding: 12px; border-radius: 8px; border: 1px solid #93c5fd; background: #eff6ff; color: #1e40af; }
</style>
