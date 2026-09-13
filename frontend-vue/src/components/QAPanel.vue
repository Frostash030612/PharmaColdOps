<script setup>
/* Structured live KG questions in API mode, with the original local FAQ fallback. */
import { ref, computed } from "vue";
import { askKG, classifyQuestion } from "../lib/qa.js";
import { postJson } from "../lib/api.js";
import { useDecisionsStore } from "../stores/decisions.js";
import { useSandboxStore } from "../stores/sandbox.js";
import { locale, bundle } from "../i18n/index.js";

const decisions = useDecisionsStore();
const sandbox = useSandboxStore();
const L = computed(() => bundle(locale.value));
const q = ref("");
const answer = ref("");
const evidence = ref([]);
const source = ref("concept");
const pending = ref(false);
let requestId = 0;

async function ask() {
  const text = q.value.trim();
  if (!text) return;
  const id = ++requestId;
  evidence.value = [];
  const type = classifyQuestion(text);
  if (!type || !decisions.useApi) {
    answer.value = askKG(text, L.value);
    source.value = "concept";
    return;
  }
  if (decisions.apiUp !== true) {
    answer.value = `${askKG(text, L.value)} ${L.value.right.qaOfflineNote}`;
    source.value = "fallback";
    return;
  }
  if (["why_disposition", "audit_chain", "cause_context"].includes(type) && !sandbox.currentRunId) {
    answer.value = L.value.right.qaNeedsCase;
    source.value = "notice";
    return;
  }
  const body = { question_type: type };
  if (["why_disposition", "audit_chain", "cause_context"].includes(type)) body.run_id = sandbox.currentRunId;
  if (type === "product_requirements") body.product_id = sandbox.current.product_id;
  pending.value = true;
  try {
    const res = await postJson(decisions.apiBase + "/api/qa", body);
    if (id !== requestId) return;
    /* The API reports an outcome class per answer (proposal §6.5): only the
       system wording is localised here — the answer/evidence text itself
       quotes the English source documents and is shown verbatim. */
    const status = res.status || "ok";
    if (status === "ok") {
      answer.value = res.answer;
      evidence.value = res.evidence || [];
      source.value = "live";
    } else if (status === "insufficient_evidence") {
      answer.value = `${res.answer} ${L.value.right.qaStatus_insufficient_evidence}`;
      evidence.value = res.evidence || [];
      source.value = "insufficient";
    } else {
      answer.value = L.value.right[`qaStatus_${status}`] || res.answer;
      evidence.value = [];
      source.value = status === "unsupported" ? "unsupported" : "notice";
    }
  } catch {
    if (id !== requestId) return;
    answer.value = `${askKG(text, L.value)} ${L.value.right.qaOfflineNote}`;
    source.value = "fallback";
  } finally {
    if (id === requestId) pending.value = false;
  }
}
function onKeydown(e) { if (e.key === "Enter") ask(); }
</script>

<template>
  <div>
    <div class="qline">
      <input type="text" v-model="q" :placeholder="L.right.qaPlaceholder" @keydown="onKeydown">
      <button :disabled="pending" @click="ask">{{ pending ? L.right.qaLoading : L.right.qaAsk }}</button>
    </div>
    <div class="answer">{{ answer || L.right.qaInitial }}</div>
    <div v-if="answer && decisions.useApi" class="qa-source" :class="source">{{ L.right[`qaSource_${source}`] }}</div>
    <ul v-if="evidence.length" class="qa-evidence">
      <li v-for="(item, i) in evidence" :key="`${item.node_type}-${item.node_id}-${i}`">
        <b>{{ (L.right.qaNode && L.right.qaNode[item.node_type]) || item.node_type }} · {{ item.node_id }}</b><span>{{ item.summary }}</span>
      </li>
    </ul>
  </div>
</template>
