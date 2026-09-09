<script setup>
/* Rule-config overrides (#allowableInput / #mktThresholdInput / #retestableInput
   / #resetCfg). Guard semantics copied from the vanilla bind(): an empty /
   non-numeric box silently keeps the previous spec value. */
import { computed } from "vue";
import { useSandboxStore } from "../stores/sandbox.js";
import { locale, bundle } from "../i18n/index.js";

const sandbox = useSandboxStore();
const L = computed(() => bundle(locale.value));

function onAllowable(e) {
  const v = parseFloat(e.target.value);
  if (v > 0) sandbox.setAllowable(v);
}
function onMktThreshold(e) {
  const v = parseFloat(e.target.value);
  if (!Number.isNaN(v)) sandbox.setMktThreshold(v);
}
function onRetestable(e) {
  sandbox.setRetestable(e.target.checked);
}
</script>

<template>
  <div class="cfg">
    <div class="lbl">{{ L.left.cfgTitle }}</div>
    <div class="cfg-row">
      <span>{{ L.left.cfgAllowable }}</span>
      <input type="number" step="1" :value="sandbox.spec.allowable" @input="onAllowable">
    </div>
    <div class="cfg-row">
      <span>{{ L.left.cfgMkt }}</span>
      <input type="number" step="0.5" :value="sandbox.spec.mktThreshold" @input="onMktThreshold">
    </div>
    <div class="cfg-row">
      <span>{{ L.left.cfgRetestable }}</span>
      <input type="checkbox" :checked="sandbox.spec.retestable" @change="onRetestable">
    </div>
    <button class="btn" @click="sandbox.resetCfg()">{{ L.left.cfgReset }}</button>
  </div>
</template>
