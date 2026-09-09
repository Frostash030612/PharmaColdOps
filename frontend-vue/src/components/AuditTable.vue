<script setup>
/* Audit trail (#auditBody). Rows are pre-built <tr> HTML strings logged on 🎲
   randomize (newest first, capped at 8), exactly like the vanilla addAudit(). */
import { computed } from "vue";
import { useSandboxStore } from "../stores/sandbox.js";
import { locale, bundle } from "../i18n/index.js";

const sandbox = useSandboxStore();
const L = computed(() => bundle(locale.value));
const body = computed(() => sandbox.auditRows.join(""));
</script>

<template>
  <div>
    <h2>{{ L.audit.title }}</h2>
    <table>
      <thead>
        <tr>
          <th>{{ L.audit.colTime }}</th>
          <th>{{ L.audit.colScenario }}</th>
          <th>{{ L.audit.colProduct }}</th>
          <th>{{ L.audit.colDispo }}</th>
          <th>{{ L.audit.colPath }}</th>
        </tr>
      </thead>
      <tbody v-html="body"></tbody>
    </table>
  </div>
</template>
