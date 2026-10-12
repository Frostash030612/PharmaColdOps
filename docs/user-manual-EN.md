# PharmaColdOps User Manual

> **Version**: October 2026 demo build (local Docker deployment)
> **Audience**: first-time users and evaluators — **no coding required**
> **See also**: architecture in [`README.md`](../README.md) · progress and measured results in [`PROGRESS.md`](../PROGRESS.md) · deployment detail in [Reproduction and local deployment](复现与本机部署.md)

**🌏 Language / 语言:** **English** · [中文](用户手册.md)

---

## Contents

1. [What this system does](#1-what-this-system-does)
2. [Running it in 5 minutes](#2-running-it-in-5-minutes)
3. [Guided demo walkthrough](#3-guided-demo-walkthrough)
4. [What each part of the interface does](#4-what-each-part-of-the-interface-does)
5. [Running without a backend (offline mode)](#5-running-without-a-backend-offline-mode)
6. [Troubleshooting](#6-troubleshooting)
7. [What this system does *not* do (important)](#7-what-this-system-does-not-do-important)
8. [Appendix for developers](#8-appendix-for-developers)

---

## 1. What this system does

When cold-chain pharmaceuticals (vaccines, biologics) suffer a **temperature excursion** — too warm or too cold — during transport or storage, a quality lead must decide what to do with the batch. The usual problem is not a lack of monitoring; it is that **the alarm comes with no traceable reasoning**: the temperature curve exists, but *why* the batch should be scrapped, *which regulation* supports that, and *how* the remaining doses get re-delivered are scattered across emails, spreadsheets and individual experience.

PharmaColdOps closes that loop:

```
Temperature excursion event
   ↓
① Disposition recommendation   release / retest / scrap + rule path + regulatory grounding
   ↓
② Human review                boundary cases are forced to human review; the human
                              conclusion overrides the automatic advice (original kept)
   ↓
③ Reshipment & re-routing     generate replacement demand → compare, on the live run,
                              "re-route this vehicle / send a spare / return to depot"
   ↓
④ Map & audit                 see before/after re-routing on the map; export a printable audit report
   ↓
⑤ Ask "why"                   knowledge-graph Q&A returns the regulation and SOP behind the decision
```

It covers the four IRS technique groups: **decision automation** (rule engine), **knowledge discovery and data mining** (temperature/MKT, risk and root-cause models), **resource optimisation** (VRPTW vehicle routing) and **cognitive systems** (knowledge-graph Q&A).

---

## 2. Running it in 5 minutes

### Option A — one-command Docker (recommended for evaluation)

**Prerequisites:** Docker Desktop running in **Linux container mode**, port 8080 free.

From the repository root:

```bash
# ① generate random passwords and private config (never overwrites, never prints secrets)
.venv/bin/python scripts/configure_demo.py

# ② verify the config parses
docker compose --env-file deploy/demo.env -f deploy/compose.demo.yml config --quiet

# ③ build and start, waiting until everything is ready
docker compose --env-file deploy/demo.env -f deploy/compose.demo.yml up -d --build --wait --wait-timeout 180
```

> **Windows**: replace `.venv/bin/python` with `.venv\Scripts\python.exe`.
> No `.venv` yet? See section 8.

**Then open your browser:**

### 👉 http://127.0.0.1:8080/?lang=en

If the interface appears, you are done. On first start the system seeds an empty graph with rules, regulations, the facility network and baseline shipment records — **this can take one or two minutes**.

**Optional health checks:**

| URL | Meaning |
|---|---|
| `http://127.0.0.1:8080/api/health` | the process is alive |
| `http://127.0.0.1:8080/api/ready` | **stricter**: database, both models and graph dependencies are all ready |

**Shut down when finished** (keeps your data):

```bash
docker compose --env-file deploy/demo.env -f deploy/compose.demo.yml down
```

> ⚠️ **Never add `-v`** — that deletes the data volumes.

### Option B — development mode (when changing code)

See section 8.

---

## 3. Guided demo walkthrough

This is the shortest designed end-to-end path. Click in this order.

### Step 0 — the three areas

- **Left**: event/case list and the registration entry point
- **Centre**: the map (routes and vehicles)
- **Right**: disposition, review, audit and export panels

### Step 1 — create today's main run

In the delivery panel click:

> **🎲 生成今日批次（按日期）** (generate today's batch by date)

The system generates a batch of simulated orders and shows a **preview** (mileage, number of vehicles, facilities to serve, stop sequence). Confirm with:

> **确认发车** (confirm departure)

A vehicle now drives a fixed stop sequence on the map — this is the **main run**.

> 💡 **Why this step first?** A branch event (exception re-routing) can only attach to a **currently running main run**.
> Closing a case before creating a plan is explicitly refused — that is a designed guardrail, not a bug.

### Step 2 — create a temperature excursion

Register an event on the left, or pick an existing case that will be judged **scrap** (for example `R01`).

Important: **pick a case with the same product as the running batch** (`vaccine_2_8` in the demo).
Surplus stock cannot substitute across products. That is by design.

### Step 3 — close the case and see the options immediately

Click:

> **结案并查看处置方案** (close and view disposition options)

This gives you two things at once:

1. **The disposition**: release / retest / scrap, **with its rule path and regulatory grounding** (which rule fired, citing which WHO / EU GDP / ICH source)
2. **A re-routing comparison table** across the candidate actions:

| Candidate | Meaning |
|---|---|
| **Use surplus stock already on the vehicle** and add a stop en route | fastest, no depot return; requires same product and temperature zone |
| **Send a spare vehicle** | the spare departs from the depot |
| **Return to depot to collect** | go back to the depot first |

The table shows, per option, **how much further it drives, the ETA, and which orders are affected** (including those that arrive late as a knock-on effect).

> The map marks the branch at the same time: **red dot** = affected hospital, **red dashed circle** = the new branch stop.

### Step 4 — see before/after re-routing

Click:

> **⛶ 展开地图** (expand map)

In the enlarged transport view:

- **Dashed grey** = the route **before** re-routing
- **Solid red** = the route **after** re-routing
- Delivered stops show a grey **✓**; undelivered stops carry their stop number

You can also change **speed**, **⏸ 暂停** (pause — a genuine clock freeze, not just stopping the refresh), and **跟随车辆** (follow the vehicle).

### Step 5 — commit an option

Pick a row in the comparison table and click:

> **采用此方案** (adopt this option)

The option is written into the running operation. If you adopt "surplus stock on the vehicle", you will see on-vehicle stock decrease while the depot batch stays untouched.

### Step 6 — ask "on what grounds?"

Ask the knowledge graph, for example:

- "Why was this case judged scrap?"
- "What storage conditions does this product require?"

Answers carry **regulation and SOP citations**. When the system has no evidence it says so **explicitly** rather than inventing an answer.

### Step 7 — export the audit report

From the case detail, export a **printable HTML report** and a **complete JSON snapshot** (original automatic advice, human conclusion, delivery state and graph coverage).

### Things that look like failures but are by design

| What you see | What it actually is |
|---|---|
| Closing a case with no plan → refused with a message | guardrail: a branch must attach to a main run |
| The surplus-stock option is missing for another cold product | the surplus is `vaccine_2_8`; products cannot substitute |
| Some events are not auto-dispositioned but demand human review | boundary / low-confidence cases are **forced to human review** |
| The clock stops on its own | the demo clock pauses while orders await review (the panel says so) |

---

## 4. What each part of the interface does

| Area / button | Purpose |
|---|---|
| **🎲 生成今日批次（按日期）** | generate and preview a simulated order batch; confirming creates today's run |
| **确认发车** | depart the fleet against the simulation clock |
| **⏮ 重演这一批 / 重演上一次作业** | replay the same orders (old runs are kept as history); works after a page refresh |
| **结案并查看处置方案** | close the case and immediately list every re-routing candidate; **only your selection is committed** |
| **🔍 预览处置方案 / 对比并选择处置方案** | read-only preview — nothing is reserved until you adopt |
| **采用此方案** | commit the selected candidate into the running operation |
| **⛶ 展开地图** | enlarged transport view: clock, speed, pause, follow, comparison toggle, vehicle list (`Esc` closes) |
| **主动申请人工审核** | escalate the current event to a human; reshipment, "handled" and closing are blocked until reviewed |
| **次日 / 跨天** | end-of-day parking (five warehouse nodes only — hospitals cannot be day-end terminals) and create the next day's fixed plan |
| **导出审计报告** | printable HTML plus a complete JSON snapshot |

**Map legend**: dashed grey = before re-routing / already driven; solid bold = remaining route; numbers on stops = stop sequence; red dots = affected hospitals.

---

## 5. Running without a backend (offline mode)

The front-end contains a **built-in offline rule engine**, so the disposition logic still demonstrates without a backend.

Leave `?api=` empty in the address bar:

```
http://127.0.0.1:8080/?api=          ← explicitly offline
```

**Offline you can**: exercise the rule-based disposition and browse the interface.
**Offline you cannot**: register cases, dispatch deliveries, or reach the real knowledge graph and models.

> If the backend or network fails during a demo, you can fall back to offline mode for the rule-engine part — but **say** that it is the offline fallback, not a real backend result.

---

## 6. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Port 8080 does not open | `docker compose ps` to check containers; a 503 from `/api/ready` means a dependency is not ready — read `docker compose logs api` |
| Port already in use | re-run the configurator with `--port 8081`, or edit the port in `deploy/demo.env` |
| First start is slow | normal — the empty graph is being seeded; wait 1–2 minutes |
| Page says "Knowledge graph unavailable" | the graph is down or unreachable; disposition still works, Q&A degrades to offline guidance |
| Map shows a route but no basemap | offline tiles are not cached and there is no network; it falls back to the route-only view |
| Backend code changed but behaviour did not | **the backend does not auto-reload** — restart uvicorn. A trap the team hit during demos |
| Switch language | `?lang=en` or `?lang=zh` in the address bar |

```bash
# service status
docker compose --env-file deploy/demo.env -f deploy/compose.demo.yml ps

# API logs
docker compose --env-file deploy/demo.env -f deploy/compose.demo.yml logs -f api

# readiness (503 = some dependency is not ready)
curl http://127.0.0.1:8080/api/ready
```

### ⚠️ If you run the tests on a native Windows host

A full `pytest` run on **native Chinese Windows** shows many failures, and **that is not broken code**:
`src/optimisation/case_action_guard.py` uses Unix-only `fcntl` file locking and **deliberately fails closed on
non-Unix platforms**. The team's full baseline (see `PROGRESS.md`) was measured inside a **Linux container**.
Judge code health with Docker's Linux environment, not with red tests on Windows.

---

## 7. What this system does *not* do (important)

Evaluators and users should know these boundaries. **They are disclosed scope, not defects.**

| Boundary | Detail |
|---|---|
| **Data is simulated** | temperature series, orders and quantities are **simulated**; the risk models were trained on public datasets that are **likely synthetic**. The system grants no real pharmaceutical disposition authority |
| **Not a production deployment** | bound to `127.0.0.1` only, **no user authentication**, no public hardening — not a production or compliance system |
| **Does not replace a pharmacist** | thresholds are **engineering assumptions** (principle-anchored defaults), not product-level stability conclusions; regulatory citations stop at document level (clause level for ICH) |
| **Human review is mandatory** | boundary and low-confidence cases require human confirmation; the human conclusion is stored separately and the original automatic advice is never overwritten |
| **Annotator agreement missed target** | dual annotation reached Cohen's κ = **0.6434**, below the 0.80 target — **reported as-is, not massaged by re-testing** |
| **M6 human evaluation is not finished** | frozen inputs and an offline form are ready, but **as of 2026-10-12 no human annotation has been recorded**; independent accuracy is therefore unavailable |
| **ML does not drive online decisions** | M4 model scores are **advisory**, reported but never triggering scrap/release; the front-end risk index is still a rule heuristic |
| **Optimiser limits** | the solver is OR-Tools Routing Solver + GLS (**not CP-SAT**); time-limited results are not guaranteed globally optimal and may differ between runs |

Full uncertainty disclosures live in [`PROGRESS.md`](../PROGRESS.md) and the per-module documents.

---

## 8. Appendix for developers

### Development-mode startup (without Docker)

```bash
# backend (repository root)
# macOS / Linux
.venv/bin/python -m uvicorn --app-dir src api.main:app --port 8000
# Windows PowerShell
.venv\Scripts\python.exe -m uvicorn --app-dir src api.main:app --port 8000

# front-end (second terminal)
cd frontend-vue
pnpm install --frozen-lockfile
pnpm dev
# backend mode: http://localhost:5173/?api=http://127.0.0.1:8000&lang=en
```

### Building the environment from scratch

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-eval.lock.txt
.venv/bin/python -m pip check
npm install --global pnpm@12.4.1
pnpm --dir frontend-vue install --frozen-lockfile
pnpm --dir frontend-vue build
```

**Pinned baseline**: Python 3.12.12 · Node 24.15.0 · pnpm 12.4.1.
`requirements.txt` is the broader research environment, **not** the demo installer.

### Where to look next

| You want | Read |
|---|---|
| modules and technique groups | the Modules table in [`README.md`](../README.md) |
| deployment, backup, restore | [Reproduction and local deployment](复现与本机部署.md) |
| end-to-end acceptance and demo | [Full demo and end-to-end acceptance](完整演示与端到端验收.md) |
| API contracts | [Interface contracts](接口契约.md) |
| registration and offline sandbox | [Incident registration and offline sandbox](异常登记与离线沙箱.md) |
| human review and effective disposition | [Human review and effective disposition](人工审核与有效处置.md) |
| map basemap | [Front-end map basemap](前端地图底图说明.md) |
| v2 shadow (read-only model) | [v2 read-only shadow API and demo entry](v2只读shadow接口与演示入口.md) |
| M6 independent human evaluation | [M6 independent human evaluation handoff guide](M6独立人工评估交接指南.md) |
| case audit export | [Case audit report export](案例审计报告导出.md) |

### Reading paths by role

- **Just want the demo** → sections 2 and 3
- **Deploying it yourself** → section 2, section 6, and [Reproduction and local deployment](复现与本机部署.md)
- **Reviewing the technology** → [`README.md`](../README.md), [`PROGRESS.md`](../PROGRESS.md), [Architecture](ARCHITECTURE.md)
- **Joining the M6 human evaluation** → [M6 independent human evaluation handoff guide](M6独立人工评估交接指南.md)

---

*Maintained by the project team. Where this manual disagrees with the interface or [`PROGRESS.md`](../PROGRESS.md), those win — and please fix this file (team documentation discipline, rule 5).*
