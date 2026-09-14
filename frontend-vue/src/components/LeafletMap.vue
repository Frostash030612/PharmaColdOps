<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from "vue";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const props = defineProps({
  nodes: { type: Array, required: true },
  plan: { type: Object, required: true },
  selectedId: { type: Number, default: null },
  selectedVehicle: { type: String, default: null },
  text: { type: Object, required: true },
});
const emit = defineEmits(["select", "selectVehicle"]);
const el = ref(null);
const tileError = ref(false);
const colors = ["#0d9488", "#7c3aed", "#d97706"];
let map, layer, observer, vehicleLayer;
const markers = new Map();        // vehicle_id -> { marker, from, to, t0, dur }
let raf = null;
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
  drawVehicles();
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
/* Live vehicles ride on their own layer, and each marker is kept across
   updates and glided to its new position. Re-creating markers every poll is
   what made the truck blink; tweening between the server's positions also
   turns a once-a-second jump into continuous motion. */
const TWEEN_MS = 1000;

function ensureVehicleLayer() {
  if (!vehicleLayer) vehicleLayer = L.layerGroup().addTo(map);
}

function drawVehicles() {
  if (!map) return;
  ensureVehicleLayer();
  const live = new Set();
  (props.plan.routes || []).forEach((route, i) => {
    const track = route.track;
    if (!track || !track.position) return;
    live.add(route.vehicle_id);
    const [lon, lat] = track.position;
    const target = L.latLng(lat, lon);
    let entry = markers.get(route.vehicle_id);
    if (!entry) {
      const marker = L.marker(target, {
        zIndexOffset: 500,
        icon: L.divIcon({
          className: "veh-icon",
          html: `<span style="background:${colors[i % colors.length]}">🚚</span>`,
          iconSize: [24, 24], iconAnchor: [12, 12],
        }),
      }).bindTooltip(route.vehicle_id, { direction: "top" }).addTo(vehicleLayer);
      marker.on("click", () => emit("selectVehicle", route.vehicle_id));
      entry = { marker, from: target, to: target, t0: 0 };
      markers.set(route.vehicle_id, entry);
    } else {
      entry.from = entry.marker.getLatLng();
      entry.to = target;
      entry.t0 = performance.now();
    }
    const el = entry.marker.getElement();
    if (el) el.classList.toggle("focus", props.selectedVehicle === route.vehicle_id);
  });
  // A vehicle that finished (or left the plan) loses its marker.
  for (const [id, entry] of markers) {
    if (!live.has(id)) { entry.marker.remove(); markers.delete(id); }
  }
  if (markers.size && !raf) raf = requestAnimationFrame(step);
}

function step(now) {
  raf = null;
  let moving = false;
  for (const entry of markers.values()) {
    if (!entry.t0) continue;
    const k = Math.min(1, (now - entry.t0) / TWEEN_MS);
    entry.marker.setLatLng(L.latLng(
      entry.from.lat + (entry.to.lat - entry.from.lat) * k,
      entry.from.lng + (entry.to.lng - entry.from.lng) * k,
    ));
    if (k < 1) moving = true;
  }
  if (moving) raf = requestAnimationFrame(step);
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
watch(() => props.plan, (next, prev) => {
  // A pure position update must not re-fit the map, or it would fight the
  // user's pan/zoom every second; only a changed route set re-frames.
  const sameRoutes = prev && next && prev.routes?.length === next.routes?.length &&
    (prev.routes || []).every((r, i) => r.vehicle_id === next.routes[i]?.vehicle_id &&
      r.customer_ids?.length === next.routes[i]?.customer_ids?.length);
  if (sameRoutes) { drawVehicles(); return; }
  redraw(); fit();
});
watch(() => props.selectedId, redraw);
watch(() => props.selectedVehicle, () => {
  for (const [id, entry] of markers) {
    const el = entry.marker.getElement();
    if (el) el.classList.toggle("focus", props.selectedVehicle === id);
  }
});

onBeforeUnmount(() => {
  if (raf) cancelAnimationFrame(raf);
  markers.clear();
  observer?.disconnect(); map?.remove(); map = null;
});
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
:deep(.veh-icon) { transition: none; }
:deep(.veh-icon.focus span) { outline: 3px solid #0f172a; transform: scale(1.18); }
:deep(.veh-icon span) { transition: transform .15s ease; display: flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 50%; font-size: 13px;
  box-shadow: 0 1px 4px rgba(15,23,42,.4); border: 2px solid #fff; }
.sg-tile-note { font-size: 11px; line-height: 1.5; color: #64748b; margin: 6px 0; }
</style>
