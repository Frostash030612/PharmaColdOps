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
import { useDispatchStore } from "../stores/dispatch.js";
import { useRegistrationStore } from "../stores/registration.js";
import M4Panel from './M4Panel.vue';
import M2Panel from './M2Panel.vue';
import routes from "../data/singaporeRoutes.json";
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
const dispatch = useDispatchStore();
const registration = useRegistrationStore();
let recovered = null;
let recoveryError = "";
try { recovered = registration.restore(); } catch (e) { recoveryError = String(e.message || e); }
if (recovered && !(recovered.payload.product_id in PRODUCT_NUM)) {
  recoveryError = "Stored registration product is unsupported; retry or discard the local draft explicitly";
  recovered = null;
}
const facilities = routes.nodes;
const orderChoices = computed(() => dispatch.run?.input?.orders || []);
const linkedOrder = computed(() => ev.value.dispatch_id === dispatch.run?.dispatch_id
  ? orderChoices.value.find((o) => o.order_id === ev.value.order_id) : null);
function selectOrder(e) {
  const order = orderChoices.value.find((o) => o.order_id === e.target.value);
  if (!order) { ev.value.order_id = null; ev.value.dispatch_id = null; return; }
  const d = defaultsOf(order.product_id);
  ev.value = { ...d.ev, facility_id: ev.value.facility_id || null,
    order_id: order.order_id, dispatch_id: dispatch.run.dispatch_id,
    destination_facility_id: order.destination_facility_id };
  spec.value = d.spec;
}
const L = computed(() => bundle(locale.value));

/* ---- draft (local; sandbox stays untouched until archive) ---- */
function defaultsOf(pid) {
  return {
    ev: { product_id: pid, ...DEFAULT_EVENT[pid] },
    spec: { ...PRODUCT_NUM[pid] },
  };
}
const initPid = (recovered?.payload?.product_id in PRODUCT_NUM ? recovered.payload.product_id : null) || ((sandbox.current.product_id in PRODUCT_NUM)
  ? sandbox.current.product_id : "vaccine_2_8");
const init = defaultsOf(initPid);
const ev = ref(recovered ? { ...init.ev, ...recovered.payload } : init.ev);
const override = recovered?.payload?.spec_override || {};
const spec = ref({ ...init.spec, allowable: override.allowable_duration_min ?? init.spec.allowable,
  mktThreshold: override.mkt_threshold_c ?? init.spec.mktThreshold,
  retestable: override.retestable ?? init.spec.retestable });
const locked = computed(() => !!registration.pending);

const archiving = ref(false);
const error = ref(recoveryError);
const showRules = ref(false);
const remark = ref(recovered?.payload?.remark || "");
const mlContexts = ref(recovered?.payload?.ml_contexts || []);
const temperatureContext = ref(recovered?.payload?.temperature_context || null);
const temperaturePending = ref(false);
function applyTemperature(event) { Object.assign(ev.value, event); }

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
  if (archiving.value || decisions.apiUp !== true || (!locked.value && temperaturePending.value)) return;
  archiving.value = true;
  error.value = false;
  try {
    const res = await registration.submit(locked.value ? null : {
      ...eventPayload({ ...ev.value, ml_contexts: mlContexts.value, temperature_context: temperatureContext.value }),
      spec_override: overridePayload(spec.value),
      remark: remark.value.trim() || null,
    });
    overlay.closeNewInbound();
    sandbox.restoreCase(res);        // now the whole flow appears on the page
    history.refresh();               // archive panel picks up the new record
    window.scrollTo({ top: 0, behavior: "smooth" });
    overlay.openCase();
  } catch (e) {
    error.value = String(e.message || e);
  } finally {
    archiving.value = false;
  }
}
function discardDraft() {
  if (window.confirm(L.value.registration.discardConfirm)) registration.clear();
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
        <p v-if="locked" class="registration-note">{{ L.registration.retryNote }} · {{ registration.pending.payload.registration_id }}</p>
        <p v-if="locked">{{ registration.pending.payload.dispatch_id || L.workflow.unlinked }} · {{ registration.pending.payload.order_id || '—' }}</p>
        <p v-if="!registration.storageAvailable" class="modal-error">{{ L.registration.storageWarning }}</p>
        <fieldset class="registration-fields" :disabled="archiving || locked">
        <div class="controls">
          <div class="ctl">
            <label>{{ L.workflow.orderLink }}</label>
            <select :value="ev.order_id || ''" @change="selectOrder">
              <option value="">{{ L.workflow.unlinked }}</option>
              <option v-if="locked && ev.order_id && !orderChoices.some((o) => o.order_id === ev.order_id)" :value="ev.order_id">{{ ev.order_id }} · {{ ev.destination_facility_id }}</option>
              <option v-for="order in orderChoices" :key="order.order_id" :value="order.order_id">
                {{ order.order_id }} · {{ order.quantity }} · {{ order.destination_facility_id }}
              </option>
            </select>
            <small v-if="linkedOrder">{{ ev.dispatch_id }} · {{ linkedOrder.quantity }} · {{ linkedOrder.earliest_min }}–{{ linkedOrder.latest_min }} min</small>
          </div>
          <div class="ctl">
            <label>{{ L.workflow.location }}</label>
            <select v-model="ev.facility_id">
              <option :value="null">{{ L.workflow.unknownLocation }}</option>
              <option v-for="node in facilities" :key="node.facility_id" :value="node.facility_id">{{ node.name }}</option>
            </select>
          </div>
          <div class="ctl">
            <label>{{ L.center.destination }}</label>
            <select v-model="ev.destination_facility_id" :disabled="!!ev.order_id">
              <option :value="undefined">{{ L.workflow.selectDestination }}</option>
              <option v-for="node in facilities.filter((n) => n.role === 'customer')" :key="node.facility_id" :value="node.facility_id">{{ node.name }}</option>
            </select>
          </div>
          <div class="ctl">
            <label>{{ L.center.product }}</label>
            <select :value="ev.product_id" :disabled="!!ev.order_id" @change="onProduct">
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
            <div class="range-line"><fieldset :disabled="!!temperatureContext || temperaturePending">
              <input type="range" step="0.5" :min="tempLo" :max="tempHi" :value="cTemp"
                     @input="onNum('excursion_temp_c', $event)">
              <input type="number" class="num" step="0.5" :value="ev.excursion_temp_c"
                     @input="onNum('excursion_temp_c', $event)">
            </fieldset></div>
          </div>
          <div class="ctl">
            <label>{{ L.center.dur }}</label>
            <div class="range-line"><fieldset :disabled="!!temperatureContext || temperaturePending">
              <input type="range" step="1" min="0" :max="durMax" :value="cDur"
                     @input="onNum('duration_min', $event, true)">
              <input type="number" class="num" step="1" :value="ev.duration_min"
                     @input="onNum('duration_min', $event, true)">
            </fieldset></div>
          </div>
          <div class="ctl">
            <label>{{ L.center.mkt }}</label>
            <div class="range-line"><fieldset :disabled="!!temperatureContext || temperaturePending">
              <input type="range" step="0.1" :min="mktLo" :max="mktHi" :value="cMkt"
                     @input="onNum('mkt_c', $event)">
              <input type="number" class="num" step="0.1" :value="ev.mkt_c"
                     @input="onNum('mkt_c', $event)">
            </fieldset></div>
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

        </fieldset>
        <M2Panel v-model="temperatureContext" :product-id="ev.product_id" :readonly="locked || archiving" :offline="!up"
          @event="applyTemperature" @pending="temperaturePending = $event" />
        <M4Panel v-model="mlContexts" :readonly="locked || archiving" :offline="!up" />
        <div v-if="!temperaturePending || locked" class="ni-preview">
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

        <p v-if="error" class="modal-error">{{ L.newInbound.error }}: {{ error }}</p>
        <button v-if="(locked || error) && !archiving" type="button" class="btn inline" @click="discardDraft">{{ L.registration.discard }}</button>
      </div>

      <div class="modal-foot">
        <div class="ni-batch">
          <label>{{ L.newInbound.batch }}</label>
          <input v-model="remark" type="text" :placeholder="L.newInbound.batchPh" :disabled="archiving || locked">
        </div>
        <div class="ni-actions">
          <button class="btn inline" type="button" :disabled="archiving" @click="cancel">
            {{ L.newInbound.cancel }}
          </button>
          <button class="btn inline modal-primary" type="button" :disabled="!up || archiving || (!locked && (temperaturePending || (d.reshipment && !ev.destination_facility_id)))" @click="archive">
            {{ archiving ? "…" : locked ? L.registration.retry : L.newInbound.archive }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.registration-fields { margin: 0; padding: 0; border: 0; min-width: 0; }
.range-line fieldset { display: flex; gap: 8px; padding: 0; border: 0; min-width: 0; width: 100%; }
.registration-note { padding: 10px; border: 1px solid #fbbf24; background: #fffbeb; border-radius: 8px; overflow-wrap: anywhere; }
</style>
