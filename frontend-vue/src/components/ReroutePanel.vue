<script setup>
/* Delivery re-routing (#reroute). Cleared/idle state, else route toggle +
   map (SVG layer by default; Leaflet once every node carries `loc`) + metrics
   + violation note + pharmacy detail + replacement allocation. The SVG map's
   clickable circles bubble to the wrapper exactly as the vanilla #reroute
   delegated click did. */
import { computed, ref } from "vue";
import { useSandboxStore } from "../stores/sandbox.js";
import { useDecisionsStore } from "../stores/decisions.js";
import { DEPOT, PHARMACIES, ROUTES } from "../data/realData.mjs";
import {
  rerouteIdleHtml, routeMapSvg, routeToggleHtml,
  routeMetricsHtml, routeViolHtml, pharmDetailHtml, allocHtml,
} from "../lib/routeSvg.js";
import { routeNodesWithLoc } from "../lib/routeGeo.js";
import LeafletMap from "./LeafletMap.vue";
import { locale, bundle } from "../i18n/index.js";

const sandbox = useSandboxStore();
const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));

const decision = computed(() => decisions.decisionFor);
const route = computed(() => ROUTES[sandbox.routeMode]);

/* Leaflet only when every node on the live route has finite lng/lat AND we are
   online; a tile error flips the session back to the SVG map. */
const liveNodes = computed(() => routeNodesWithLoc(DEPOT, PHARMACIES, route.value));
const leafletOn = computed(() =>
  liveNodes.value !== null && typeof navigator !== "undefined" && navigator.onLine !== false
);
const tileFallback = ref(false);

const idleHtml = computed(() => rerouteIdleHtml(L.value));
const toggleHtml = computed(() => routeToggleHtml(sandbox.routeMode, L.value));
const mapSvg = computed(() =>
  routeMapSvg(DEPOT, PHARMACIES, route.value, sandbox.routeMode,
              sandbox.selectedPharm, L.value)
);
const metricsViolHtml = computed(() =>
  routeMetricsHtml(route.value, L.value) + routeViolHtml(route.value)
);
const detailHtml = computed(() =>
  pharmDetailHtml(sandbox.selectedPharm, route.value, PHARMACIES, L.value)
);
const allocHtmlText = computed(() => {
  const name = L.value.products[sandbox.current.product_id] || sandbox.current.product_id;
  return allocHtml(name, L.value);
});

/* delegated click, as in the vanilla bind() on #reroute */
function onRouteClick(e) {
  const mb = e.target.closest("[data-mode]");
  if (mb) { sandbox.setRouteMode(mb.dataset.mode); return; }
  const ph = e.target.closest("[data-ph]");
  if (ph) sandbox.togglePharm(ph.dataset.ph);
}
function onSelectPharm(id) { sandbox.togglePharm(id); }
</script>

<template>
  <div v-if="decision.reshipment" class="route-area" @click="onRouteClick">
    <div v-html="toggleHtml"></div>
    <LeafletMap
      v-if="leafletOn && !tileFallback"
      :depot="DEPOT" :pharmacies="PHARMACIES" :route="route"
      :mode="sandbox.routeMode" :selected-pharm="sandbox.selectedPharm"
      @select="onSelectPharm" @tileerror="tileFallback = true"
    />
    <div v-else v-html="mapSvg"></div>
    <div v-html="metricsViolHtml"></div>
    <div v-html="detailHtml"></div>
    <div v-html="allocHtmlText"></div>
  </div>
  <div v-else v-html="idleHtml"></div>
</template>
