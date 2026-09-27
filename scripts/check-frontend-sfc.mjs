/* Compile every SFC with the REAL Vue compiler and report template/script errors.

   Why: counting tags by hand is not trustworthy (comments and attribute values
   confuse it), and Vite's dev server cannot run in every environment. This is
   the authoritative "did I break a template" check.

   Run from the repo root:
     node scripts/check-frontend-sfc.mjs [file.vue ...]
*/
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const DEFAULT_FILES = [
  "frontend-vue/src/App.vue",
  "frontend-vue/src/components/ReroutePanel.vue",
  "frontend-vue/src/components/BranchCompareModal.vue",
  "frontend-vue/src/components/IncidentList.vue",
  "frontend-vue/src/components/LeafletMap.vue",
  "frontend-vue/src/components/HeaderBar.vue",
];

/* pnpm keeps the package in its store and does not hoist it to node_modules/@vue,
   so the store path is resolved explicitly (version wildcard, not pinned). */
function loadCompiler() {
  const store = "frontend-vue/node_modules/.pnpm";
  if (!existsSync(store)) throw new Error(`${store} not found — run pnpm install in frontend-vue/`);
  const dir = readdirSync(store).find((d) => d.startsWith("@vue+compiler-sfc@"));
  if (!dir) throw new Error("no @vue/compiler-sfc in the pnpm store");
  const entry = resolve(store, dir, "node_modules/@vue/compiler-sfc/dist/compiler-sfc.cjs.js");
  return createRequire(resolve("frontend-vue/package.json"))(entry);
}

const { parse, compileTemplate, compileScript } = loadCompiler();
const files = process.argv.slice(2).length ? process.argv.slice(2) : DEFAULT_FILES;

let failed = 0;
for (const file of files) {
  if (!existsSync(file)) {
    console.log(`SKIP ${file} (not found)`);
    continue;
  }
  const source = readFileSync(file, "utf8");
  const { descriptor, errors } = parse(source, { filename: file });
  if (errors.length) {
    console.log(`FAIL ${file}`);
    for (const e of errors) console.log(`      parse: ${e.message}`);
    failed++;
    continue;
  }

  const problems = [];
  try {
    const script = compileScript(descriptor, { id: file });
    if (!script.content.trim()) problems.push("empty compiled script");
  } catch (e) {
    problems.push(`script: ${e.message}`);
  }
  if (descriptor.template) {
    const t = compileTemplate({ source: descriptor.template.content, filename: file, id: file });
    for (const e of t.errors) problems.push(`template: ${e.message || e}`);
  }

  if (problems.length) {
    console.log(`FAIL ${file}`);
    for (const p of problems) console.log(`      ${p}`);
    failed++;
  } else {
    console.log(`OK   ${file}${descriptor.template ? "" : "  (no template)"}`);
  }
}

console.log(failed ? `\n${failed} file(s) failed` : `\n${files.length} file(s) compile cleanly`);
process.exitCode = failed ? 1 : 0;
