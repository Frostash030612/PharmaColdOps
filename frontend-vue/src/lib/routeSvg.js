/* Delivery re-routing panel — the SVG layer and shared text blocks, ported
   verbatim from renderReroute(). Pure: data (DEPOT/PHARMACIES/ROUTES) + the
   selected mode/node + L bundle in, ready HTML strings out. The Leaflet layer
   (routeGeo/LeafletMap) replaces only the map <svg> when nodes carry `loc`. */
import { interp } from "./format.js";

/* Reshipment NOT required → idle map + cleared box. */
export function rerouteIdleHtml(L) {
  return `
    <svg class="route-svg" viewBox="0 0 360 180">
      <rect x="0" y="0" width="360" height="180" rx="10" fill="#f8fafc"/>
      <circle cx="180" cy="90" r="26" fill="#e2e8f0"/>
      <text x="180" y="95" text-anchor="middle" fill="#94a3b8" font-size="12" font-family="inherit">${L.route.noRoute}</text>
    </svg>
    <div class="idle">${L.route.idle}</div>`;
}

/* The offline hand-built 360×210 string map. */
export function routeMapSvg(depot, pharmacies, route, routeMode, selectedPharm, L) {
  const coords = { depot };
  pharmacies.forEach((p) => (coords[p.id] = p));
  const pts = [depot, ...route.order.map((id) => coords[id])];
  const dPath = pts.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ");
  const stroke = routeMode === "optimized" ? "#14b8a6" : "#dc2626";
  const dash = routeMode === "optimized" ? "" : ' stroke-dasharray="6 5"';

  let svg = `<svg class="route-svg" viewBox="0 0 360 210">
    <rect x="0" y="0" width="360" height="210" rx="10" fill="#f0fdfa"/>
    <path d="${dPath}" fill="none" stroke="${stroke}" stroke-width="2.5"${dash}/>
    <circle cx="${depot.x}" cy="${depot.y}" r="20" fill="#0d9488"/>
    <text x="${depot.x}" y="${depot.y + 5}" text-anchor="middle" fill="#fff" font-size="10" font-weight="700" font-family="inherit">${L.route.depot}</text>`;
  for (const p of pharmacies) {
    const sel = selectedPharm === p.id;
    const fill = sel ? "#14b8a6" : "#fff";
    const col = sel ? "#fff" : "#14b8a6";
    svg += `<circle class="pharm-node" data-ph="${p.id}" cx="${p.x}" cy="${p.y}" r="13" fill="${fill}" stroke="${col}" stroke-width="2.5"/>`;
    svg += `<text x="${p.x}" y="${p.y + 4}" text-anchor="middle" fill="${col}" font-size="10" font-weight="700" font-family="inherit" pointer-events="none">${p.label}</text>`;
  }
  svg += `</svg>`;
  return svg;
}

export function routeToggleHtml(routeMode, L) {
  return `<div class="route-toggle">
    <button class="${routeMode === "optimized" ? "on" : ""}" data-mode="optimized">${L.route.modeOptimized}</button>
    <button class="${routeMode === "original" ? "on" : ""}" data-mode="original">${L.route.modeOriginal}</button>
  </div>`;
}

export function routeMetricsHtml(route, L) {
  return `<div class="metrics">
    <div class="metric"><div class="mv">${route.dist}</div><div class="mk">${L.route.metricDist}</div></div>
    <div class="metric"><div class="mv">${route.time}</div><div class="mk">${L.route.metricTime}</div></div>
    <div class="metric"><div class="mv">${route.cost}</div><div class="mk">${L.route.metricCost}</div></div>
    <div class="metric"><div class="mv">${route.viol}</div><div class="mk">${L.route.metricViol}</div></div>
  </div>`;
}

export function routeViolHtml(route) {
  return route.viol ? `<div class="viol-note">✗ ${route.violNote}</div>` : "";
}

export function pharmDetailHtml(selectedPharm, route, pharmacies, L) {
  if (!selectedPharm) return "";
  const p = pharmacies.find((x) => x.id === selectedPharm);
  if (!p) return "";
  const pos = route.order.indexOf(p.id) + 1;
  return `<div class="pharm-detail"><span class="nm">${p.name}</span><br>` +
    interp(L.route.detail, {
      tw: p.tw, zone: p.zone, demand: p.demand, pos, total: route.order.length,
    }) + `</div>`;
}

export function allocHtml(productName, L) {
  return `<div class="alloc"><span class="strong">${L.route.allocStrong}</span>` +
    interp(L.route.allocPost, { name: productName }) + `</div>`;
}
