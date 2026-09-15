<script setup>
/* The transport map.

   Everything here comes from the operation's own view of itself: `plan.routes`
   carries per-stop `delivered` flags and (live) per-leg road geometry, so the
   map draws what has already been driven separately from what is left, numbers
   the stops in the order they are served, and can overlay an alternative route
   ("改道前 vs 改道后") without guessing where anything falls on a polyline.

   Positions are tweened between polls rather than re-created: re-creating the
   markers every second is what made the trucks blink. */
import { ref, watch, onMounted, onBeforeUnmount, computed } from "vue";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const props = defineProps({
  nodes: { type: Array, required: true },
  plan: { type: Object, required: true },
  selectedId: { type: Number, default: null },
  selectedVehicle: { type: String, default: null },
  text: { type: Object, required: true },
  height: { type: String, default: "290px" },
  legend: { type: Boolean, default: false },
  follow: { type: Boolean, default: false },
  /// Alternative routes to overlay: { id, geojson, color, dashed, weight }.
  overlays: { type: Array, default: () => [] },
  /// Network node ids the current branch event touches (drawn as a ring).
  branchNodeIds: { type: Array, default: () => [] },
  /// The facility whose goods were affected, if any.
  incidentNodeId: { type: Number, default: null },
});
const emit = defineEmits(["select", "selectVehicle"]);
const el = ref(null);
const tileError = ref(false);
const colors = ["#0d9488", "#7c3aed", "#d97706"];
let map, layer, overlayLayer, observer, vehicleLayer;
const markers = new Map();        // vehicle_id -> { marker, from, to, t0, dur }
let raf = null;

const NODES_BY_ID = computed(() =>
  Object.fromEntries(props.nodes.map((node) => [node.node_id, node])));

/* The stop list per vehicle, in service order, with what is already done.
   Live routes carry `legs` (exact geometry per leg); the committed demo plan
   only has the merged line, in which case everything counts as still ahead. */
function routeStops(route) {
  if (route.stops?.length) {
    return route.stops.map((stop, index) => ({
      nodeId: stop.node_id, index: index + 1, delivered: !!stop.delivered,
      orderId: stop.order_id ?? null,
    }));
  }
  return (route.customer_ids || []).map((nodeId, index) => ({
    nodeId, index: index + 1, delivered: false, orderId: null,
  }));
}

/* One merged polyline per route when there is no leg geometry (demo plan). */
function routeLines(route, index) {
  if (route.legs?.length) {
    const done = [], todo = [];
    route.legs.forEach((leg) => (leg.delivered ? done : todo).push(leg.coords));
    return [
      { coords: flatten(done), delivered: true },
      { coords: flatten(todo), delivered: false },
    ].filter((line) => line.coords.length > 1)
      .map((line) => ({ ...line, color: colors[index % colors.length] }));
  }
  const feature = (props.plan.geojson?.features || [])[index];
  const coords = feature?.geometry?.coordinates || [];
  return coords.length > 1
    ? [{ coords, delivered: false, color: colors[index % colors.length] }]
    : [];
}

function flatten(parts) {
  return parts.reduce((all, part) => (all.length ? all.concat(part.slice(1)) : all.concat(part)), []);
}

const toLatLngs = (coords) => coords.map(([lon, lat]) => [lat, lon]);

function fit() {
  if (!map || !layer) return;
  const bounds = layer.getBounds();
  if (bounds.isValid()) map.fitBounds(bounds.pad(0.08));
}

function drawOverlays() {
  if (overlayLayer) overlayLayer.remove();
  overlayLayer = L.featureGroup().addTo(map);
  props.overlays.forEach((item) => {
    const coords = item.geojson?.geometry?.coordinates || [];
    if (coords.length < 2) return;
    L.polyline(toLatLngs(coords), {
      color: item.color || "#0f172a", weight: item.weight || 4,
      opacity: item.dashed ? 0.75 : 0.95,
      dashArray: item.dashed ? "7 7" : null,
    }).bindTooltip(props.text[item.labelKey] || item.label || "", { sticky: true })
      .addTo(overlayLayer);
  });
}

function redraw() {
  if (!map) return;
  if (layer) layer.remove();
  layer = L.featureGroup().addTo(map);

  // Focusing one vehicle dims the others rather than hiding them: the rest of
  // the operation is context, and context that disappears is context lost.
  const dimmed = (vehicleId) =>
    !!props.selectedVehicle && props.selectedVehicle !== vehicleId;

  const onRoute = new Set();
  (props.plan.routes || []).forEach((route, index) => {
    const dim = dimmed(route.vehicle_id);
    routeLines(route, index).forEach((line) => {
      L.polyline(toLatLngs(line.coords), {
        color: line.color, weight: line.delivered ? 3 : 4,
        opacity: (line.delivered ? 0.45 : 0.9) * (dim ? 0.25 : 1),
        dashArray: line.delivered ? "6 6" : null,
      }).addTo(layer);
    });
    routeStops(route).forEach((stop) => {
      onRoute.add(stop.nodeId);
      drawStop(stop, index, dim);
    });
  });
  drawNodes(onRoute);
  drawVehicles();
  drawOverlays();
}

function drawStop(stop, routeIndex, dim) {
  const node = NODES_BY_ID.value[stop.nodeId];
  if (!node) return;
  const color = colors[routeIndex % colors.length];
  const selected = node.node_id === props.selectedId;
  const branch = props.branchNodeIds.includes(node.node_id);
  const marker = L.circleMarker([node.lat, node.lon], {
    radius: stop.delivered ? 5 : 7,
    color: selected ? "#0f172a" : "#fff", weight: 2,
    fillColor: stop.delivered ? "#94a3b8" : color,
    fillOpacity: stop.delivered ? 0.45 : 1,
    opacity: dim ? 0.35 : 1,
  }).addTo(layer).on("click", () => emit("select", node.node_id));
  const label = document.createElement("span");
  label.textContent = `${stop.index}. ${node.name}` +
    (stop.delivered ? ` — ${props.text.delivered}` : "");
  marker.bindTooltip(label, { direction: "top" });
  // The order number sits ON the stop, because "which stop comes next" is the
  // question the map is supposed to answer at a glance.
  L.marker([node.lat, node.lon], {
    interactive: false, zIndexOffset: branch ? 400 : 200,
    icon: L.divIcon({
      className: "stop-num",
      html: `<b style="background:${stop.delivered ? "#94a3b8" : color};opacity:${dim ? 0.4 : 1}">${stop.index}</b>`,
      iconSize: [16, 16], iconAnchor: [-6, 18],
    }),
  }).addTo(layer);
  if (branch) {
    L.circleMarker([node.lat, node.lon], {
      radius: 14, color: "#dc2626", weight: 2, fill: false, dashArray: "4 4",
    }).addTo(layer);
  }
}

/* Every facility in the network stays on the map, so the operation is placed in
   its city rather than floating on a blank background. */
function drawNodes(onRoute) {
  props.nodes.forEach((node) => {
    if (onRoute.has(node.node_id)) return;
    const selected = node.node_id === props.selectedId;
    const branch = props.branchNodeIds.includes(node.node_id);
    const incident = node.node_id === props.incidentNodeId;
    const marker = L.circleMarker([node.lat, node.lon], {
      radius: selected ? 8 : 5,
      color: selected ? "#0f172a" : "#fff", weight: 2,
      fillColor: incident ? "#dc2626" : node.node_id === 0 ? "#0f172a" : "#cbd5e1",
      fillOpacity: 1,
    }).addTo(layer).on("click", () => emit("select", node.node_id));
    const label = document.createElement("span");
    label.textContent = node.name;
    marker.bindTooltip(label, { direction: "top" });
    if (branch) {
      L.circleMarker([node.lat, node.lon], {
        radius: 13, color: "#dc2626", weight: 2, fill: false, dashArray: "4 4",
      }).addTo(layer);
    }
  });
}

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
  for (const [id, entry] of markers) {
    if (!live.has(id)) { entry.marker.remove(); markers.delete(id); }
  }
  if (markers.size && !raf) raf = requestAnimationFrame(step);
}

function step(now) {
  raf = null;
  let moving = false;
  for (const [id, entry] of markers.values()) {
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

/* Follow mode keeps the focused truck in view without re-fitting the whole
   network every second (which would fight the user's own pan and zoom). */
function followVehicle() {
  if (!map || !props.follow) return;
  const id = props.selectedVehicle || props.plan.routes?.[0]?.vehicle_id;
  const entry = id && markers.get(id);
  if (entry) map.panTo(entry.to, { animate: true, duration: 0.4 });
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
  if (sameRoutes) { drawVehicles(); followVehicle(); return; }
  redraw(); fit();
});
watch(() => props.overlays, drawOverlays, { deep: true });
watch(() => props.branchNodeIds, redraw, { deep: true });
watch(() => props.selectedId, redraw);
watch(() => props.selectedVehicle, () => {
  redraw();
  followVehicle();
  for (const [id, entry] of markers) {
    const mark = entry.marker.getElement();
    if (mark) mark.classList.toggle("focus", props.selectedVehicle === id);
  }
});
watch(() => props.follow, followVehicle);

onBeforeUnmount(() => {
  if (raf) cancelAnimationFrame(raf);
  markers.clear();
  observer?.disconnect(); map?.remove(); map = null;
});
</script>

<template>
  <div class="sg-map-wrap" :style="{ height }">
    <div ref="el" class="sg-map" role="region" :aria-label="text.mapLabel"></div>
    <button class="sg-fit" @click="fit">{{ text.reset }}</button>
    <ul v-if="legend" class="sg-legend">
      <li><i class="dot depot"></i>{{ text.depot }}</li>
      <li><i class="dot hospital"></i>{{ text.legendStop }}</li>
      <li><i class="dot done"></i>{{ text.legendDelivered }}</li>
      <li><i class="line todo"></i>{{ text.legendPending }}</li>
      <li><i class="line done-line"></i>{{ text.legendDriven }}</li>
      <li><i class="ring"></i>{{ text.legendBranch }}</li>
    </ul>
  </div>
  <p v-if="tileError" class="sg-tile-note" role="status">{{ text.tiles }}</p>
</template>

<style scoped>
.sg-map-wrap { position: relative; }
.sg-map { height: 100%; width: 100%; border-radius: 8px; background: #eaf0f3; z-index: 0; }
.sg-fit { position: absolute; z-index: 500; top: 10px; right: 10px; background: white; border: 1px solid #cbd5e1; border-radius: 5px; padding: 5px 7px; font-size: 10px; cursor: pointer; }
.sg-legend { position: absolute; z-index: 500; left: 10px; bottom: 10px; margin: 0; padding: 7px 9px; list-style: none;
  background: rgba(255,255,255,.92); border: 1px solid #e2e8f0; border-radius: 8px; font-size: 10px; color: #475569; line-height: 1.7; }
.sg-legend li { display: flex; align-items: center; gap: 5px; }
.sg-legend .dot { width: 9px; height: 9px; border-radius: 50%; border: 1px solid #fff; box-shadow: 0 0 0 1px #cbd5e1; }
.sg-legend .dot.depot { background: #0f172a; }
.sg-legend .dot.hospital { background: #0d9488; }
.sg-legend .dot.done { background: #94a3b8; }
.sg-legend .line { width: 16px; height: 0; border-top: 3px solid #0d9488; }
.sg-legend .line.done-line { border-top-style: dashed; border-top-color: #94a3b8; }
.sg-legend .ring { width: 9px; height: 9px; border-radius: 50%; border: 2px dashed #dc2626; }
:deep(.veh-icon) { transition: none; }
:deep(.veh-icon.focus span) { outline: 3px solid #0f172a; transform: scale(1.18); }
:deep(.veh-icon span) { transition: transform .15s ease; display: flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 50%; font-size: 13px;
  box-shadow: 0 1px 4px rgba(15,23,42,.4); border: 2px solid #fff; }
:deep(.stop-num b) { display: inline-flex; align-items: center; justify-content: center;
  width: 15px; height: 15px; border-radius: 50%; color: #fff; font-size: 9px; font-weight: 700;
  border: 1.5px solid #fff; box-shadow: 0 1px 3px rgba(15,23,42,.35); }
.sg-tile-note { font-size: 11px; line-height: 1.5; color: #64748b; margin: 6px 0; }
</style>
