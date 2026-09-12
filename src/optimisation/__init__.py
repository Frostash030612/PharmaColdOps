"""Distribution re-planning / VRPTW (M5).

Owner: C (DAILY_PLAN role C). W0 goal: turn the committed Solomon JSON
instances (``data/optimisation/solomon/``) into unified, validated in-memory
data classes so the greedy baseline (W1), CP-SAT / GA (W2+) and the
reshipment → re-route main flow can all consume one input shape.

The output contract (``ReplanResult``) and the ``ReshipmentOrder`` bridge are
shared contracts used by the API, routing solvers and knowledge graph.
"""
