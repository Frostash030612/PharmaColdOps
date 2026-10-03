# PharmaColdOps

An explainable decision-support prototype for cold-chain pharmaceutical temperature excursions. When an excursion occurs, PharmaColdOps issues a traceable disposition recommendation (release / quarantine / retest / scrap) and flags whether a separate reshipment workflow should be considered, grounded in WHO / EU GDP / ICH principles and product-specific stability assumptions.

M4 advisory inference is now available alongside (not instead of) the rule decision.
Run `.venv/bin/python scripts/train_m4_models.py` before starting the API to generate trusted
local risk/candidate-cause artifacts. The online registration panel accepts explicit simulated
transport/monthly contexts, preserves model snapshots, and never maps a failure score to scrap.
See [M4 integration, limitations and input contracts](docs/M4模型集成.md).

Formal M4 experiments now include outer five-fold validation, provided-facility-ID
and time-forward cause stress tests, independent calibration, context-only ablations,
failure/confusion analysis and hash-matched offline SHAP. Run
`.venv/bin/python scripts/evaluate_m4.py --output data/processed/m4-formal-new`.
Fresh outputs only; serving models and historical cases are not replaced.
See [formal results and reproducibility](docs/M4正式实验.md).

M2 now calculates duration-weighted MKT from explicit simulated temperature intervals,
detects contiguous hot/cold windows, and archives the original series with a selected event.
The new-case panel supports seeded generation and JSON editing; gaps and unsupported cold
rules block automatic registration. See [M2 contracts and demo guide](docs/M2温度序列与MKT.md).

Boundary cases now register for human review without overwriting the original rule result.
The effective human outcome governs reshipment; pending review protects linked deliveries,
and executed outcomes are locked. See [human-review workflow](docs/人工审核与有效处置.md).
Case details export printable standalone HTML and complete JSON snapshots including original
assessments, reviews, recorded delivery state and actual graph coverage.
See [audit export scope and integrity](docs/案例审计报告导出.md).

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

The API-mode delivery panel now includes a reproducible simulated-order generator:
routine, tight-deadline, multi-source/multi-temperature and insufficient-fleet scenarios,
with editable date, seed, demand, windows and resources. Generated JSON includes the
effective configuration and source-data hashes; business inputs remain entirely simulated.
The legacy fixed demo is retained. See [generator guide](docs/模拟订单生成器.md).

Independent urgent delivery now uses the same operation, route candidates and execution
clock without asking for real cargo quantities or warehouse balances. Final parking is
restricted to the five warehouse nodes selected by the operator; hospitals cannot be
end-of-day terminals. Default overnight demos assume supply automatically rather than
requiring quantity entry. See [urgent and parking rules](docs/独立加急与仓库停车规则.md).

Incident registration is now durable and idempotent by draft identity, with a recoverable
browser retry envelope. A header-level offline rule sandbox works without the API and
does not register cases or dispatch routes. See [registration and offline guide](docs/异常登记与离线沙箱.md).

Run `.venv/bin/python scripts/run_demo_acceptance.py` for the reproducible full API workflow
in isolated storage; add `--graph` to verify a configured, seeded test Neo4j. A separate
Playwright CLI script drives the visible Vue main flow. See [full acceptance guide](docs/完整演示与端到端验收.md).
Case registration now commits a durable graph outbox in the same DB transaction. Enable
automatic retry with `KG_SYNC_ENABLED=1`, or run `scripts/sync_knowledge_graph.py`.
See [graph reliability and recovery](docs/知识图谱可靠性与恢复.md), especially before rebuilding a graph.
`scripts/check_case_graph.py` performs a read-only check of actual per-case graph coverage;
`--repair` replays only non-conflicting missing chains. `scripts/verify_graph_recovery.py`
verifies actual graph stop/restart and automatic recovery using only its own temporary container.
`scripts/evaluate_qa.py` now defaults to its own disposable graph and isolated SQLite/JSONL,
cleans graph cases and registration/outbox/archive together, and preserves a manifest/report.
See [QA evaluation safety and options](docs/问答评测工具.md); existing test graphs require explicit opt-in.

新加坡路网与前端的完成范围、实测结果及复用方式：[交付记录](docs/M5_singapore_handover.md)。

| Module | Directory | Technique group |
|---|---|---|
| Disposition rule engine | `src/rule_engine/` | Decision automation |
| Temperature excursions & MKT (M2) | `src/temperature_monitoring.py` | Knowledge discovery & data mining |
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
  Next-day inventory carries remaining model lots; the default demo assumes extra supply automatically.

In backend mode, reopen a completed run with **Open closing-day record**. Review parking,
use the disclosed demo supply assumption, confirm the moves, advance the clock until parked,
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
