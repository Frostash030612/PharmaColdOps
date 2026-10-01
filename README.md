# PharmaColdOps

An explainable decision-support prototype for cold-chain pharmaceutical temperature excursions. When an excursion occurs, PharmaColdOps issues a traceable disposition recommendation (release / quarantine / retest / scrap) and flags whether a separate reshipment workflow should be considered, grounded in WHO / EU GDP / ICH principles and product-specific stability assumptions.

Proposal & related documents live in [`proposal/`](proposal/):

The current working baseline is the **2026-09-28 revised EN/ZH Markdown, presentation materials,
and regenerated speech document**. The submitted English PDF remains a frozen 2026-09-13 record;
see [proposal version status](proposal/README.md) for the documented differences.

- Proposal (EN): [proposal/PharmaColdOps-Proposal-EN.md](proposal/PharmaColdOps-Proposal-EN.md)
- Proposal (中文): [proposal/PharmaColdOps-Proposal-ZH.md](proposal/PharmaColdOps-Proposal-ZH.md)
- Presentation deck: [proposal/PharmaColdOps-Proposal-Presentation.pptx](proposal/PharmaColdOps-Proposal-Presentation.pptx)
- Figures: [`proposal/figures/`](proposal/figures/)
- Ground-truth evaluation design: [proposal/处置决策-ground-truth评估方案.md](proposal/处置决策-ground-truth评估方案.md)

## Modules (IRS technique groups)

新加坡路网与前端的完成范围、实测结果及复用方式：[交付记录](docs/M5_singapore_handover.md)。

| Module | Directory | Technique group |
|---|---|---|
| Disposition rule engine | `src/rule_engine/` | Decision automation |
| Risk prediction & root cause | `src/ml/` | Knowledge discovery & data mining |
| Re-routing optimiser (VRPTW) | `src/optimisation/` | Resource optimisation |
| Knowledge graph & Q&A | `src/knowledge_graph/` | Cognitive systems |
| API / frontend | `src/api/` | Integration |

## Web demo — front-end ↔ back-end

The single **`frontend-vue/`** client supports two modes: `?api=` uses the FastAPI backend and the
default offline mode uses the built-in JS rule-engine equivalent. The older zero-build `frontend/`
tree was retired on 2026-09-12.

**Vue app (`frontend-vue/`, recommended)** — needs Node.js LTS (see below). Uses **pnpm**;
with Node ≥ 16.9 run `corepack enable pnpm` once (no global install needed) and install from the
committed `pnpm-lock.yaml`:

```bash
cd frontend-vue
corepack enable pnpm    # one-off
pnpm install --frozen-lockfile
pnpm dev                       # http://localhost:5173          (offline)
# http://localhost:5173/?api=http://127.0.0.1:8000               (backend mode)
```

**Retired (2026-09-12): zero-build `frontend/`** — deleted; it is replaced entirely by
`frontend-vue/` above. There is nothing to serve from that directory any more.

**Map basemap** — the Leaflet map prefers tiles cached under
[`frontend-vue/public/tiles/`](frontend-vue/public/tiles/), fetched once with
`node scripts/fetch_map_tiles.mjs`, so the demo needs no external request and survives a missing
wifi (it falls back to the online OpenStreetMap layer, then to a route-only view; force the online
layer with `?tiles=osm`). See [docs/前端地图底图说明.md](docs/前端地图底图说明.md).

Backend (terminal 1):

```bash
# macOS / Linux
.venv/bin/python -m uvicorn --app-dir src api.main:app --port 8000

# Windows PowerShell
.venv\Scripts\python.exe -m uvicorn --app-dir src api.main:app --port 8000
```

**Where the code lives**

- 🖥️ **Front-end (Vue)** — [`frontend-vue/`](frontend-vue/): the single Vue 3 + Vite client (EN/ZH,
  offline fallback + `?api=` backend mode), Leaflet map, dispatch console, `src/components/`,
  `src/stores/`, `src/lib/`, `src/i18n/`; data is the generated `src/data/realData.mjs`.
- 🌐 **Back-end service** — [`src/api/`](src/api/): FastAPI + Uvicorn routes.
- 🔄 **Integration endpoints** — `POST /api/route` is a stateless reshipment-route preview;
  `POST /api/dispatch/reshipments` commits a selected candidate into the live delivery operation;
  `POST /api/dispatch/runs/{id}/failure-preview` and `failure-accept` handle a mechanical
  vehicle failure through replacement delivery; `POST /api/dispatch/runs/{id}/delay-preview`
  and `delay-accept` inspect forecast delivery-window misses and commit an operator-approved
  remaining-stop re-sequence; `POST /api/qa` runs bounded, case-specific Neo4j evidence queries.
  The run-level `overnight-preview`, `overnight-accept`, and `next-day` endpoints
  execute parking moves and create the next dated fixed-order run from the actual parked fleet.
  Next-day inventory carries remaining lots; any extra supply must be declared explicitly.

In backend mode, reopen a completed run with **Open closing-day record**. Review parking,
declare any additional next-day supply, confirm the moves, advance the clock until parked,
then create/depart the next fixed-order day. The parked fleet starts from its actual locations;
consumed inventory is not restored and daily mileage starts afresh.
- 🧠 **Decision core** (what the back-end calls) — [`src/rule_engine/`](src/rule_engine/); behaviour is driven by [`rules_config.json`](src/rule_engine/rules_config.json).
- 🔗 **Contract tests** — [`tests/test_api_contract.py`](tests/test_api_contract.py): change `front-end ↔ back-end` fields together with this file.

Full stack + how-to-connect notes for the team: [docs/前后端技术栈与连接说明.md](docs/前后端技术栈与连接说明.md)（中文）.
Knowledge-graph entity/relation model draft: [docs/KG_SCHEMA_v1.md](docs/KG_SCHEMA_v1.md).

## Data layout

`data/` is organised by project module, mirroring `src/` (proposal §7, §8.3):

| Directory | Module | Contents |
|---|---|---|
| `data/ml/` | Risk prediction & root cause | Cold-chain / temperature datasets (Kaggle + Hugging Face) — **see [`data/ml/DATA_DICTIONARY.md`](data/ml/DATA_DICTIONARY.md)** |
| `data/optimisation/solomon/` | Re-routing optimiser | Solomon VRPTW instances (CVRPLIB) |
| `data/processed/` | All modules | Preprocessed feature tables / audit reports (§7.3) — generated, not committed — **except** `agreement_stats.md` + `PROVENANCE.md`, which are annotation deliverables |
| `data/scenarios/` | Disposition rule engine | Gold-standard scenario bank + the annotation workbench that produced it (see below) |

Download the no-login sources with `python scripts/download_data.py`; Kaggle datasets
need a manual `kaggle.json` token (see `PROGRESS.md`). Regenerate the ML dataset audit
with `python scripts/audit_datasets.py` → `data/processed/ml_audit_report.md`.

## Quickstart

Python 3.12 is the supported runtime. From a clean checkout:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d
.venv/bin/python -m pytest -q
```

Windows users can replace `.venv/bin/...` with `.venv\Scripts\...`.
The current 2026-10-01 baseline is **351 passed / 20 skipped**; the skipped tests
require a reachable Neo4j. The earlier 2026-09-30 revision was verified with
**341 passed** with Neo4j connected; see [PROGRESS.md](PROGRESS.md) for versioned checks.
Run `docker compose down` when the local graph is no longer needed; it preserves the graph volume.

Then verify the Vue production build:

```bash
cd frontend-vue
pnpm install --frozen-lockfile
pnpm build
```

Vue front-end (`frontend-vue/`) additionally needs **Node.js LTS** (`node -v`; Windows:
`winget install --id OpenJS.NodeJS.LTS -e`). Regenerate both demo data files together
(one run, two outputs — they cannot drift):

```bash
.venv/bin/python scripts/export_demo_data.py \
  --out-esm frontend-vue/src/data/realData.mjs
```

## ML experiments (`src/ml/`)

Shared evaluation helpers live in [`src/ml/evaluate.py`](src/ml/evaluate.py). Run the full experiments:

```bash
.venv/bin/python scripts/train_risk_full.py    # LR / LightGBM / XGBoost + SHAP on Kaggle silent-failure
.venv/bin/python scripts/train_root_cause.py   # 10-class excursion-cause classifier (vaccine-cold-chain)
```

Results land in `data/processed/` (gitignored); see `PROGRESS.md` for the current numbers and the honesty caveats (no timestamp → non-chronological split; datasets likely synthetic).

## Rule engine (first module — MVP)

A temperature excursion in → a disposition decision out.

- Input: `ExcursionEvent` (product, excursion temp, duration, MKT, packaging, stage)
- Output: `Decision` (disposition, reshipment flag, rule path, evidence)
- Thresholds: `src/rule_engine/rules_config.json` — **placeholders** to be replaced with product-specific WHO/GDP/ICH stability data
- Evaluation: `data/scenarios/scenarios.csv` is the gold-standard scenario bank (proposal §8.3).
  Since 2026-09-12 its `gold_label` column is **independent dual human annotation** — B and C each
  blind-labelled all 57 scenarios, A arbitrated (Cohen's κ = 0.6434) — replacing the placeholder that
  used to be the engine's own output (the circularity proposal §8.3 set out to break).
  `tests/test_rule_engine.py` therefore no longer asserts engine == gold; it **freezes the 3 remaining
  engine-vs-gold deviations** and pins the agreement rate at 54/57. (Before rubric v1.1 the freeze list
  held 18 entries and the pinned rate was 39/57; v1.1 rewrote clause 4 from `quarantine` to `scrap`,
  which dissolved 15 of them and left 3 that point at the gold labels rather than the spec.) Full write-up:
  [`docs/annotation_findings_v1.md`](docs/annotation_findings_v1.md) and the current spec
  [`docs/annotation_rubric_v1.1.md`](docs/annotation_rubric_v1.1.md); statistics and file fingerprints:
  [`data/processed/agreement_stats.md`](data/processed/agreement_stats.md),
  [`data/processed/PROVENANCE.md`](data/processed/PROVENANCE.md). Re-run the 9/19 engine evaluation with
  `python scripts/evaluate_engine.py --engine <outputs.csv> --private-package <annotation package>`;
  verify the delivered files against their recorded fingerprints (and re-run the leak checks) with
  `python scripts/check_provenance.py --private-package <annotation package>`.

## Singapore road-network input (M5)

C's solvers now accept a directed `(distance, travel_time)` callback. Solomon
remains the default; Singapore uses cached road matrices in km/min. The committed
`data/optimisation/singapore/network.json` contains real OSM matrices and road
geometry for **19 nodes**: 1 main depot, 1 third-party warehouse, 14 hospital receiving sites and
3 distribution points. Solve and export fully offline
with `python scripts/export_singapore_routes.py`. Rebuild with
`python scripts/build_singapore_network.py --osm-file path/to/Singapore.osm.gz`
(OSMnx; public extract download avoids Overpass throttling).
See [network assumptions and reproduction](docs/singapore_network_assumptions.md)
for facilities, simulated orders, data attribution and environment details.

## Team

4 members — roles and responsibilities in proposal §10.
