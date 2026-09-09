"""Distribution re-planning / VRPTW (M5).

Owner: C (DAILY_PLAN role C). W0 goal: turn the committed Solomon JSON
instances (``data/optimisation/solomon/``) into unified, validated in-memory
data classes so the greedy baseline (W1), CP-SAT / GA (W2+) and the
reshipment → re-route main flow can all consume one input shape.

Greenfield on 2026-09-10: loader + models only. The output contract
(``ReplanResult``) and the ``ReshipmentOrder`` field set are cross-member
contracts finalised 9/21 (A+C draft, D review) — not self-invented here.
"""
