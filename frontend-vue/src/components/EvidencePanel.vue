<script setup>
/* Evidence rows + decision footer (#evidence). Rows come from buildEvidence:
   semantic levels from the fresh server result when current, else computed
   locally by the same rules. */
import { computed } from "vue";
import { useSandboxStore } from "../stores/sandbox.js";
import { useDecisionsStore } from "../stores/decisions.js";
import { buildEvidence } from "../lib/evidence.js";
import { locale, bundle } from "../i18n/index.js";

const sandbox = useSandboxStore();
const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));

const ev = computed(() =>
  buildEvidence(sandbox.spec, sandbox.current, decisions.freshServer,
                decisions.decisionFor, L.value)
);
</script>

<template>
  <div class="evidence">
    <div v-for="(row, i) in ev.rows" :key="i" class="ev-row">
      <span class="k">{{ row.k }}</span>
      <span class="v">{{ row.v }}</span>
      <span v-if="row.limit" class="limit">{{ row.limit }}</span>
      <span class="chip" :class="row.level">{{ row.label }}</span>
    </div>
    <div class="ev-summary">{{ ev.summary }}</div>
    <div class="ev-reg">{{ ev.reg }}</div>
  </div>
</template>
