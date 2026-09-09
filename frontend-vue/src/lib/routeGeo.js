/* Routing geometry helpers shared by the SVG layer and the Leaflet layer.
   Leaflet stays dormant until a depot/pharmacy actually carries a finite
   `loc: {lat,lng}` — today every node is `loc: null`, so the SVG map always
   renders and nothing touches the network. */
export function pharmById(pharmacies, id) {
  return pharmacies.find((p) => p.id === id) || null;
}

export function stopIndexOf(route, id) {
  return route.order.indexOf(id);
}

export function nodeHasLoc(node) {
  return !!(node && node.loc && isFinite(node.loc.lat) && isFinite(node.loc.lng));
}

/* Route node sequence [depot, c1, c2, …] returning either the original nodes
   (they carry `.loc`) or null when any node lacks coordinates. */
export function routeNodesWithLoc(depot, pharmacies, route) {
  const nodes = [depot, ...route.order.map((id) => pharmById(pharmacies, id))];
  if (nodes.some((n) => !n || !nodeHasLoc(n))) return null;
  return nodes;
}
