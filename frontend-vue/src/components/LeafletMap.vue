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
  /// Archived incidents rendered as first-class map markers.
  incidentEvents: { type: Array, default: () => [] },
  /// While a comparison is shown, this vehicle's own pending line is faded so
  /// the two options ("before" grey / "after" red) are what the eye lands on.
  compareVehicle: { type: String, default: null },
});
const emit = defineEmits(["select", "selectVehicle", "selectIncident"]);
const el = ref(null);
const tileError = ref(false);
const colors = ["#0d9488", "#7c3aed", "#d97706"];
let map, layer, overlayLayer, observer, vehicleLayer;
let fellBackToOnline = false;     // local basemap missing -> tried the online layer once
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

/* One merged polyline per route when there is no leg geometry (demo plan).
   "Driven" comes from the schedule (has the truck been along this leg), not from
   the stop's order being delivered: the last leg home serves no order and would
   otherwise stay "still ahead" for ever. */
function routeLines(route, index) {
  const color = colors[index % colors.length];
  if (route.legs?.length) {
    const done = [], todo = [];
    route.legs.forEach((leg) => {
      const driven = leg.driven ?? leg.delivered;
      (driven ? done : todo).push(leg.coords);
    });
    return [
      { coords: flatten(done), delivered: true },
      { coords: flatten(todo), delivered: false },
    ].filter((line) => line.coords.length > 1)
      .map((line) => ({ ...line, color }));
  }
  const feature = (props.plan.geojson?.features || [])[index];
  const coords = feature?.geometry?.coordinates || [];
  return coords.length > 1 ? [{ coords, delivered: false, color }] : [];
}

/* Driven and pending must not look alike. Grey-on-grey was the first attempt and
   it read as "just another road" on the OSM basemap: the driven part is now a
   darker solid grey and BOTH parts get a white casing, so each line separates
   from the other and from the map underneath. */
const DONE_COLOR = "#475569";

function drawLine(line, dim) {
  const color = line.delivered ? DONE_COLOR : line.color;
  const weight = line.delivered ? 3.5 : 5;
  L.polyline(toLatLngs(line.coords), {
    color: "#ffffff", weight: weight + 4,
    opacity: (line.delivered ? 0.55 : 0.9) * (dim ? 0.25 : 1),
  }).addTo(layer);
  L.polyline(toLatLngs(line.coords), {
    color, weight,
    opacity: (line.delivered ? 0.8 : 1) * (dim ? 0.25 : 1),
    dashArray: line.delivered ? "9 7" : null,
  }).addTo(layer);
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
    const comparing = props.overlays.length > 0
      && props.compareVehicle === route.vehicle_id;
    const dim = dimmed(route.vehicle_id) || comparing;
    routeLines(route, index).forEach((line) => drawLine(line, dim));
    routeStops(route).forEach((stop) => {
      onRoute.add(stop.nodeId);
      drawStop(stop, index, dim);
    });
  });
  drawNodes(onRoute);
  drawIncidentEvents();
  drawVehicles();
  drawOverlays();
}

/* Multiple archived events can belong to one hospital.  One marker per
   facility keeps the map readable; the badge shows the count and opens the
   newest event (the rail still exposes every individual record). */
function drawIncidentEvents() {
  const groups = new Map();
  props.incidentEvents.forEach((event) => {
    if (!groups.has(event.nodeId)) groups.set(event.nodeId, []);
    groups.get(event.nodeId).push(event);
  });
  for (const [nodeId, events] of groups) {
    const node = NODES_BY_ID.value[nodeId];
    if (!node || !events.length) continue;
    const latest = events[0];
    const marker = L.marker([node.lat, node.lon], {
      zIndexOffset: 650,
      icon: L.divIcon({
        className: "incident-icon",
        html: `<span style="background:${latest.color || '#dc2626'}">!${events.length > 1 ? `<small>${events.length}</small>` : ""}</span>`,
        iconSize: [30, 30], iconAnchor: [15, 30],
      }),
    }).addTo(layer).on("click", () => emit("selectIncident", latest.id));
    marker.bindTooltip(`${node.name} · ${events.length} ${props.text.incidentCount || "incident(s)"}`,
      { direction: "top" });
  }
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
  // question the map is supposed to answer at a glance. A served stop gets a
  // tick instead: its position in the sequence no longer matters.
  L.marker([node.lat, node.lon], {
    interactive: false, zIndexOffset: branch ? 400 : 200,
    icon: L.divIcon({
      className: "stop-num",
      html: stop.delivered
        ? `<b class="tick" style="opacity:${dim ? 0.4 : 1}">✓</b>`
        : `<b style="background:${color};opacity:${dim ? 0.4 : 1}">${stop.index}</b>`,
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

/* A point along a road polyline at ``fraction`` of its length.
   Interpolating in a straight line between two polled positions cuts every
   corner: at 60x a single poll covers up to a kilometre of winding road, so the
   truck visibly left the street. Riding the leg's own polyline keeps it on it. */
function pointAlong(coords, fraction) {
  if (!coords?.length) return null;
  if (coords.length === 1) return coords[0];
  const spans = [];
  let total = 0;
  for (let i = 1; i < coords.length; i += 1) {
    const [x1, y1] = coords[i - 1];
    const [x2, y2] = coords[i];
    const length = Math.hypot(x2 - x1, y2 - y1);
    spans.push(length);
    total += length;
  }
  if (total <= 0) return coords[0];
  const clamped = Math.max(0, Math.min(1, fraction));
  let target = total * clamped;
  for (let i = 0; i < spans.length; i += 1) {
    if (target <= spans[i] || i === spans.length - 1) {
      const rest = spans[i] ? target / spans[i] : 0;
      const [x1, y1] = coords[i];
      const [x2, y2] = coords[i + 1];
      return [x1 + (x2 - x1) * rest, y1 + (y2 - y1) * rest];
    }
    target -= spans[i];
  }
  return coords[coords.length - 1];
}

/// The road polyline of one leg, keyed the way the backend reports it.
function legKey(vehicleId, from, to) { return `${vehicleId}|${from}:${to}`; }

function legRegistry() {
  const registry = new Map();
  (props.plan.routes || []).forEach((route) => {
    (route.legs || []).forEach((leg) => {
      registry.set(legKey(route.vehicle_id, leg.from, leg.to), leg.coords);
    });
  });
  return registry;
}

const TWEEN_MS = 1000;

function ensureVehicleLayer() {
  if (!vehicleLayer) vehicleLayer = L.layerGroup().addTo(map);
}

function drawVehicles() {
  if (!map) return;
  ensureVehicleLayer();
  const registry = legRegistry();
  const live = new Set();
  (props.plan.routes || []).forEach((route, i) => {
    const track = route.track;
    // A truck that is home is not on the road any more — but one whose orders
    // are all delivered and is still driving back IS, and stays visible.
    if (!track || !track.position || (track.finished && route.status !== "failed")) return;
    live.add(route.vehicle_id);
    const key = legKey(route.vehicle_id, track.leg_from, track.leg_to);
    const leg = route.status === "failed" ? null : registry.get(key);
    const target = pointAlong(leg, track.leg_fraction);
    const latLng = target ? L.latLng(target[1], target[0])
      : L.latLng(track.position[1], track.position[0]);
    let entry = markers.get(route.vehicle_id);
    if (!entry) {
      const marker = L.marker(latLng, {
        zIndexOffset: 500,
        icon: L.divIcon({
          className: "veh-icon",
          html: `<span style="background:${colors[i % colors.length]}">🚚</span>`,
          iconSize: [24, 24], iconAnchor: [12, 12],
        }),
      }).bindTooltip(route.vehicle_id, { direction: "top" }).addTo(vehicleLayer);
      marker.on("click", () => emit("selectVehicle", route.vehicle_id));
      entry = { marker, t0: 0, leg: leg, legKey: key, fromFraction: 0,
                toFraction: track.leg_fraction, fromPoint: latLng, toPoint: latLng };
      markers.set(route.vehicle_id, entry);
    } else {
      // Animate the leg FRACTION, not the position: same leg → carry on from
      // where the marker already is; new leg → glide across the join.
      // The comparison MUST be by key, not by array identity: every poll brings
      // freshly parsed arrays, so an identity check is never true and the marker
      // would be yanked back to the start of its leg once a second.
      const sameLeg = entry.legKey === key && !!entry.leg;
      entry.fromPoint = entry.marker.getLatLng();
      entry.fromFraction = sameLeg ? entry.toFraction : 0;
      entry.leg = leg;
      entry.legKey = key;
      entry.toFraction = track.leg_fraction;
      entry.toPoint = latLng;
      entry.t0 = performance.now();
    }
    const el = entry.marker.getElement();
    if (el) el.classList.toggle("focus", props.selectedVehicle === route.vehicle_id);
    if (el && route.status === "failed") {
      const badge = el.querySelector("span");
      if (badge) { badge.style.background = "#dc2626"; badge.textContent = "⚠"; }
    }
  });
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
    const onRoad = entry.leg
      ? pointAlong(entry.leg, entry.fromFraction + (entry.toFraction - entry.fromFraction) * k)
      : null;
    if (onRoad) {
      entry.marker.setLatLng(L.latLng(onRoad[1], onRoad[0]));
    } else {
      entry.marker.setLatLng(L.latLng(
        entry.fromPoint.lat + (entry.toPoint.lat - entry.fromPoint.lat) * k,
        entry.fromPoint.lng + (entry.toPoint.lng - entry.fromPoint.lng) * k,
      ));
    }
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
  /* Basemap. Local tiles (public/tiles, fetched once by
     scripts/fetch_map_tiles.mjs) are preferred: no external request during a
     demo, nothing to rate-limit or block, and it works with the wifi off.
     Everything the map actually demonstrates — routes, depot, facilities,
     simulated clock — is drawn from bundled data either way, so a missing
     basemap degrades to a readable diagram instead of an empty box.
     Force the online layer with ?tiles=osm, e.g. for a different city. */
  const useOnlineTiles = new URLSearchParams(location.search).get("tiles") === "osm";
  const baseLayer = useOnlineTiles
    ? L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
        maxZoom: 18,
      })
    : L.tileLayer("./tiles/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> (tiles cached locally)',
        maxZoom: 18,
      });
  baseLayer.on("tileerror", () => {
    /* Local tiles absent → fall back to the online layer once; if that also
       fails, the note under the map says so and the routes stay visible. */
    if (!tileError.value && !useOnlineTiles && !fellBackToOnline) {
      fellBackToOnline = true;
      map?.removeLayer(baseLayer);
      const online = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
        maxZoom: 18,
      });
      online.on("tileerror", () => { tileError.value = true; }).addTo(map);
      return;
    }
    tileError.value = true;
  }).addTo(map);
  redraw(); fit();
  observer = new ResizeObserver(() => map?.invalidateSize());
  observer.observe(el.value);
});
watch(() => props.plan, (next, prev) => {
  // Only a changed route SET re-frames the map, or it would fight the user's
  // pan/zoom every second. The drawing itself must happen on every update
  // though: delivering a stop does not change the shape of the route (the stop
  // list keeps delivered stops), so skipping the redraw left the map showing the
  // original all-pending colours for the whole run — the truck moved, the
  // "already driven" grey never appeared.
  const sameRoutes = prev && next && prev.routes?.length === next.routes?.length &&
    (prev.routes || []).every((r, i) => r.vehicle_id === next.routes[i]?.vehicle_id &&
      r.customer_ids?.length === next.routes[i]?.customer_ids?.length);
  redraw();
  if (!sameRoutes) fit();
  followVehicle();
});
watch(() => props.overlays, drawOverlays, { deep: true });
watch(() => props.branchNodeIds, redraw, { deep: true });
watch(() => props.incidentEvents, redraw, { deep: true });
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
.sg-legend .dot.done { background: #b8c0cc; }
.sg-legend .line { width: 18px; height: 0; border-top: 4px solid #0d9488; box-shadow: 0 0 0 1.5px #fff; }
.sg-legend .line.done-line { border-top: 3px dashed #475569; }
.sg-legend .ring { width: 9px; height: 9px; border-radius: 50%; border: 2px dashed #dc2626; }
:deep(.veh-icon) { transition: none; }
:deep(.veh-icon.focus span) { outline: 3px solid #0f172a; transform: scale(1.18); }
:deep(.veh-icon span) { transition: transform .15s ease; display: flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 50%; font-size: 13px;
  box-shadow: 0 1px 4px rgba(15,23,42,.4); border: 2px solid #fff; }
:deep(.stop-num b) { display: inline-flex; align-items: center; justify-content: center;
  width: 15px; height: 15px; border-radius: 50%; color: #fff; font-size: 9px; font-weight: 700;
  border: 1.5px solid #fff; box-shadow: 0 1px 3px rgba(15,23,42,.35); }
:deep(.stop-num b.tick) { background: #64748b; font-size: 10px; }
:deep(.incident-icon span) { position: relative; display: grid; place-items: center; width: 28px; height: 28px;
  border-radius: 50%; color: #fff; border: 2px solid #fff;
  box-shadow: 0 2px 8px rgba(15,23,42,.4); font-size: 15px; font-weight: 900; }
:deep(.incident-icon small) { position: absolute; right: -7px; top: -7px; min-width: 16px; height: 16px;
  display: grid; place-items: center; border-radius: 999px; background: #0f172a; border: 1px solid #fff;
  color: #fff; font-size: 8px; }
.sg-tile-note { font-size: 11px; line-height: 1.5; color: #64748b; margin: 6px 0; }
</style>
