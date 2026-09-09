<script setup>
/* The six rules in priority order (#rulesList), the hit rule highlighted. */
import { computed } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { locale, bundle } from "../i18n/index.js";

const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));
const ruleNo = computed(() => decisions.decisionFor.ruleNo);
</script>

<template>
  <ul class="rules-list">
    <li v-for="(rule, i) in L.rules" :key="i" :class="{ fired: i + 1 === ruleNo }">
      <span class="no">{{ i + 1 }}</span>{{ rule }}
    </li>
  </ul>
</template>
