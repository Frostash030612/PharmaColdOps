# PharmaColdOps

An intelligent decision-support system for cold-chain pharmaceutical transport and warehousing. When a temperature excursion occurs, PharmaColdOps issues an explainable disposition (release / quarantine / retest / scrap + reshipment) and generates an alternative inventory-allocation and delivery re-routing plan — grounded in WHO / EU GDP / ICH rules.

- Proposal: [PharmaColdOps-Proposal-EN.md](PharmaColdOps-Proposal-EN.md)
- Presentation deck: [PharmaColdOps-Proposal-Presentation.pptx](PharmaColdOps-Proposal-Presentation.pptx)
- Ground-truth evaluation design: [处置决策-ground-truth评估方案.md](处置决策-ground-truth评估方案.md)

## Modules (IRS technique groups)

| Module | Directory | Technique group |
|---|---|---|
| Disposition rule engine | `src/rule_engine/` | Decision automation |
| Risk prediction & root cause | `src/ml/` | Knowledge discovery & data mining |
| Re-routing optimiser (VRPTW) | `src/optimisation/` | Resource optimisation |
| Knowledge graph & Q&A | `src/knowledge_graph/` | Cognitive systems |
| API / frontend | `src/api/` | Integration |

## Quickstart

```bash
python -m venv .venv
# activate the venv, then:
pip install -r requirements.txt
pytest
```

## Rule engine (first module — MVP)

A temperature excursion in → a disposition decision out.

- Input: `ExcursionEvent` (product, excursion temp, duration, MKT, packaging, stage)
- Output: `Decision` (disposition, reshipment flag, rule path, evidence)
- Thresholds: `src/rule_engine/rules_config.json` — **placeholders** to be replaced with product-specific WHO/GDP/ICH stability data
- Evaluation: `data/scenarios/scenarios.csv` is the gold-standard scenario bank (proposal §8.3); `tests/test_rule_engine.py` asserts the engine matches the gold labels

## Team

4 members — roles and responsibilities in proposal §10.
