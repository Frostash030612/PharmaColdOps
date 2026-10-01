/* Check that every i18n key the frontend components read exists in BOTH locale
   bundles. The app carries ~130 keys per locale and en/zh drift is a recurring
   failure mode (a key added on one side renders as the raw key on the other).

   `L.value.x.y` is skipped: that is the Vue ref accessor, not a message key.

   Run from the repo root:
     node scripts/check-frontend-i18n.mjs
*/
import { readFileSync, existsSync } from "node:fs";

const COMPONENTS = [
  "frontend-vue/src/App.vue",
  "frontend-vue/src/components/ReroutePanel.vue",
  "frontend-vue/src/components/BranchCompareModal.vue",
  "frontend-vue/src/components/IncidentList.vue",
  "frontend-vue/src/components/LeafletMap.vue",
  "frontend-vue/src/components/HeaderBar.vue",
  "frontend-vue/src/components/CaseActions.vue",
  "frontend-vue/src/components/CaseDrawer.vue",
  "frontend-vue/src/components/IncidentFilters.vue",
  "frontend-vue/src/components/NewInboundModal.vue",
  "frontend-vue/src/components/SimulationGenerator.vue",
  "frontend-vue/src/components/UrgentOrderPanel.vue",
].filter((f) => existsSync(f));

const bundleOf = (file) =>
  new Function(readFileSync(file, "utf8").replace(/^export default/m, "return"))();

const bundles = {
  EN: bundleOf("frontend-vue/src/i18n/en.js"),
  ZH: bundleOf("frontend-vue/src/i18n/zh.js"),
};
const lookup = (bundle, path) =>
  path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), bundle);

let checked = 0;
let missing = 0;
for (const file of COMPONENTS) {
  const src = readFileSync(file, "utf8");
  const refs = new Set();
  /* text.<key>, and text.value.<key> in template code — both read the same
     bundle, so the "value" hop is dropped rather than treated as a key.
     text.value[...] is dynamic (a computed key), so it is skipped: the key is
     only known at runtime and cannot be checked statically. */
  for (const m of src.matchAll(/(?<!\.)\btext\.(?:value\.)?([a-zA-Z_]\w*)\b(?!\s*\[)/g)) {
    if (m[1] === "value") continue; // passing the ref's whole bundle to a helper
    refs.add(`singapore.${m[1]}`);
  }
  /* L.<section>.<key>, never L.value.<...> */
  for (const m of src.matchAll(/(?<!\.)\bL\.([a-zA-Z_][\w]*)\.([a-zA-Z_]\w*)/g)) {
    if (m[1] === "value") continue;
    refs.add(`${m[1]}.${m[2]}`);
  }
  for (const ref of [...refs].sort()) {
    checked++;
    for (const [name, bundle] of Object.entries(bundles)) {
      if (typeof lookup(bundle, ref) !== "string") {
        console.log(`MISSING ${name}: ${ref}   (read by ${file})`);
        missing++;
      }
    }
  }
}

console.log(`checked ${checked} distinct keys in ${COMPONENTS.length} components -> `
  + (missing ? `${missing} missing` : "all present in EN and ZH"));
process.exitCode = missing ? 1 : 0;
