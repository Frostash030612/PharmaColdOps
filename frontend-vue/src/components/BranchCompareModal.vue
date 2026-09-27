<script setup>
/* Candidate comparison popup.

   The options used to live in a small table under the dispatch panel, which
   could only show a row of numbers. Choosing between "send a spare vehicle",
   "add a stop to a truck already rolling" and "return to the depot" is a
   spatial and temporal decision, so each option now gets its own panel: the
   actual road geometry this option drives (with the un-changed route dashed
   behind it) and a timeline of every order it delays. */
import { computed, ref, watch } from "vue";
import LeafletMap from "./LeafletMap.vue";
import { useDispatchStore } from "../stores/dispatch.js";
import { useHistoryStore } from "../stores/history.js";
import { useSandboxStore } from "../stores/sandbox.js";
import { locale, bundle } from "../i18n/index.js";
import { fmt, interp } from "../lib/format.js";
import { candidateOverlays, candidateNodeIds, candidateDeltas, buildTimeline } from "../lib/branchCompare.js";
import { DISPO_COLOR } from "../data/products.js";
import routes from "../data/singaporeRoutes.json";

const dispatch = useDispatchStore();
const history = useHistoryStore();
const sandbox = useSandboxStore();
const L = computed(() => bundle(locale.value));
const text = computed(() => L.value.singapore);

const nodes = routes.nodes;
const nodeByFacility = Object.fromEntries(nodes.map((n) => [n.facility_id, n.node_id]));
const nameByFacility = Object.fromEntries(nodes.map((n) => [n.facility_id, n.name]));

/* Minutes from midnight → a clock label. Declared here because the case summary
   above uses it. */
function clock(min) {
  if (min == null) return "—";
  const m = Math.round(min);
  return `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/* Which option the right-hand panel is showing. Defaults to the one the backend
   ranked first, because that is the recommendation being explained. */
const picked = ref(0);

/* A refusal that has no HTTP error behind it (missing case id, thrown promise)
   still has to be visible: a button that silently does nothing is worse than an
   error message. */
const localError = ref("");

watch(() => dispatch.branchOpen, (open) => { if (open) picked.value = 0; });

const candidates = computed(() => dispatch.branch?.candidates || []);
const candidate = computed(() => candidates.value[picked.value] || null);
const best = computed(() => candidates.value[0] || null);

/* What is being handled. The popup used to jump straight to "change the route or
   send another vehicle" without ever saying which excursion, batch or hospital
   that decision was about — an operator landing here could not tell what had
   gone wrong. Read from the archived record (the values as they were closed),
   never re-derived from the current rules, so the popup shows the case's own
   disposition and reason even if the rule set has moved on since. */
const caseInfo = computed(() => {
  const runId = dispatch.branch?.run_id || sandbox.currentRunId || null;
  const record = runId ? history.runs.find((r) => r.run_id === runId) : null;
  const ev = record?.event || sandbox.current || {};
  const spec = record?.spec || sandbox.spec || {};
  const order = dispatch.branch?.order || null;
  const destination = order?.destination_facility_id || ev.destination_facility_id || null;
  const disposition = record?.disposition || null;
  return {
    runId,
    when: record?.created_at ? String(record.created_at).replace("T", " ") : null,
    product: L.value.products[ev.product_id] || ev.product_id || "—",
    /* The product label already carries its range in some locales ("Vaccine
       (2–8 °C)"), so the range is only appended when the label lacks it. */
    storage: spec.storage_min_c != null && spec.storage_max_c != null
      ? `${spec.storage_min_c}–${spec.storage_max_c} °C` : null,
    temp: ev.excursion_temp_c,
    duration: ev.duration_min,
    mkt: ev.mkt_c,
    allowable: spec.allowable_duration_min,
    stage: ev.stage ? (L.value.stages?.[ev.stage] || ev.stage) : null,
    packaging: ev.packaging || null,
    destination,
    destinationName: destination ? (nameByFacility[destination] || destination) : null,
    quantity: order?.quantity ?? null,
    window: order && order.earliest_min != null
      ? `${clock(order.earliest_min)}–${clock(order.latest_min)}` : null,
    disposition,
    dispositionLabel: disposition ? (L.value.dispo[disposition]?.label || disposition) : null,
    dispositionColor: disposition ? (DISPO_COLOR[disposition] || "#dc2626") : "#dc2626",
    ruleNo: record?.rule_no ?? null,
    /* The reason as it was recorded (English from the backend), with the current
       locale's wording for the same rule as a note when the two differ. */
    reason: record?.reason || null,
    reasonLocal: record?.rule_no ? (L.value.ruleText?.[record.rule_no]?.reason || null) : null,
  };
});

/* Whether a spoiled batch travels back on the same trip (the B6 rescue case):
   that is a second thing the operator has to know about, not a route detail. */
const spoiled = computed(() => (candidate.value?.quarantine_order_ids || []).length > 0);

const kindLabels = {
  spare_vehicle: () => text.value.branchKindSpare,
  add_stop_in_transit: () => text.value.branchKindAddStop,
  return_to_depot: () => text.value.branchKindReturn,
  load_before_departure: () => text.value.branchKindLoadFirst,
};
const kindLabel = (kind) => (kindLabels[kind] ? kindLabels[kind]() : kind);

const overlays = computed(() => candidateOverlays(dispatch.branch, candidate.value));
const branchNodeIds = computed(() => candidateNodeIds(dispatch.branch, candidate.value, nodeByFacility));
const incidentNodeId = computed(() => dispatch.incidentNodeId);
const deltas = computed(() => candidateDeltas(candidate.value, best.value));
const timeline = computed(() => buildTimeline(dispatch.branch, candidate.value));

/* The map draws a plan; the popup's plan is just this option's own route, so
   the alternative lines are read as the only route on screen. */
const planForMap = computed(() => ({
  routes: candidate.value
    ? [{ vehicle_id: candidate.value.vehicle_id, stops: [], customer_ids: [] }]
    : [],
}));

const worstDelay = (c) => Math.max(0, ...(c.affected_orders || []).map((a) => a.delay_min || 0));
const minutes = (n) => `${fmt(n, 0)} ${text.value.branchMinutes}`;

/* Why the recommended option is the one the backend put first. The honest answer
   is a trade-off — usually "costs more, disturbs nobody" against "cheaper, but
   delays N orders" — so it is stated instead of implied by a colour. */
const tradeoff = computed(() => {
  const c = candidate.value;
  const others = candidates.value.filter((o) => o !== c);
  if (!c || !others.length) return "";
  const cheapest = others.reduce((a, b) => (a.added_distance_m <= b.added_distance_m ? a : b));
  const cheaperKm = (c.added_distance_m - cheapest.added_distance_m) / 1000;
  const affected = (c.affected_orders || []).length;
  if (cheaperKm > 0.05 && affected === 0) {
    return interp(text.value.compareTradeoffCostlier, { km: fmt(cheaperKm, 2) });
  }
  if (cheaperKm < -0.05 && affected > 0) {
    return interp(text.value.compareTradeoffCheaper,
                  { km: fmt(-cheaperKm, 2), n: affected, min: fmt(worstDelay(c), 0) });
  }
  if (affected === 0) return text.value.compareTradeoffNoImpact;
  return interp(text.value.compareTradeoffImpact,
                { n: affected, min: fmt(worstDelay(c), 0) });
});

function choose() {
  const c = candidate.value;
  if (!c) return;
  /* The preview payload has no top-level `run_id` (verified 2026-09-27: it is
     null, the order comes from `event_fallback`), and the store's
     commitReshipment *silently returns* when the id is missing — which is
     exactly how "Use this option" could do nothing at all. So the id is taken
     from the case the popup is open on, and a missing one is reported instead
     of swallowed. */
  const runId = sandbox.currentRunId || dispatch.branch?.run_id || null;
  if (!runId) {
    localError.value = text.value.compareNeedCase;
    return;
  }
  localError.value = "";
  Promise.resolve(dispatch.commitReshipment(runId, {
    candidate_kind: c.kind,
    vehicle_id: c.vehicle_id,
  })).catch((e) => { localError.value = String(e?.message || e); });
}
</script>

<template>
  <div class="compare-backdrop" @click.self="dispatch.closeBranchCompare()">
    <section class="compare-modal" role="dialog" aria-modal="true">
      <!-- A plain div, not <header>: styles.css styles the *page* header with a
           dark navy gradient, and a semantic <header> here inherited it, putting
           dark title text on a dark bar (2026-09-27). -->
      <div class="compare-head">
        <div>
          <strong>{{ text.branchTitle }}</strong>
          <p>{{ text.branchCompareHint }}</p>
        </div>
        <div class="compare-head-right">
          <label class="compare-policy">
            {{ text.branchPolicy }}
            <select :value="dispatch.policy" :disabled="dispatch.pending"
              @change="dispatch.setPolicy($event.target.value)">
              <option value="minimize_disruption">{{ text.policyDisruption }}</option>
              <option value="minimize_vehicles">{{ text.policyVehicles }}</option>
            </select>
          </label>
          <button class="compare-close" :title="text.compareClose" @click="dispatch.closeBranchCompare()">✕</button>
        </div>
      </div>

      <p v-if="dispatch.needsDailyPlan" class="sg-error" role="status">{{ text.branchNeedsPlan }}</p>
      <p v-else-if="dispatch.branchError" class="sg-error" role="status">{{ dispatch.branchError }}</p>

      <!-- What this decision is about. Shown before any option, because "which
           option is best" is unanswerable without knowing what happened and
           which batch and hospital are affected. -->
      <section v-if="caseInfo.runId" class="case-brief">
        <div class="case-brief-main">
          <span class="case-brief-tag">{{ text.compareCaseTag }}</span>
          <strong>{{ caseInfo.destinationName || text.unknownCaseDest }}</strong>
          <span v-if="caseInfo.quantity != null" class="case-brief-qty">
            {{ interp(text.compareCaseQty, { n: caseInfo.quantity, unit: text.units }) }}
          </span>
          <span v-if="caseInfo.window" class="case-brief-win">
            {{ interp(text.compareCaseWindow, { win: caseInfo.window }) }}
          </span>
        </div>

        <ul class="case-brief-facts">
          <li>
            <b>{{ text.compareCaseProduct }}</b>{{ caseInfo.product }}
          </li>
          <li v-if="caseInfo.storage">
            <b>{{ text.compareCaseStorage }}</b>{{ caseInfo.storage }}
          </li>
          <li>
            <b>{{ text.compareCaseExcursion }}</b>
            {{ caseInfo.temp }} °C
            <template v-if="caseInfo.duration != null"> · {{ caseInfo.duration }} {{ text.branchMinutes }}</template>
            <template v-if="caseInfo.allowable != null"> / {{ text.compareCaseAllowable }} {{ caseInfo.allowable }} {{ text.branchMinutes }}</template>
            <template v-if="caseInfo.mkt != null"> · MKT {{ caseInfo.mkt }} °C</template>
          </li>
          <li v-if="caseInfo.stage">
            <b>{{ text.compareCaseStage }}</b>{{ caseInfo.stage }}
            <template v-if="caseInfo.packaging"> · {{ text.compareCasePackaging }}
              {{ caseInfo.packaging === "compromised" ? text.compareCasePackBroken : text.compareCasePackOk }}</template>
          </li>
        </ul>

        <div v-if="caseInfo.dispositionLabel" class="case-brief-decision">
          <span class="case-brief-dot" :style="{ background: caseInfo.dispositionColor }"></span>
          <b :style="{ color: caseInfo.dispositionColor }">{{ caseInfo.dispositionLabel }}</b>
          <span v-if="caseInfo.ruleNo != null" class="case-brief-rule">{{ text.compareCaseRule }} #{{ caseInfo.ruleNo }}</span>
          <span v-if="caseInfo.reason" class="case-brief-reason">
            {{ text.compareCaseReason }}: {{ caseInfo.reason }}
            <em v-if="caseInfo.reasonLocal && caseInfo.reasonLocal !== caseInfo.reason">（{{ caseInfo.reasonLocal }}）</em>
          </span>
        </div>

        <p class="case-brief-notes">
          <span v-if="spoiled" class="case-brief-spoiled">⚠ {{ text.compareCaseSpoiled }}</span>
          <span v-else>{{ text.compareCaseWhy }}</span>
          <span class="case-brief-id">
            {{ text.compareCaseId }} <code>{{ caseInfo.runId }}</code>
            <template v-if="caseInfo.when"> · {{ caseInfo.when }}</template>
          </span>
        </p>
      </section>

      <div v-if="candidates.length" class="compare-body">
        <!-- What each option costs, side by side. Click one to load its map + timeline. -->
        <ul class="compare-list">
          <li v-for="(c, i) in candidates" :key="`${c.kind}-${c.vehicle_id}`">
            <button class="compare-card" :class="{ on: i === picked, best: i === 0, late: !c.on_time }"
              @click="picked = i">
              <span class="compare-card-top">
                <b>{{ kindLabel(c.kind) }}</b>
                <em v-if="i === 0" class="tag-best">{{ text.compareRecommended }}</em>
              </span>
              <!-- "ETA" prefix: without it the card time read like a departure
                   and looked inconsistent with the timeline's axis. -->
              <span class="compare-card-vehicle">{{ c.vehicle_id }} · {{ text.compareEta }} {{ clock(c.eta_min) }}</span>
              <span class="compare-metrics">
                <span><i>+</i>{{ fmt(c.added_distance_m / 1000, 2) }} {{ text.km }}</span>
                <span :class="{ warn: worstDelay(c) > 0 }">
                  {{ (c.affected_orders || []).length }} {{ text.compareAffected }}
                </span>
                <span v-if="!c.on_time" class="warn">{{ text.branchLateness }} {{ minutes(c.lateness_min) }}</span>
              </span>
              <span v-if="c.pickup_facility_id" class="compare-note">
                {{ text.branchPickup }} {{ c.pickup_facility_id }}
              </span>
              <span v-if="c.resequenced" class="compare-note">{{ text.branchResequenced }}</span>
            </button>
          </li>
        </ul>

        <!-- The chosen option: where it drives, and who it delays. -->
        <div v-if="candidate" class="compare-detail">
          <div class="compare-detail-head">
            <strong>{{ kindLabel(candidate.kind) }}</strong>
            <span>{{ candidate.vehicle_id }}</span>
            <span v-if="deltas" class="compare-delta"
              :class="{ better: deltas.addedDistanceM < 0, worse: deltas.addedDistanceM > 0 }">
              {{ deltas.addedDistanceM === 0 ? text.compareSameCost
                 : (deltas.addedDistanceM > 0
                    ? interp(text.compareDearer, { km: fmt(deltas.addedDistanceM / 1000, 2) })
                    : interp(text.compareCheaper, { km: fmt(-deltas.addedDistanceM / 1000, 2) })) }}
            </span>
          </div>
          <p v-if="tradeoff" class="compare-tradeoff">{{ tradeoff }}</p>

          <LeafletMap :nodes="nodes" :plan="planForMap" :text="text" height="240px"
            :overlays="overlays" :branch-node-ids="branchNodeIds"
            :incident-node-id="incidentNodeId" :compare-vehicle="candidate.vehicle_id" />

          <p class="compare-legend">
            <i class="sw before"></i>{{ text.beforeRoute }}
            <i class="sw after"></i>{{ text.afterRoute }}
            <span class="compare-stops">{{ text.compareStops }}</span>
          </p>

          <!-- Timeline: grey = when the order was due, coloured = when it lands now.
               An option that disturbs nobody gets a one-line statement instead of
               an empty axis with a "now" marker, which read as if the chart had
               failed to draw (2026-09-27). -->
          <div class="compare-timeline">
            <strong>{{ text.compareTimeline }}</strong>
            <svg v-if="timeline.bars.length" :viewBox="`0 0 ${timeline.width} ${timeline.height}`"
              class="compare-svg" role="img" :aria-label="text.compareTimeline">
              <g v-for="t in timeline.ticks" :key="`t${t.min}`">
                <line :x1="t.x" :y1="10" :x2="t.x" :y2="timeline.height - 16" stroke="#e2e8f0" stroke-width="1" />
                <text :x="t.x" :y="timeline.height - 4" text-anchor="middle" font-size="9" fill="#94a3b8">{{ t.label }}</text>
              </g>
              <line :x1="timeline.nowX" :y1="8" :x2="timeline.nowX" :y2="timeline.height - 16"
                stroke="#0f172a" stroke-width="1.5" stroke-dasharray="4 3" />
              <text :x="timeline.nowX + 3" y="14" font-size="9" fill="#0f172a">{{ text.compareNow }}</text>

              <template v-for="b in timeline.bars" :key="b.orderId">
                <text :x="timeline.padLeft - 6" :y="b.y + 9" text-anchor="end" font-size="10" fill="#475569">
                  {{ b.label }}
                </text>
                <line :x1="b.beforeX" :y1="b.y + 4" :x2="b.afterX" :y2="b.y + 4"
                  stroke="#cbd5e1" stroke-width="2" />
                <circle :cx="b.beforeX" :cy="b.y + 4" r="3" fill="#94a3b8" />
                <circle :cx="b.afterX" :cy="b.y + 4" r="4" :fill="b.color" />
                <text :x="b.afterX + 7" :y="b.y + 8" font-size="9" :fill="b.color">
                  {{ b.delayMin > 0 ? `+${b.delayMin} ${text.branchMinutes}` : text.compareOnTime }}
                </text>
              </template>
              <text v-if="!timeline.bars.length" :x="timeline.padLeft" y="26" font-size="11" fill="#64748b">
                {{ text.branchNoAffected }}
              </text>
            </svg>
            <p v-else class="compare-noimpact">{{ text.branchNoAffected }}</p>
          </div>

          <div class="compare-actions">
            <button class="compare-take" :disabled="dispatch.pending || !sandbox.currentRunId"
              @click="choose()">
              {{ dispatch.pending ? text.committing : text.compareUse }}
            </button>
            <span v-if="localError" class="sg-error">{{ localError }}</span>
            <span v-else-if="dispatch.error" class="sg-error">{{ dispatch.error }}</span>
            <span v-else-if="!sandbox.currentRunId" class="compare-hint">{{ text.compareNeedCase }}</span>
          </div>
        </div>
      </div>

      <p v-else class="sg-note compare-empty">{{ text.branchPreview }}</p>
    </section>
  </div>
</template>

<style scoped>
.compare-backdrop {
  position: fixed; inset: 0; z-index: 1200; display: flex; align-items: center; justify-content: center;
  background: rgba(15, 23, 42, .45); backdrop-filter: blur(3px); padding: 18px;
}
.compare-modal {
  width: min(1140px, 96vw); max-height: 92vh; overflow: auto; background: #fff;
  border-radius: 14px; box-shadow: 0 24px 60px rgba(15, 23, 42, .35); padding: 16px 18px 18px;
}
.compare-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px;
  background: #fff; padding: 2px 0 10px; margin-bottom: 12px; border-bottom: 1px solid var(--line); }
.compare-head strong { font-size: 15px; color: var(--ink); }
.compare-head p { margin: 3px 0 0; color: var(--muted); font-size: 11.5px; max-width: 62ch; }
.compare-head-right { display: flex; align-items: center; gap: 10px; flex: none; }
.compare-policy { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--muted); }
.compare-policy select { border: 1px solid var(--line); border-radius: 7px; padding: 4px 6px; font-size: 11px;
  color: var(--ink); background: #fff; }
.compare-close {
  border: 1px solid var(--line); background: #fff; color: var(--muted); border-radius: 8px;
  width: 28px; height: 28px; cursor: pointer; font-size: 13px; line-height: 1;
}
.compare-close:hover { border-color: var(--teal); color: var(--teal); }

.compare-body { display: grid; grid-template-columns: 320px 1fr; gap: 16px; align-items: start; }
.compare-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.compare-card {
  width: 100%; text-align: left; display: grid; gap: 3px; cursor: pointer;
  border: 1px solid var(--line); border-left: 4px solid var(--line);
  border-radius: 10px; background: #fff; padding: 9px 11px; color: var(--ink); transition: .13s;
}
.compare-card:hover { border-color: var(--teal-2); }
.compare-card.on { border-color: var(--teal); border-left-color: var(--teal); background: #f0fdfa; }
.compare-card.best { border-left-color: var(--teal); }
.compare-card.late { border-left-color: #dc2626; }
.compare-card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.compare-card-top b { font-size: 12.5px; }
.tag-best {
  font-style: normal; font-size: 9.5px; font-weight: 700; color: #0f766e;
  background: #ccfbf1; border-radius: 999px; padding: 1px 6px; white-space: nowrap;
}
.compare-card-vehicle { font-size: 11px; color: var(--muted); }
.compare-metrics { display: flex; flex-wrap: wrap; gap: 10px; font-size: 11.5px; color: #334155; }
.compare-metrics .warn { color: #b45309; font-weight: 600; }
.compare-metrics i { font-style: normal; color: var(--muted); }
.compare-note { font-size: 10.5px; color: #64748b; }

.compare-detail { display: grid; gap: 8px; }
.compare-detail-head { display: flex; align-items: center; gap: 10px; font-size: 12.5px; color: var(--ink); }
.compare-detail-head span { color: var(--muted); font-size: 11.5px; }
.compare-delta { font-size: 11px; font-weight: 600; }
.compare-delta.better { color: #0f766e; }
.compare-delta.worse { color: #b45309; }
.compare-tradeoff { margin: 0; font-size: 11.5px; line-height: 1.5; color: #475569; background: #f8fafc;
  border-left: 3px solid var(--teal); border-radius: 0 8px 8px 0; padding: 6px 9px; }

.compare-legend { display: flex; align-items: center; gap: 12px; margin: 0; font-size: 11px; color: var(--muted); }
.compare-legend .sw { display: inline-block; width: 16px; height: 0; border-top-width: 3px; border-top-style: solid; margin-right: 5px; }
.compare-legend .sw.before { border-top-color: #94a3b8; border-top-style: dashed; }
.compare-legend .sw.after { border-top-color: #dc2626; }
.compare-stops { margin-left: auto; }

.compare-timeline { border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px 4px; background: #fbfdff; }
.compare-timeline strong { font-size: 12px; color: var(--ink); }
.compare-svg { width: 100%; height: auto; display: block; }
.compare-noimpact { margin: 6px 0 6px; font-size: 11.5px; color: #0f766e; font-weight: 600; }

.compare-actions { display: flex; align-items: center; gap: 12px; }
.compare-take {
  border: 1px solid var(--teal); background: var(--teal); color: #fff; border-radius: 9px;
  padding: 7px 14px; font-size: 12px; font-weight: 600; cursor: pointer;
}
.compare-take:disabled { opacity: .6; cursor: default; }
.compare-hint { font-size: 11px; color: #b45309; }
.compare-empty { margin: 4px 0; }

/* --- what this decision is about (case brief) --- */
.case-brief { border: 1px solid var(--line); border-left: 4px solid var(--teal); border-radius: 0 10px 10px 0;
  background: #f8fbfd; padding: 10px 12px; margin: 0 0 12px; display: grid; gap: 6px; }
.case-brief-main { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px; }
.case-brief-tag { font-size: 10px; font-weight: 700; letter-spacing: .3px; color: #0f766e;
  background: #ccfbf1; border-radius: 999px; padding: 2px 7px; }
.case-brief-main strong { font-size: 14px; color: var(--ink); }
.case-brief-qty { font-size: 12px; color: #0f766e; font-weight: 600; }
.case-brief-win { font-size: 11.5px; color: var(--muted); }
.case-brief-facts { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px 18px; }
.case-brief-facts li { font-size: 11.5px; color: #334155; }
.case-brief-facts b { color: var(--muted); font-weight: 600; margin-right: 4px; }
.case-brief-decision { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 11.5px; }
.case-brief-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.case-brief-rule { color: var(--muted); }
.case-brief-reason { color: #475569; font-style: italic; }
.case-brief-notes { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px 12px; margin: 0;
  font-size: 11px; color: var(--muted); }
.case-brief-spoiled { color: #b45309; font-weight: 700; }
.case-brief-id { margin-left: auto; }
.case-brief-id code { font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 10.5px; color: #475569; }

@media (max-width: 900px) {
  .compare-body { grid-template-columns: 1fr; }
}
</style>
