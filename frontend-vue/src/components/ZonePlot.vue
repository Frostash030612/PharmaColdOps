<script setup>
/* Decision boundary map (#zonePlot/#legend/#plotNote). Cells are server-fed
   while the /api/grid response matches the live spec key, else evaluated
   locally — both from the SAME cellAxes, so the 468 cells always line up. */
import { computed } from "vue";
import { useSandboxStore } from "../stores/sandbox.js";
import { useDecisionsStore } from "../stores/decisions.js";
import { zoneSvg } from "../lib/zone.js";
import { locale, bundle } from "../i18n/index.js";

const sandbox = useSandboxStore();
const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));

const zone = computed(() =>
  zoneSvg(sandbox.spec, sandbox.current, decisions.currentGrid,
          decisions.decisionFor.disposition, L.value)
);
</script>

<template>
  <div>
    <div class="zone-wrap" v-html="zone.svg"></div>
    <div class="legend" v-html="zone.legendHtml"></div>
    <div class="plot-note">{{ zone.note }}</div>
  </div>
</template>
