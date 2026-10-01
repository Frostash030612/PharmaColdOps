<script setup>
/* Preset scenario cards (#exList). Dot colour = backend batch disposition once
   loaded, else the local engine on the stock spec (identical result). */
import { computed } from "vue";
import { useSandboxStore } from "../stores/sandbox.js";
import { useDecisionsStore } from "../stores/decisions.js";
import { SCENARIOS } from "../data/realData.mjs";
import { PRODUCT_NUM, DISPO_COLOR } from "../data/products.js";
import { dispositionOf } from "../lib/engine.js";
import { interp, fmt } from "../lib/format.js";
import { locale, bundle } from "../i18n/index.js";

const sandbox = useSandboxStore();
const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));

const items = computed(() =>
  SCENARIOS.map((sc) => {
    const spec = PRODUCT_NUM[sc.product_id];
    const disp = (!sandbox.offlinePreview && decisions.presets && decisions.presets[sc.id])
      || dispositionOf({ ...sc }, spec);
    const stage = L.value.stages[sc.stage] || sc.stage;
    return {
      sc,
      id: sc.id,
      productName: L.value.products[sc.product_id] || sc.product_id,
      dot: DISPO_COLOR[disp],
      active: sandbox.activeId === sc.id,
      meta: interp(L.value.templates.scenarioMeta, {
        temp: fmt(sc.excursion_temp_c), dur: sc.duration_min,
        mkt: fmt(sc.mkt_c), stage,
      }),
    };
  })
);
</script>

<template>
  <div class="ex-list">
    <div v-for="it in items" :key="it.id" class="ex-item" :class="{ active: it.active }"
         @click="sandbox.applyScenario(it.sc)">
      <div class="top">
        <span class="dot" :style="{ background: it.dot }"></span>
        <span class="id">{{ it.id }}</span>
        <span class="name">{{ it.productName }}</span>
      </div>
      <div class="meta">{{ it.meta }}</div>
    </div>
  </div>
</template>
