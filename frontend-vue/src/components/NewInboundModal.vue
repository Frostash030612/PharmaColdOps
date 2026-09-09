<script setup>
/* New-inbound modal (opened from the header "+"). Everything the user fills in
   lives in LOCAL draft refs — the main-page sandbox is untouched until the
   "Close & archive" button posts /api/case_close and the returned record is
   restored into the sandbox. The preview is computed live from the draft with
   the same pure engine/risk libs the page uses, so it reads exactly how the
   case will be judged. */
import { computed, ref } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { useHistoryStore } from "../stores/history.js";
import { useSandboxStore } from "../stores/sandbox.js";
import { useOverlayStore } from "../stores/overlay.js";
import {
  PRODUCT_NUM, PRODUCT_IDS, STAGE_IDS, PACKAGING_IDS, DEFAULT_EVENT,
  TEMP_RANGE, DISPO_COLOR,
} from "../data/products.js";
import { evaluate } from "../lib/engine.js";
import { riskInfo, causeLabel } from "../lib/risk.js";
import { eventPayload, overridePayload, postJson } from "../lib/api.js";
import { clamp, interp } from "../lib/format.js";
import { locale, bundle } from "../i18n/index.js";

const decisions = useDecisionsStore();
const history = useHistoryStore();
const sandbox = useSandboxStore();
const overlay = useOverlayStore();
const L = computed(() => bundle(locale.value));

/* ---- draft (local; sandbox stays untouched until archive) ---- */
function defaultsOf(pid) {
  return {
    ev: { product_id: pid, ...DEFAULT_EVENT[pid] },
    spec: { ...PRODUCT_NUM[pid] },
  };
}
const initPid = (sandbox.current.product_id in PRODUCT_NUM)
  ? sandbox.current.product_id : "vaccine_2_8";
const init = defaultsOf(initPid);
const ev = ref(init.ev);
const spec = ref(init.spec);

const archiving = ref(false);
const error = ref(false);
const showRules = ref(false);
const remark = ref("");

const up = computed(() => decisions.apiUp === true);

/* ---- controls ----- */
function onProduct(e) {
  const d = defaultsOf(e.target.value);
  ev.value = d.ev;
  spec.value = d.spec;
}
function onStage(e) { ev.value.stage = e.target.value; }
function onPackaging(e) { ev.value.packaging = e.target.value; }

function onNum(k, e, round = false) {
  const v = parseFloat(e.target.value);
  if (Number.isNaN(v)) return;
  ev.value[k] = round ? Math.round(v) : v;
}
function onSpecNum(k, e) {
  const v = parseFloat(e.target.value);
  if (!Number.isNaN(v)) spec.value[k] = v;
}
function resetSpec() { spec.value = { ...PRODUCT_NUM[ev.value.product_id] }; }

/* slider geometry (same derivation as ExcursionInputs, over the draft) */
const tempLo = computed(() => TEMP_RANGE[ev.value.product_id][0]);
const tempHi = computed(() => TEMP_RANGE[ev.value.product_id][1]);
const durMax = computed(() => Math.max(10, Math.round(2.5 * spec.value.allowable)));
const mktLo = computed(() => spec.value.mktThreshold - 6);
const mktHi = computed(() => spec.value.mktThreshold + 4);
const cTemp = computed(() => clamp(ev.value.excursion_temp_c, tempLo.value, tempHi.value));
const cDur = computed(() => clamp(ev.value.duration_min, 0, durMax.value));
const cMkt = computed(() => clamp(ev.value.mkt_c, mktLo.value, mktHi.value));

/* ---- live preview (how the draft will be judged) ---- */
const d = computed(() => evaluate(ev.value, spec.value, L.value));
const risk = computed(() => {
  const ri = riskInfo(ev.value, spec.value);
  return {
    score: ri.risk,
    color: ri.risk >= 70 ? "var(--scrap)" : ri.risk >= 45 ? "var(--quarantine)" : "var(--release)",
  };
});
const causeNote = computed(() =>
  interp(L.value.risk.causeLabel, { cause: causeLabel(riskInfo(ev.value, spec.value).topCauseCode, L.value) })
);
const badge = computed(() => L.value.dispo[d.value.disposition].badge);
const label = computed(() => L.value.dispo[d.value.disposition].label);

/* ---- actions ---- */
function cancel() {
  if (archiving.value) return;
  overlay.closeNewInbound();
}

async function archive() {
  if (archiving.value || decisions.apiUp !== true) return;
  archiving.value = true;
  error.value = false;
  try {
    const res = await postJson(decisions.apiBase + "/api/case_close", {
      ...eventPayload(ev.value),
      spec_override: overridePayload(spec.value),
      started_at: new Date().toISOString(),
      remark: remark.value.trim() || null,
    });
    overlay.closeNewInbound();
    sandbox.restoreCase(res);        // now the whole flow appears on the page
    history.refresh();               // archive panel picks up the new record
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch {
    error.value = true;
  } finally {
    archiving.value = false;
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="cancel">
    <div class="modal-panel" role="dialog" aria-modal="true">
      <div class="modal-head">
        <div>
          <div class="modal-title">{{ L.newInbound.title }}</div>
          <div class="modal-sub">{{ L.newInbound.sub }}</div>
        </div>
        <button class="modal-x" :title="L.modal.close" :disabled="archiving" @click="cancel">×</button>
      </div>

      <div class="modal-body ni-body">
        <div class="controls">
          <div class="ctl">
            <label>{{ L.center.product }}</label>
            <select :value="ev.product_id" @change="onProduct">
              <option v-for="id in PRODUCT_IDS" :key="id" :value="id">{{ L.products[id] }}</option>
            </select>
          </div>
          <div class="ctl">
            <label>{{ L.center.stage }}</label>
            <select :value="ev.stage" @change="onStage">
              <option v-for="id in STAGE_IDS" :key="id" :value="id">{{ L.stages[id] }}</option>
            </select>
          </div>
          <div class="ctl">
            <label>{{ L.center.packaging }}</label>
            <select :value="ev.packaging" @change="onPackaging">
              <option v-for="id in PACKAGING_IDS" :key="id" :value="id">{{ L.packagingOptions[id] }}</option>
            </select>
          </div>

          <div class="ctl">
            <label>{{ L.center.temp }}</label>
            <div class="range-line">
              <input type="range" step="0.5" :min="tempLo" :max="tempHi" :value="cTemp"
                     @input="onNum('excursion_temp_c', $event)">
              <input type="number" class="num" step="0.5" :value="ev.excursion_temp_c"
                     @input="onNum('excursion_temp_c', $event)">
            </div>
          </div>
          <div class="ctl">
            <label>{{ L.center.dur }}</label>
            <div class="range-line">
              <input type="range" step="1" min="0" :max="durMax" :value="cDur"
                     @input="onNum('duration_min', $event, true)">
              <input type="number" class="num" step="1" :value="ev.duration_min"
                     @input="onNum('duration_min', $event, true)">
            </div>
          </div>
          <div class="ctl">
            <label>{{ L.center.mkt }}</label>
            <div class="range-line">
              <input type="range" step="0.1" :min="mktLo" :max="mktHi" :value="cMkt"
                     @input="onNum('mkt_c', $event)">
              <input type="number" class="num" step="0.1" :value="ev.mkt_c"
                     @input="onNum('mkt_c', $event)">
            </div>
          </div>
        </div>

        <button class="ni-toggle" type="button" @click="showRules = !showRules">
          {{ showRules ? "▾" : "▸" }} {{ L.newInbound.rules }}
        </button>
        <div v-if="showRules" class="cfg ni-cfg">
          <div class="cfg-row">
            <span>{{ L.left.cfgAllowable }}</span>
            <input type="number" step="1" min="1" :value="spec.allowable"
                   @input="onSpecNum('allowable', $event)">
          </div>
          <div class="cfg-row">
            <span>{{ L.left.cfgMkt }}</span>
            <input type="number" step="0.5" :value="spec.mktThreshold"
                   @input="onSpecNum('mktThreshold', $event)">
          </div>
          <div class="cfg-row">
            <span>{{ L.left.cfgRetestable }}</span>
            <input type="checkbox" :checked="spec.retestable" @change="spec.retestable = $event.target.checked">
          </div>
          <button class="btn" type="button" @click="resetSpec">{{ L.newInbound.resetSpec }}</button>
        </div>

        <div class="ni-preview">
          <div class="section-label">{{ L.newInbound.preview }}</div>
          <div class="dispo-banner" :style="{ background: DISPO_COLOR[d.disposition] }">
            <div class="dispo-badge">{{ badge }}</div>
            <div>
              <div class="big">{{ label }}</div>
              <div class="why">{{ d.reason }}</div>
            </div>
            <div class="reship">
              {{ L.banner.reshipHead }}<br>
              <b>{{ d.reshipment ? L.banner.reshipReq : L.banner.reshipNo }}</b>
            </div>
          </div>
          <div class="ni-riskline">
            <span class="risk-score" :style="{ color: risk.color }">{{ risk.score }}/100</span>
            <span class="risk-cause">{{ causeNote }}</span>
            <span class="risk-rule">#{{ d.ruleNo }}</span>
          </div>
          <div class="rulepath">{{ d.rulePath }}</div>
        </div>

        <p v-if="error" class="modal-error">{{ L.newInbound.error }}</p>
      </div>

      <div class="modal-foot">
        <div class="ni-batch">
          <label>{{ L.newInbound.batch }}</label>
          <input v-model="remark" type="text" :placeholder="L.newInbound.batchPh">
        </div>
        <div class="ni-actions">
          <button class="btn inline" type="button" :disabled="archiving" @click="cancel">
            {{ L.newInbound.cancel }}
          </button>
          <button class="btn inline modal-primary" type="button" :disabled="!up || archiving" @click="archive">
            {{ archiving ? "…" : L.newInbound.archive }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
