# PharmaColdOps

An intelligent decision-support system for cold-chain pharmaceutical transport and warehousing. When a temperature excursion occurs, PharmaColdOps issues an explainable disposition (release / quarantine / retest / scrap + reshipment) and generates an alternative inventory-allocation and delivery re-routing plan — grounded in WHO / EU GDP / ICH rules.

Proposal & related documents live in [`proposal/`](proposal/):

- Proposal (EN): [proposal/PharmaColdOps-Proposal-EN.md](proposal/PharmaColdOps-Proposal-EN.md)
- Proposal (中文): [proposal/PharmaColdOps-Proposal-ZH.md](proposal/PharmaColdOps-Proposal-ZH.md)
- Presentation deck: [proposal/PharmaColdOps-Proposal-Presentation.pptx](proposal/PharmaColdOps-Proposal-Presentation.pptx)
- Figures: [`proposal/figures/`](proposal/figures/)
- Ground-truth evaluation design: [proposal/处置决策-ground-truth评估方案.md](proposal/处置决策-ground-truth评估方案.md)

## Modules (IRS technique groups)

| Module | Directory | Technique group |
|---|---|---|
| Disposition rule engine | `src/rule_engine/` | Decision automation |
| Risk prediction & root cause | `src/ml/` | Knowledge discovery & data mining |
| Re-routing optimiser (VRPTW) | `src/optimisation/` | Resource optimisation |
| Knowledge graph & Q&A | `src/knowledge_graph/` | Cognitive systems |
| API / frontend | `src/api/` | Integration |

## Web demo — front-end ↔ back-end

The demo has two modes. Open `frontend/index.html` offline (self-contained JS fallback), or add
`?api=http://127.0.0.1:8000` to route **all** decisions through the FastAPI backend
(`src/api/`) running the real Python rule engine. The backend decides *semantics*; each locale
front-end maps them to wording locally.

```bash
.venv/Scripts/python.exe -m uvicorn --app-dir src api.main:app --port 8000   # terminal 1
python -m http.server 5500 -d frontend                                        # terminal 2
# http://127.0.0.1:5500/index.html?api=http://127.0.0.1:8000
```

**Where the code lives**

- 🖥️ **Front-end** — edit only [`frontend/`](frontend/): `index.html` (EN), `index-zh.html` (ZH), `real_data.js` (data).
- 🌐 **Back-end service** — [`src/api/`](src/api/): FastAPI + Uvicorn routes.
- 🧠 **Decision core** (what the back-end calls) — [`src/rule_engine/`](src/rule_engine/); behaviour is driven by [`rules_config.json`](src/rule_engine/rules_config.json).
- 🔗 **Contract tests** — [`tests/test_api_contract.py`](tests/test_api_contract.py): change `front-end ↔ back-end` fields together with this file.

Full stack + how-to-connect notes for the team: [docs/前后端技术栈与连接说明.md](docs/前后端技术栈与连接说明.md)（中文）.

## Data layout

`data/` is organised by project module, mirroring `src/` (proposal §7, §8.3):

| Directory | Module | Contents |
|---|---|---|
| `data/ml/` | Risk prediction & root cause | Cold-chain / temperature datasets (Kaggle + Hugging Face) — **see [`data/ml/DATA_DICTIONARY.md`](data/ml/DATA_DICTIONARY.md)** |
| `data/optimisation/solomon/` | Re-routing optimiser | Solomon VRPTW instances (CVRPLIB) |
| `data/processed/` | All modules | Preprocessed feature tables / audit reports (§7.3) — generated, not committed |

Download the no-login sources with `python scripts/download_data.py`; Kaggle datasets
need a manual `kaggle.json` token (see `PROGRESS.md`). Regenerate the ML dataset audit
with `python scripts/audit_datasets.py` → `data/processed/ml_audit_report.md`.

## Quickstart

```bash
python -m venv .venv
# activate the venv, then:
pip install -r requirements.txt
pytest
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
- Evaluation: `data/scenarios/scenarios.csv` is the gold-standard scenario bank (proposal §8.3); `tests/test_rule_engine.py` asserts the engine matches the gold labels

## Team

4 members — roles and responsibilities in proposal §10.
