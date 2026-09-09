<script setup>
/* Auditable rule path line (#rulepath). Rendered via textContent in vanilla —
   plain text here, never HTML, so no escaping concern. */
import { useDecisionsStore } from "../stores/decisions.js";

const decisions = useDecisionsStore();
</script>

<template>
  <div class="rulepath">{{ decisions.decisionFor.rulePath }}</div>
</template>
