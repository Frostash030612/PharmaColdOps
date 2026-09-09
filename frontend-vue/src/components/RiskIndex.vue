<script setup>
/* Risk index (#riskFill/#riskVal/#causeNote): deterministic score from the same
   thresholds as the rules; root cause wording is locale data. */
import { computed } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { interp } from "../lib/format.js";
import { locale, bundle } from "../i18n/index.js";

const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));
const ri = computed(() => decisions.riskFor);
const causeNote = computed(() => interp(L.value.risk.causeLabel, { cause: ri.value.topCause }));
</script>

<template>
  <div>
    <div style="display:flex;align-items:center;gap:10px">
      <div class="riskbar" style="flex:1">
        <div :style="{ width: ri.risk + '%' }"></div>
      </div>
      <b style="font-size:13px">{{ ri.risk }}/100</b>
    </div>
    <div class="plot-note">{{ causeNote }}</div>
  </div>
</template>
