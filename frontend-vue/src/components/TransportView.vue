<script setup>
/* The transport view: the operation, large.

   The panel's map is a 290px thumbnail in the narrowest column, which is fine
   for glancing at but useless for watching a delivery happen. This is the same
   map with room to breathe, plus the controls that only make sense at that size:
   the simulated clock, a real pause (speed 0 freezes simulated time), following
   the focused truck, and the "改道前 vs 改道后" overlay once a branch event has
   been previewed. */
import { computed, ref, onMounted, onBeforeUnmount, watch } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { useSandboxStore } from "../stores/sandbox.js";
import { useDispatchStore } from "../stores/dispatch.js";
import data from "../data/singaporeRoutes.json";
import LeafletMap from "./LeafletMap.vue";
import { locale, bundle } from "../i18n/index.js";

const emit = defineEmits(["close"]);
const decisions = useDecisionsStore();
const sandbox = useSandboxStore();
const dispatch = useDispatchStore();
const L = computed(() => bundle(locale.value));
const text = computed(() => L.value.singapore);

const nodes = data.nodes;
const names = Object.fromEntries(nodes.map((node) => [node.node_id, node.name]));
const plan = computed(() => dispatch.live || data.plans.ortools);

const selectedVehicle = ref(null);
const follow = ref(true);
const showComparison = ref(true);
const paused = ref(false);
const lastSpeed = ref(60);

const branch = computed(() => dispatch.branch);
const focusedVehicle = computed(() =>
  selectedVehicle.value || plan.value.routes?.[0]?.vehicle_id || null);

/* Tell the store which truck the overlays are about, so the small map and this
   view always draw the same comparison. */
watch(focusedVehicle, (id) => { dispatch.branchVehicle = id; }, { immediate: true });

/* "改道前 vs 改道后": both lines come from the backend already drawn. */
const overlays = computed(() =>
  showComparison.value ? dispatch.branchOverlays : []);
const branchNodeIds = computed(() => (showComparison.value ? dispatch.branchNodeIds : []));
const incidentNodeId = computed(() => dispatch.incidentNodeId);

const simClock = computed(() => {
  const minutes = dispatch.live?.sim_now_min;
  if (minutes == null) return "—";
  const total = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
});

const underway = computed(() => dispatch.run?.status === "in_transit");
const SPEEDS = [
  { value: 1, key: "speedReal" },
  { value: 60, key: "speedFast" },
  { value: 300, key: "speedFaster" },
];
function setSpeed(value) {
  lastSpeed.value = value;
  paused.value = false;
  dispatch.setSpeed(value);
}
function togglePause() {
  paused.value = !paused.value;
  dispatch.setSpeed(paused.value ? 0 : lastSpeed.value);
}
function pickVehicle(id) {
  selectedVehicle.value = selectedVehicle.value === id ? null : id;
}

/* Esc closes the view, and the page behind it must not scroll. */
function onKey(event) { if (event.key === "Escape") emit("close"); }
onMounted(() => {
  window.addEventListener("keydown", onKey);
  document.body.style.overflow = "hidden";
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  document.body.style.overflow = "";
});
</script>

<template>
  <div class="tv-backdrop" role="dialog" aria-modal="true" :aria-label="text.transportTitle">
    <div class="tv-panel">
      <header>
        <strong>{{ text.transportTitle }}</strong>
        <span class="tv-clock">{{ text.simClock }} <b>{{ simClock }}</b></span>
        <button class="tv-close" @click="emit('close')">{{ text.transportClose }}</button>
      </header>

      <div class="tv-controls">
        <button :disabled="!underway" :class="{ on: paused }" @click="togglePause">
          {{ paused ? text.transportResume : text.transportPause }}
        </button>
        <span class="tv-speeds">
          <button v-for="s in SPEEDS" :key="s.value" :disabled="!underway"
            :class="{ on: !paused && (dispatch.run?.clock?.speed || 60) === s.value }"
            @click="setSpeed(s.value)">{{ text[s.key] }}</button>
        </span>
        <label class="tv-check">
          <input type="checkbox" v-model="follow">{{ text.transportFollow }}
        </label>
        <label class="tv-check">
          <input type="checkbox" v-model="showComparison" :disabled="!branch?.candidates?.length">
          {{ text.transportCompare }}
        </label>
        <span v-if="branch?.candidates?.length && selectedVehicle" class="tv-hint">
          {{ text.transportCompareHint }}
        </span>
        <span v-else-if="!underway" class="tv-hint">{{ text.transportNotRunning }}</span>
      </div>

      <LeafletMap :nodes="nodes" :plan="plan" :text="text" :selected-id="null"
        :selected-vehicle="selectedVehicle" height="calc(100vh - 240px)" legend follow
        :overlays="overlays" :branch-node-ids="branchNodeIds" :incident-node-id="incidentNodeId"
        @select-vehicle="pickVehicle" />

      <ul class="tv-vehicles">
        <li v-for="(route, index) in plan.routes" :key="route.vehicle_id"
          :class="{ picked: focusedVehicle === route.vehicle_id }">
          <button @click="pickVehicle(route.vehicle_id)">
            {{ text.vehicle }} {{ route.vehicle_id }}
          </button>
          <span v-if="route.track">
            {{ route.track.reached_stops }}/{{ route.stops?.length || route.customer_ids.length }}
            · {{ text.stopsDone }}
          </span>
          <span v-else>{{ route.customer_ids.map((id) => names[id]).join(" → ") }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.tv-backdrop { position: fixed; inset: 0; z-index: 2000; background: rgba(15,23,42,.55); backdrop-filter: blur(3px);
  display: flex; align-items: center; justify-content: center; padding: 18px; }
.tv-panel { background: #fff; border-radius: 12px; padding: 12px 14px; width: min(1500px, 100%); max-height: 100%;
  overflow: auto; box-shadow: 0 18px 50px rgba(15,23,42,.35); }
.tv-panel header { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.tv-panel header > strong { font-size: 14px; color: #0f172a; }
.tv-clock { color: #64748b; font-size: 12px; }
.tv-clock b { color: #0f766e; font-variant-numeric: tabular-nums; }
.tv-close { margin-left: auto; background: #0f172a; color: #fff; border: 0; border-radius: 7px; padding: 5px 11px; cursor: pointer; font-size: 12px; }
.tv-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 9px; font-size: 12px; color: #475569; }
.tv-controls > button { background: #7c3aed; color: #fff; border: 0; border-radius: 7px; padding: 5px 11px; cursor: pointer; font-weight: 600; }
.tv-controls > button.on { background: #b45309; }
.tv-controls button:disabled { opacity: .5; cursor: default; }
.tv-speeds button { border: 1px solid #cbd5e1; background: #fff; color: #475569; border-radius: 5px; padding: 3px 7px; font-size: 11px; cursor: pointer; }
.tv-speeds button.on { border-color: #0d9488; color: #0f766e; background: #f0fdfa; }
.tv-check { display: inline-flex; align-items: center; gap: 4px; }
.tv-hint { color: #64748b; }
.tv-vehicles { list-style: none; display: flex; gap: 14px; flex-wrap: wrap; margin: 9px 0 0; padding: 0; font-size: 11px; color: #475569; }
.tv-vehicles li.picked { color: #0f172a; font-weight: 600; }
.tv-vehicles button { background: none; border: 0; padding: 0; color: inherit; font: inherit; cursor: pointer; text-decoration: underline dotted; }
</style>
