<script setup>
/* Compliance Q&A (#qaInput/#qaAsk/#qaAnswer) — knowledge-graph concept mockup. */
import { ref, computed } from "vue";
import { askKG } from "../lib/qa.js";
import { locale, bundle } from "../i18n/index.js";

const L = computed(() => bundle(locale.value));
const q = ref("");
const answer = ref("");

function ask() {
  const text = q.value.trim();
  if (!text) return;
  answer.value = askKG(text, L.value);
}
function onKeydown(e) { if (e.key === "Enter") ask(); }
</script>

<template>
  <div>
    <div class="qline">
      <input type="text" v-model="q" :placeholder="L.right.qaPlaceholder" @keydown="onKeydown">
      <button @click="ask">{{ L.right.qaAsk }}</button>
    </div>
    <div class="answer">{{ answer || L.right.qaInitial }}</div>
  </div>
</template>
