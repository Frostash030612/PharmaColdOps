<script setup>
/* Structured queries are scoped to the displayed case/product. */
import { ref, computed, watch } from "vue";
import { conceptAnswer, classifyQuestion, isOutsideQaScope, QA_QUERY_TYPES, CASE_QUESTION_TYPES, safeEvidenceLink, decodeQaResponse, questionScopeMismatch } from "../lib/qa.js";
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
const queryType = ref("auto");
let requestId = 0;

function invalidate() {
  ++requestId;
  answer.value = "";
  evidence.value = [];
  pending.value = false;
}
watch(() => [q.value, queryType.value, sandbox.currentRunId, sandbox.current.product_id,
  decisions.apiBase, decisions.useApi, decisions.apiUp, locale.value], invalidate, { flush: "sync" });
const contextLabel = computed(() => L.value.right.qaContext
  .replace("{case}", sandbox.currentRunId || L.value.right.qaNoSelectedCase)
  .replace("{product}", sandbox.current.product_id));

async function ask() {
  const text = q.value.trim();
  if (!text && queryType.value === "auto") return;
  const id = ++requestId;
  pending.value = false;
  answer.value = "";
  evidence.value = [];
  if (isOutsideQaScope(text)) {
    answer.value = L.value.right.qaStatus_unsupported;
    source.value = "unsupported";
    return;
  }
  const type = queryType.value === "auto" ? classifyQuestion(text) : queryType.value;
  if (!type) {
    const concept = conceptAnswer(text, L.value);
    answer.value = concept || L.value.qa.fallback;
    source.value = concept ? "concept" : "clarify";
    return;
  }
  if (questionScopeMismatch(text, type, {runId: sandbox.currentRunId, productId: sandbox.current.product_id})) {
    answer.value = L.value.right.qaScopeMismatch;
    source.value = "clarify";
    return;
  }
  if (!decisions.useApi || decisions.apiUp !== true) {
    answer.value = L.value.right.qaUnavailable;
    source.value = "unavailable";
    return;
  }
  if (CASE_QUESTION_TYPES.includes(type) && !sandbox.currentRunId) {
    answer.value = L.value.right.qaNeedsCase;
    source.value = "notice";
    return;
  }
  const body = { question_type: type };
  if (CASE_QUESTION_TYPES.includes(type)) body.run_id = sandbox.currentRunId;
  if (type === "product_requirements") body.product_id = sandbox.current.product_id;
  pending.value = true;
  try {
    const res = await postJson(decisions.apiBase + "/api/qa", body);
    if (id !== requestId) return;
    const reply = decodeQaResponse(res, L.value);
    answer.value = reply.answer;
    evidence.value = reply.evidence;
    source.value = reply.source;
  } catch {
    if (id !== requestId) return;
    answer.value = L.value.right.qaUnavailable;
    source.value = "unavailable";
  } finally {
    if (id === requestId) pending.value = false;
  }
}
function onKeydown(e) { if (e.key === "Enter") ask(); }
</script>

<template>
  <div>
    <label class="qa-query-kind">{{ L.right.qaQueryLabel }}
      <select v-model="queryType" :aria-label="L.right.qaQueryLabel">
        <option value="auto">{{ L.right.qaQuery_auto }}</option>
        <option v-for="type in QA_QUERY_TYPES" :key="type" :value="type">{{ L.right[`qaQuery_${type}`] }}</option>
      </select>
    </label>
    <p class="qa-context">{{ contextLabel }}</p>
    <div class="qline">
      <input type="text" v-model="q" :placeholder="L.right.qaPlaceholder" @keydown="onKeydown">
      <button :disabled="pending" @click="ask">{{ pending ? L.right.qaLoading : L.right.qaAsk }}</button>
    </div>
    <div class="answer">{{ answer || L.right.qaInitial }}</div>
    <div v-if="answer" class="qa-source" :class="source">{{ L.right[`qaSource_${source}`] }}</div>
    <ul v-if="evidence.length" class="qa-evidence">
      <li v-for="(item, i) in evidence" :key="`${item.node_type}-${item.node_id}-${i}`">
        <b>{{ (L.right.qaNode && L.right.qaNode[item.node_type]) || item.node_type }} · {{ item.node_id }}</b><span>{{ item.summary }}</span>
        <a v-if="safeEvidenceLink(item.source_url)" :href="safeEvidenceLink(item.source_url)" target="_blank" rel="noopener noreferrer">{{ L.right.qaOpenSource }}</a>
        <details v-if="item.verified"><summary>{{ L.right.qaVerification }}</summary><small>{{ item.verified }}</small></details>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.qa-query-kind { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 6px; }
.qa-query-kind select { max-width: 100%; padding: 5px; }
.qa-context { font-size: 12px; overflow-wrap: anywhere; opacity: .8; margin: 4px 0 8px; }
.qa-evidence a, .qa-evidence small { display: block; margin-top: 4px; overflow-wrap: anywhere; }
</style>
