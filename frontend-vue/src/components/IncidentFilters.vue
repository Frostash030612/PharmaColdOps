<script setup>
import { computed } from "vue";
import { useHistoryStore } from "../stores/history.js";
import { locale, bundle } from "../i18n/index.js";
import routes from "../data/singaporeRoutes.json";
const history = useHistoryStore();
const L = computed(() => bundle(locale.value));
const hospitals = routes.nodes.filter((n) => n.role === "customer");
</script>
<template>
  <div class="incident-filters">
    <label>{{ L.workflow.date }}<input v-model="history.dateFilter" type="date" @change="history.scope = 'all'" /></label>
    <label>{{ L.workflow.hospital }}<select v-model="history.hospitalFilter"><option value="">{{ L.workflow.all }}</option><option v-for="node in hospitals" :key="node.facility_id" :value="node.facility_id">{{ node.name }}</option></select></label>
    <label>{{ L.workflow.status }}<select v-model="history.statusFilter"><option value="">{{ L.workflow.all }}</option><option v-for="status in ['pending', 'processing', 'handled', 'closed']" :key="status" :value="status">{{ L.workflow[status] }}</option></select></label>
    <label>{{ L.workflow.sort }}<select v-model="history.sort"><option value="newest">{{ L.workflow.newest }}</option><option value="oldest">{{ L.workflow.oldest }}</option></select></label>
    <button @click="history.resetFilters()">{{ L.workflow.reset }}</button>
  </div>
</template>
<style scoped>
.incident-filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 10px 0; }
.incident-filters label { display: grid; gap: 3px; font-size: 12px; min-width: 0; }
.incident-filters input, .incident-filters select { min-width: 0; width: 100%; box-sizing: border-box; }
</style>
