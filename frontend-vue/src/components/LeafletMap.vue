<script setup>
/* Online map layer (dual-layer map). Mounted only when the live route's depot
   AND every pharmacy carry a finite `loc` — today they are all null, so this
   component never mounts and nothing touches the network. Leaflet + its CSS are
   imported lazily at first mount; circles use L.circleMarker to dodge the
   bundler's default-marker-image pitfall. A tile error falls back to the SVG
   layer (parent flips to mapSvg via @tileerror). */
import { ref, watch, onMounted, onBeforeUnmount } from "vue";

const props = defineProps({
  depot: { type: Object, required: true },       // { x, y, loc:{lat,lng} }
  pharmacies: { type: Array, required: true },   // each { id, loc:{lat,lng}, label }
  route: { type: Object, required: true },       // { order:[...] }
  mode: { type: String, required: true },        // optimized | original
  selectedPharm: { type: String, default: null },
});
const emit = defineEmits(["select", "tileerror"]);

const el = ref(null);
let leafMod = null;
let map = null;
let layer = null;
let ready = false;

async function init() {
  leafMod = await import("leaflet");
  await import("leaflet/dist/leaflet.css");
  const L = leafMod;
  map = L.map(el.value, {
    zoomControl: false,
    scrollWheelZoom: false,
    attributionControl: true,
  });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 18,
  }).on("tileerror", () => emit("tileerror")).addTo(map);
  ready = true;
  redraw();
}

function redraw() {
  if (!ready || !map || !leafMod) return;
  if (layer) { map.removeLayer(layer); layer = null; }

  const L = leafMod;
  const pts = [props.depot, ...props.route.order.map((id) =>
    props.pharmacies.find((p) => p.id === id))];
  const latlngs = pts.map((n) => [n.loc.lat, n.loc.lng]);

  layer = L.layerGroup().addTo(map);

  /* route polyline: optimized solid teal, original red dashed (SVG semantics) */
  L.polyline(latlngs, {
    color: props.mode === "optimized" ? "#14b8a6" : "#dc2626",
    weight: 3,
    dashArray: props.mode === "optimized" ? null : "8 7",
  }).addTo(layer);

  /* depot bigger + distinct */
  L.circleMarker([props.depot.loc.lat, props.depot.loc.lng], {
    radius: 14, color: "#fff", weight: 2, fillColor: "#0d9488", fillOpacity: 1,
  }).addTo(layer);

  /* pharmacies selectable */
  props.pharmacies.forEach((p) => {
    const sel = props.selectedPharm === p.id;
    L.circleMarker([p.loc.lat, p.loc.lng], {
      radius: sel ? 11 : 8,
      color: sel ? "#14b8a6" : "#fff",
      weight: 2.5,
      fillColor: sel ? "#fff" : "#14b8a6",
      fillOpacity: 1,
    }).addTo(layer).on("click", () => emit("select", p.id));
    L.marker([p.loc.lat, p.loc.lng], {
      icon: L.divIcon({ className: "", html: `<div style="position:relative;top:-14px;left:0;font-size:11px;font-weight:700;color:#0f766e;white-space:nowrap">${p.label}</div>` }),
    }).addTo(layer);
  });

  map.fitBounds(L.latLngBounds(latlngs).pad(0.25));
}

onMounted(init);
watch(() => [props.route, props.mode, props.selectedPharm], redraw, { deep: true });
onBeforeUnmount(() => { if (map) { map.remove(); map = null; } });
</script>

<template>
  <div class="leaflet-box"><div ref="el" style="width:100%;height:210px"></div></div>
</template>
