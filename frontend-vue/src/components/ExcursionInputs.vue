<script setup>
/* Excursion inputs — product/stage/packaging selects, the 🎲 randomizer, and the
   three linked slider+number pairs (#tempRange/#tempNum, #durRange/#durNum,
   #mktRange/#mktNum). Guard + rounding semantics are copied from the vanilla
   bind()'s link(); the number box may hold a value outside the slider's range,
   in which case the slider thumb sits at the clamped bound (as the browser does). */
import { computed } from "vue";
import { useSandboxStore, DESTINATIONS } from "../stores/sandbox.js";
import { useDecisionsStore } from "../stores/decisions.js";
import {
  PRODUCT_IDS, STAGE_IDS, PACKAGING_IDS, TEMP_RANGE,
} from "../data/products.js";
import { clamp } from "../lib/format.js";
import { auditRowHtml } from "../lib/audit.js";
import { locale, bundle } from "../i18n/index.js";

const sandbox = useSandboxStore();
const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));

/* slider bounds — recompute reactively as product / spec overrides change */
const tempLo = computed(() => TEMP_RANGE[sandbox.current.product_id][0]);
const tempHi = computed(() => TEMP_RANGE[sandbox.current.product_id][1]);
const durMax = computed(() => Math.max(10, Math.round(2.5 * sandbox.spec.allowable)));
const mktLo = computed(() => sandbox.spec.mktThreshold - 6);
const mktHi = computed(() => sandbox.spec.mktThreshold + 4);

/* range thumbs clamp; number boxes show the true value */
const cTemp = computed(() => clamp(sandbox.current.excursion_temp_c, tempLo.value, tempHi.value));
const cDur = computed(() => clamp(sandbox.current.duration_min, 0, durMax.value));
const cMkt = computed(() => clamp(sandbox.current.mkt_c, mktLo.value, mktHi.value));

function onProduct(e) { sandbox.switchProduct(e.target.value); }
function onStage(e) { sandbox.setStage(e.target.value); }
function onPackaging(e) { sandbox.setPackaging(e.target.value); }

function onTempRng(e) { sandbox.setTemp(parseFloat(e.target.value)); }
function onTempNum(e) {
  const v = parseFloat(e.target.value);
  if (!Number.isNaN(v)) sandbox.setTemp(v);
}
function onDurRng(e) { sandbox.setDur(Math.round(parseFloat(e.target.value))); }
function onDurNum(e) {
  const v = parseFloat(e.target.value);
  if (!Number.isNaN(v)) sandbox.setDur(Math.round(v));
}
function onMktRng(e) { sandbox.setMkt(parseFloat(e.target.value)); }
function onMktNum(e) {
  const v = parseFloat(e.target.value);
  if (!Number.isNaN(v)) sandbox.setMkt(v);
}

/* 🎲 randomize + audit row (the only moment the vanilla page logs a row) */
function onDestination(e) { sandbox.setDestination(e.target.value); }
function randomize() {
  sandbox.randomize();
  sandbox.pushAudit(auditRowHtml(sandbox.current, decisions.decisionFor, L.value));
}
</script>

<template>
  <div class="controls">
    <div class="ctl">
      <label>{{ L.center.product }}</label>
      <select :value="sandbox.current.product_id" @change="onProduct">
        <option v-for="id in PRODUCT_IDS" :key="id" :value="id">{{ L.products[id] }}</option>
      </select>
    </div>
    <div class="ctl">
      <label>{{ L.center.destination }}</label>
      <select :value="sandbox.current.destination_facility_id" @change="onDestination">
        <option v-for="node in DESTINATIONS" :key="node.facility_id" :value="node.facility_id">
          {{ node.name }}
        </option>
      </select>
    </div>
    <div>
      <label>{{ L.center.stage }}</label>
      <select :value="sandbox.current.stage" @change="onStage">
        <option v-for="id in STAGE_IDS" :key="id" :value="id">{{ L.stages[id] }}</option>
      </select>
    </div>
    <div class="ctl">
      <label>{{ L.center.packaging }}</label>
      <select :value="sandbox.current.packaging" @change="onPackaging">
        <option v-for="id in PACKAGING_IDS" :key="id" :value="id">{{ L.packagingOptions[id] }}</option>
      </select>
    </div>
    <div class="ctl">
      <label>&nbsp;</label>
      <button class="btn" style="height:32px" @click="randomize">{{ L.center.randomize }}</button>
    </div>

    <div class="ctl">
      <label>{{ L.center.temp }}</label>
      <div class="range-line">
        <input type="range" step="0.5" :min="tempLo" :max="tempHi" :value="cTemp" @input="onTempRng">
        <input type="number" class="num" step="0.5" :value="sandbox.current.excursion_temp_c" @input="onTempNum">
      </div>
    </div>
    <div class="ctl">
      <label>{{ L.center.dur }}</label>
      <div class="range-line">
        <input type="range" step="1" min="0" :max="durMax" :value="cDur" @input="onDurRng">
        <input type="number" class="num" step="1" :value="sandbox.current.duration_min" @input="onDurNum">
      </div>
    </div>
    <div class="ctl" style="grid-column: 1 / -1;">
      <label>{{ L.center.mkt }}</label>
      <div class="range-line">
        <input type="range" step="0.1" :min="mktLo" :max="mktHi" :value="cMkt" @input="onMktRng">
        <input type="number" class="num" step="0.1" :value="sandbox.current.mkt_c" @input="onMktNum">
      </div>
    </div>
  </div>
</template>
