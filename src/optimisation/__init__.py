"""Distribution re-planning / VRPTW (M5).

Owner: C (DAILY_PLAN role C). W0 goal: turn the committed Solomon JSON
instances (``data/optimisation/solomon/``) into unified, validated in-memory
data classes so the three static solvers — the greedy baseline (``greedy``),
OR-Tools Routing Solver with Guided Local Search (``ortools_solver``) and the
genetic algorithm (``ga_solver``) — and the reshipment → re-route main flow can
all consume one input shape.  The three-way comparison is produced by
``scripts/run_routing_baselines.py``.

The output contract (``ReplanResult``) and the ``ReshipmentOrder`` bridge are
shared contracts used by the API, routing solvers and knowledge graph.
"""
