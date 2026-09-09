<script setup>
/* Decision banner (#banner): coloured disposition band + reason + reshipment.
   Badge text is locale data (EN first letter vs ZH full word). */
import { computed } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { DISPO_COLOR } from "../data/products.js";
import { locale, bundle } from "../i18n/index.js";

const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));
const d = computed(() => decisions.decisionFor);
const badge = computed(() => L.value.dispo[d.value.disposition].badge);
const label = computed(() => L.value.dispo[d.value.disposition].label);
</script>

<template>
  <div class="dispo-banner" :style="{ background: DISPO_COLOR[d.disposition] }">
    <div class="dispo-badge">{{ badge }}</div>
    <div>
      <div class="big">{{ label }}</div>
      <div class="why">{{ d.reason }}</div>
    </div>
    <div class="reship">
      {{ L.banner.reshipHead }}<br>
      <b>{{ d.reshipment ? L.banner.reshipReq : L.banner.reshipNo }}</b>
    </div>
  </div>
</template>
