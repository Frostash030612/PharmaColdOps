/* Prefetch OpenStreetMap tiles for the Singapore demo area into
   frontend-vue/public/tiles/, so the Leaflet basemap renders offline and
   instantly (no external request during a demo).

   Why this exists: the map previously requested https://tile.openstreetmap.org
   on every load. That is an external dependency (wifi, proxies), it can be
   rate-limited or blocked under the OSM tile usage policy — which explicitly
   allows only light, interactive use — and a blocked basemap leaves grey tiles
   with only the route lines visible (the "Basemap unavailable" note).

   Usage (run from ANY directory; it finds the repo itself, needs internet ONCE):
     node scripts/fetch_map_tiles.mjs                # z10..z14, default bounds
     node scripts/fetch_map_tiles.mjs --zoom 10 15   # custom zoom range
     node scripts/fetch_map_tiles.mjs --dry-run      # list tiles, download none

   It derives the bounding box from frontend-vue/src/data/singaporeRoutes.json
   (the same file the map draws), so the tile set covers exactly the demo area.
   Re-run it if the network is extended (e.g. new facilities outside the box).
*/
import { mkdir, readFile, writeFile, access, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/* Resolve the repo root from this file (scripts/ -> repo), so the command works
   whether it is run from the repo root or from frontend-vue/. */
const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");
const ROUTES = join(ROOT, "frontend-vue", "src", "data", "singaporeRoutes.json");
const OUT = join(ROOT, "frontend-vue", "public", "tiles");

try {
  await stat(ROUTES);
} catch {
  console.error(`cannot find ${ROUTES}\n` +
    `This script must stay inside the repo at <repo>/scripts/fetch_map_tiles.mjs ` +
    `(it reads frontend-vue/src/data/singaporeRoutes.json to size the tile box).`);
  process.exit(2);
}

const args = process.argv.slice(2);
const dryRun = args.includes("--dry-run");
let zMin = 10;
let zMax = 14;
const zi = args.indexOf("--zoom");
if (zi !== -1) {
  zMin = Number(args[zi + 1]);
  zMax = Number(args[zi + 2] ?? args[zi + 1]);
}
const PAD = 0.02;                  // degrees of padding around the network
const UA = "PharmaColdOps-IRSPractice/0.1 (NUS-ISS student project; offline demo cache)";

function lonToX(lon, z) { return Math.floor(((lon + 180) / 360) * 2 ** z); }
function latToY(lat, z) {
  const r = (lat * Math.PI) / 180;
  return Math.floor(((1 - Math.asinh(Math.tan(r)) / Math.PI) / 2) * 2 ** z);
}

const data = JSON.parse(await readFile(ROUTES, "utf8"));
const lats = data.nodes.map((n) => n.lat);
const lons = data.nodes.map((n) => n.lon);
const south = Math.min(...lats) - PAD;
const north = Math.max(...lats) + PAD;
const west = Math.min(...lons) - PAD;
const east = Math.max(...lons) + PAD;

const jobs = [];
for (let z = zMin; z <= zMax; z++) {
  const x0 = lonToX(west, z), x1 = lonToX(east, z);
  const y0 = latToY(north, z), y1 = latToY(south, z);
  for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) jobs.push({ z, x, y });
}

console.log(`area: lat ${south.toFixed(4)}..${north.toFixed(4)}, lon ${west.toFixed(4)}..${east.toFixed(4)}`);
console.log(`zoom ${zMin}..${zMax} -> ${jobs.length} tiles (~${(jobs.length * 16 / 1024).toFixed(1)} MB)`);
if (dryRun) {
  for (const t of jobs.slice(0, 10)) console.log(`  ${t.z}/${t.x}/${t.y}.png`);
  if (jobs.length > 10) console.log(`  ... and ${jobs.length - 10} more`);
  process.exit(0);
}

let ok = 0, skipped = 0, failed = 0;
const CONCURRENCY = 4;
async function one({ z, x, y }) {
  const file = join(OUT, String(z), String(x), `${y}.png`);
  try {
    await access(file);
    skipped++;
    return;
  } catch { /* not cached yet */ }
  const url = `https://tile.openstreetmap.org/${z}/${x}/${y}.png`;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const res = await fetch(url, { headers: { "User-Agent": UA } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const buf = Buffer.from(await res.arrayBuffer());
      if (buf.length < 100) throw new Error("suspiciously small body");
      await mkdir(dirname(file), { recursive: true });
      await writeFile(file, buf);
      ok++;
      return;
    } catch (err) {
      if (attempt === 3) {
        failed++;
        console.warn(`  fail ${z}/${x}/${y}: ${err.message}`);
      } else {
        await new Promise((r) => setTimeout(r, 400 * attempt));
      }
    }
  }
}

let cursor = 0;
await Promise.all(Array.from({ length: CONCURRENCY }, async () => {
  while (cursor < jobs.length) {
    const job = jobs[cursor++];
    await one(job);
    if ((ok + skipped + failed) % 25 === 0) {
      process.stdout.write(`\r  progress ${ok + skipped + failed}/${jobs.length}`);
    }
  }
}));

console.log(`\ndownloaded ${ok}, already cached ${skipped}, failed ${failed} -> ${OUT}`);
console.log("Next: rebuild the frontend (pnpm build / npx vite build) and restart the dev server.");
if (failed) {
  console.log("Failed tiles are usually rate limiting — re-run the script; it skips what it already has.");
  process.exitCode = 1;
}
