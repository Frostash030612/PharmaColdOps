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
