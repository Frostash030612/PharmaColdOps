/* Shared numeric/text helpers — byte-for-byte ports of the demo's fmt/clamp,
   plus a tiny {token} interpolator used by libs that receive the L bundle. */

export function fmt(n, dec = 1) {
  return (Math.round(n * Math.pow(10, dec)) / Math.pow(10, dec)).toString();
}

export function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

/* {token} interpolation — same semantics as i18n's t(), duplicated here so pure
   libs never have to import the i18n module. */
export function interp(tmpl, params) {
  if (!params) return String(tmpl);
  return String(tmpl).replace(/\{(\w+)\}/g, (m, k) => (k in params ? String(params[k]) : m));
}
