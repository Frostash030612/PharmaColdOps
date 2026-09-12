# PharmaColdOps

An explainable decision-support prototype for cold-chain pharmaceutical temperature excursions. When an excursion occurs, PharmaColdOps issues a traceable disposition recommendation (release / quarantine / retest / scrap) and flags whether a separate reshipment workflow should be considered, grounded in WHO / EU GDP / ICH principles and product-specific stability assumptions.

Proposal & related documents live in [`proposal/`](proposal/):

The current proposal baseline is the **2026-09-12 revised EN/ZH Markdown, SVG figures, and regenerated Chinese Word proposal**.
PPT exports are retained as older reference files until the team synchronises them; see [proposal version status](proposal/README.md).

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

Two front-end trees share one dual-mode behaviour (`?api=` → FastAPI backend; offline → built-in JS
engine, byte-identical results). New work goes in **`frontend-vue/`** (Vue 3 + Vite); the older
zero-dependency **`frontend/`** stays available untouched.

**Vue app (`frontend-vue/`, recommended)** — needs Node.js LTS (see below). Uses **pnpm**;
with Node ≥ 16.9 run `corepack enable pnpm` once (no global install needed) and install from the
committed `pnpm-lock.yaml`:

```bash
cd frontend-vue
corepack enable pnpm    # one-off
pnpm install
pnpm dev                       # http://localhost:5173          (offline)
# http://localhost:5173/?api=http://127.0.0.1:8000               (backend mode)
```

**Zero-build app (`frontend/`, switch-over still pending)**:

```bash
python -m http.server 5500 -d frontend
# http://127.0.0.1:5500/index.html?api=http://127.0.0.1:8000
```

Backend (terminal 1, either case):

```bash
.venv/Scripts/python.exe -m uvicorn --app-dir src api.main:app --port 8000
```

**Where the code lives**

- 🖥️ **Front-end (Vue)** — [`frontend-vue/`](frontend-vue/): Vue 3 + Vite SFCs (plain JS), `src/components/`, `src/stores/`, `src/lib/`, `src/i18n/`; data is the generated `src/data/realData.mjs`.
- 🖥️ **Front-end (zero-build legacy)** — [`frontend/`](frontend/): `index.html` (EN), `index-zh.html` (ZH), `real_data.js` (data). Usable until the demo switches over.
- 🌐 **Back-end service** — [`src/api/`](src/api/): FastAPI + Uvicorn routes.
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

Python side:

```bash
python -m venv .venv
# activate the venv, then:
pip install -r requirements.txt
pytest
```

Vue front-end (`frontend-vue/`) additionally needs **Node.js LTS** (`node -v`; Windows:
`winget install --id OpenJS.NodeJS.LTS -e`). Regenerate both demo data files together
(one run, two outputs — they cannot drift):

```bash
.venv/Scripts/python.exe scripts/export_demo_data.py \
  --out frontend/real_data.js --out-esm frontend-vue/src/data/realData.mjs
```

## ML experiments (`src/ml/`)

Shared evaluation helpers live in [`src/ml/evaluate.py`](src/ml/evaluate.py). Run the full experiments:

```bash
python scripts/train_risk_full.py    # LR / LightGBM / XGBoost + SHAP on Kaggle silent-failure
python scripts/train_root_cause.py   # 10-class excursion-cause classifier (vaccine-cold-chain)
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
  `tests/test_rule_engine.py` therefore no longer asserts engine == gold; it **freezes the 18 known
  engine-vs-gold deviations** and pins the agreement rate at 39/57. Full write-up:
  [`docs/annotation_findings_v1.md`](docs/annotation_findings_v1.md); statistics and file fingerprints:
  [`data/processed/agreement_stats.md`](data/processed/agreement_stats.md),
  [`data/processed/PROVENANCE.md`](data/processed/PROVENANCE.md). Re-run the 9/19 engine evaluation with
  `python scripts/evaluate_engine.py --engine <outputs.csv> --private-package <annotation package>`;
  verify the delivered files against their recorded fingerprints (and re-run the leak checks) with
  `python scripts/check_provenance.py --private-package <annotation package>`.

## Singapore road-network input (M5)

C's solvers now accept a directed `(distance, travel_time)` callback. Solomon
remains the default; Singapore uses cached road matrices in km/min. The committed
`data/optimisation/singapore/network.json` contains real OSM matrices and road
geometry for 1 depot + 10 healthcare facilities. Solve and export fully offline
with `python scripts/export_singapore_routes.py`. Rebuild with
`python scripts/build_singapore_network.py --osm-file path/to/Singapore.osm.gz`
(OSMnx; public extract download avoids Overpass throttling).
See [network assumptions and reproduction](docs/singapore_network_assumptions.md)
for facilities, simulated orders, data attribution and environment details.

## Team

4 members — roles and responsibilities in proposal §10.
