<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from "vue";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const props = defineProps({
  nodes: { type: Array, required: true },
  plan: { type: Object, required: true },
  selectedId: { type: Number, default: null },
  text: { type: Object, required: true },
});
const emit = defineEmits(["select"]);
const el = ref(null);
const tileError = ref(false);
const colors = ["#0d9488", "#7c3aed", "#d97706"];
let map, layer, observer;
function fit() {
  if (map && layer) map.fitBounds(layer.getBounds().pad(0.08));
}
function redraw() {
  if (!map) return;
  if (layer) layer.remove();
  layer = L.featureGroup().addTo(map);
  props.plan.geojson.features.forEach((feature, i) => {
    L.geoJSON(feature, { style: { color: colors[i % colors.length], weight: 3, opacity: 0.85 } }).addTo(layer);
  });
  props.nodes.forEach(node => {
    const routeIndex = props.plan.routes.findIndex(route => route.customer_ids.includes(node.node_id));
    const selected = node.node_id === props.selectedId;
    const marker = L.circleMarker([node.lat, node.lon], {
      radius: selected ? 9 : node.node_id === 0 ? 8 : 6,
      color: selected ? "#0f172a" : "#fff", weight: 2,
      fillColor: node.node_id === 0 ? "#0f172a" : colors[Math.max(0, routeIndex) % colors.length], fillOpacity: 1,
    }).addTo(layer).on("click", () => emit("select", node.node_id));
    // Text nodes avoid interpreting facility names as HTML.
    const label = document.createElement("span");
    label.textContent = node.name;
    marker.bindTooltip(label, { direction: "top" });
  });
}
onMounted(() => {
  map = L.map(el.value, { scrollWheelZoom: false, zoomControl: true });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>', maxZoom: 18,
  }).on("tileerror", () => { tileError.value = true; }).addTo(map);
  redraw(); fit();
  observer = new ResizeObserver(() => map?.invalidateSize());
  observer.observe(el.value);
});
watch(() => props.plan, () => { redraw(); fit(); });
watch(() => props.selectedId, redraw);
onBeforeUnmount(() => { observer?.disconnect(); map?.remove(); map = null; });
</script>

<template>
  <div class="sg-map-wrap">
    <div ref="el" class="sg-map" role="region" :aria-label="text.mapLabel"></div>
    <button class="sg-fit" @click="fit">{{ text.reset }}</button>
  </div>
  <p v-if="tileError" class="sg-tile-note" role="status">{{ text.tiles }}</p>
</template>

<style scoped>
.sg-map-wrap { position: relative; }
.sg-map { height: 290px; width: 100%; border-radius: 8px; background: #eaf0f3; z-index: 0; }
.sg-fit { position: absolute; z-index: 1; top: 10px; right: 10px; background: white; border: 1px solid #cbd5e1; border-radius: 5px; padding: 5px 7px; font-size: 10px; cursor: pointer; }
.sg-tile-note { font-size: 11px; line-height: 1.5; color: #64748b; margin: 6px 0; }
</style>
