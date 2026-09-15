# M5 新加坡配送网络接入方案 —— 执行说明（写给负责实现的 AI）

> **状态：已执行完毕（2026-09-13 标注）**。本方案当年是写给实现者的一次性作业单，**其中的内容现已全部落地**：`data/optimisation/singapore/{facilities.json,network.json}` 已入库（**2026-09-15 由 1 depot + 10 家公立医院扩至 1 depot + 14 个接收点：11 公立 + 3 私立，15×15 真实有向 OSM 矩阵**）、`osm_extract.py` / `singapore_loader.py` / `singapore_export.py` 已在 `src/optimisation/`。**下面 §0.1 的「未提交改动清单」是 9/10 的历史快照，那批代码早已按本文建议拆成多个 commit 提交**——不要照它再提交一遍。留档价值：几何/矩阵构建口径与来源说明（报告要引）。
>
> 目的：把这份文档喂给另一个能操作这个代码仓库的 AI（或工程师），它不需要再问 Mia 任何背景问题，照着做就能把"新加坡真实路网"接入现有 VRPTW 求解器。
> 仓库：`https://github.com/Frostash030612/PharmaColdOps`（本地路径示例：`/Users/wang/Desktop/PharmaColdOps`，以实际 clone 路径为准）。
> 对应文档：`docs/ARCHITECTURE.md` 第 4 节「运输规划的新加坡本地化（M5）」、`docs/DAILY_PLAN.md` 里 C 角色 W2（9/23–9/26）的任务。
> 角色边界：这是 C（配送优化 VRPTW）一个人的模块，不涉及 A（规则引擎）、B（ML）、D（知识图谱/API/前端）已定的跨成员契约。
> **术语提醒**：全文原写「CP-SAT」/「CP-SAT 求解器」处，实际实现为 **OR-Tools Routing Solver + PATH_CHEAPEST_ARC + GUIDED_LOCAL_SEARCH**；提案 §6.4 已订正为 `not CP-SAT`，报告与后续文档统一用 Routing Solver（GLS）。

---

## 0. 开工前必读

### 0.1 现状（截至 2026-09-10）
`src/optimisation/` 下已经有一批**未提交**的本地改动，且已经跑通：

- 已提交（commit `3de2e66`）：`__init__.py`、`solomon_loader.py`、`models.py`（`Node` / `SolomonInstance` 骨架）、`tests/test_solomon_loader.py`。
- **未提交**（`git status` 显示为 modified / untracked，需要先处理）：
  - `src/optimisation/models.py`（modified，新增了 `VehicleRoute` / `RouteStop` / `ReplanMetrics` / `ReplanResult`）
  - `src/optimisation/routing.py`（untracked，`evaluate_route()` / `build_result()` / `euclidean()`）
  - `src/optimisation/greedy.py`（untracked，`solve_greedy()`，最近邻可行插入贪心算法）
  - `src/optimisation/ortools_solver.py`（untracked，`solve_ortools()`，**OR-Tools Routing Solver + GUIDED_LOCAL_SEARCH**——不是 CP-SAT，见下）
  - `scripts/run_routing_baselines.py`（untracked）
  - `tests/test_routing.py`（untracked，覆盖上面全部逻辑，6 个 Solomon 实例全部 feasible）

**第一步动作**：先把这批已完成、已跑通、但未提交的代码按功能拆成几个 commit 提交掉（例如：`models.py` 的 route/metrics 扩展一个 commit，`routing.py`+`greedy.py`+测试一个 commit，`ortools_solver.py`+测试一个 commit）。commit message 要写清楚做了什么（禁止空泛消息，这是仓库既有纪律，见 `PROGRESS.md`）。**不要跳过这步直接在脏工作区上继续改**，否则后面的改动没法和这批遗留改动区分开。

### 0.2 环境检查
`requirements.txt` 声明的是 conda 环境 `cold-chain`（Python 3.12），已包含 `osmnx>=2.1`、`networkx>=3.6`、`folium>=0.20`、`ortools>=9.15`。但仓库里还有一个 `.venv`（Python 3.10.12），经检查**没有安装** `ortools`/`networkx`/`osmnx` 任何一个。开工前先确认："`python -c "import ortools, networkx"`" 在你实际要用的环境里能跑通，如果只有 `.venv` 且缺包，用 `conda activate cold-chain` 切过去，或者在 `.venv` 里补装依赖——两种都行，但**不要假设 `.venv` 已经装好，先验证**。

### 0.3 网络限制（重要，决定了哪些步骤你现在能不能做）
下面第 3.5、3.7 节涉及调用 OSMnx 拉取 OpenStreetMap 路网（走 Overpass API）、做地理编码（走 Nominatim）。如果你现在运行的环境访问不了 `overpass-api.de` / `nominatim.openstreetmap.org` / `pypi.org`（比如运行在被组织网络策略限制的沙箱容器里——这是我们这次会话实测遇到的情况：云端容器和用户 Mac 上连接的沙箱 shell 都被 403 拦截了这几个域名），那这两节就跑不了。

**正确做法**：
1. 照样把第 3.1–3.4、3.6（代码 + 依赖联网数据的 loader/测试框架）做完、能不联网跑的先跑通；
2. 第 3.5 的建图脚本**写出来但不执行**，第 3.7 同理；
3. 明确报告"这两步需要在有正常公网访问的机器上，用 `cold-chain` 环境跑一次"，把这个动作交回给 Mia 自己执行；
4. **绝不要**在跑不通的情况下编造/伪造 `data/optimisation/singapore/network.json` 的内容然后假装完成了——这个项目的文化是「做不到就如实标注，不许编数字」（`PROGRESS.md`/`ARCHITECTURE.md` 反复强调的原则），编造地理/距离数据比不做更糟。

---

## 1. 目标

在现有 `data/optimisation/solomon/`（抽象欧氏坐标基准）之外，新增一条基于新加坡真实路网的 VRPTW 数据源，**复用**已有的贪心 / OR-Tools 求解器，**不破坏**现有 6 个 Solomon 实例的测试。

## 2. 核心设计问题（为什么不能直接塞数据进去）

`routing.py` 里 `evaluate_route()` 现在直接用 `euclidean(a, b)` 算"两点间的量"，并且隐含 Solomon 的假设：**距离和时间是同一个数**（单位速度）。真实路网给出来的是两个独立的量——米制距离 + 秒级行驶时间——而且是**有向、不对称**的（单行道）。所以不能照搬现有函数，要把"两点间怎么算距离/时间"从写死的函数换成一个可插拔参数：Solomon 走默认实现（保持向后兼容，现有测试不用改），新加坡走矩阵查表。

## 3. 具体改动清单

### 3.1 `src/optimisation/routing.py`

- 新增类型别名：`LegFn = Callable[[Node, Node], tuple[float, float]]`，返回 `(distance, travel_time)`。
- 新增函数：
  ```python
  def euclidean_leg(a: Node, b: Node) -> tuple[float, float]:
      d = euclidean(a, b)
      return d, d
  ```
  保留原有 `euclidean()` 不要删（`greedy.py` 的 tie-break 还在单独用它）。
- `evaluate_route()` 签名改为：
  ```python
  def evaluate_route(
      instance: SolomonInstance,
      customer_ids: Iterable[int],
      *,
      vehicle_id: int = 1,
      leg_fn: LegFn = euclidean_leg,
  ) -> VehicleRoute:
  ```
  函数体内把 `leg = euclidean(current, node)` 换成 `leg_distance, leg_time = leg_fn(current, node)`；`distance += leg_distance`；`arrival = departure + leg_time`（**这是本次改造的关键**：之前 distance 和 arrival 推进用的是同一个数，现在要分开）。返程那段同理：`return_leg_distance, return_leg_time = leg_fn(current, depot)`，`distance += return_leg_distance`，`return_time = departure + return_leg_time`。
- `build_result()` 不用改——它只读 route 级别的汇总字段，不关心底层怎么算的。

### 3.2 `src/optimisation/greedy.py`

- `_best_feasible_insertion()` 和 `solve_greedy()` 都加 `leg_fn: LegFn = euclidean_leg` 参数，透传给内部所有 `evaluate_route(..., leg_fn=leg_fn)` 调用。
- tie-break 那行 `nearest_leg = euclidean(by_id[predecessor_id], customer)` 改成 `nearest_leg, _ = leg_fn(by_id[predecessor_id], customer)`。
- 顺手清理一处遗留死代码：`solve_greedy()` 里这一行
  ```python
  unassigned.remove(next(node_id for node_id in ids if node_id not in set(
      routes[-1].customer_ids if False else ids[:-1]
  ))) if False else None
  ```
  这行的条件恒为 `False`，从未真正执行过，是调试残留，直接删掉。删除后跑一遍 `tests/test_routing.py` 确认所有测试结果不变（这行本来就是死代码，理论上不影响任何行为，但删完必须验证）。

### 3.3 `src/optimisation/ortools_solver.py`

- `solve_ortools()` 加 `leg_fn: LegFn = euclidean_leg` 参数。
- 内部 `distance()` 回调改成：
  ```python
  def distance(from_index: int, to_index: int) -> int:
      a = nodes[manager.IndexToNode(from_index)]
      b = nodes[manager.IndexToNode(to_index)]
      d, _ = leg_fn(a, b)
      return round(d * SCALE)
  ```
- `elapsed()` 回调改成用 `leg_fn` 的时间分量：
  ```python
  def elapsed(from_index: int, to_index: int) -> int:
      a = nodes[manager.IndexToNode(from_index)]
      b = nodes[manager.IndexToNode(to_index)]
      _, t = leg_fn(a, b)
      node = nodes[manager.IndexToNode(from_index)]
      return round(t * SCALE) + node.service * SCALE
  ```
  注意：新加坡场景里 distance（公里）和 time（分钟）的数值量级跟 Solomon 的抽象单位差很远，`SCALE=100` 是为 Solomon 调的，新加坡场景**另外定一个常量**（比如 `SINGAPORE_SCALE`），不要不假思索复用同一个 `SCALE`，否则 OR-Tools 内部的整数离散化精度会有问题。

### 3.4 新增 `src/optimisation/singapore_loader.py`

写法、docstring 密度对标 `solomon_loader.py`。

- 常量：
  ```python
  SINGAPORE_NETWORK_PATH = (
      Path(__file__).resolve().parents[2] / "data" / "optimisation" / "singapore" / "network.json"
  )
  ```
- 主函数：
  ```python
  def load_singapore_instance(path: str | Path = SINGAPORE_NETWORK_PATH) -> tuple[SolomonInstance, LegFn]:
      ...
  ```
  - 读 JSON（schema 见 3.5），按 JSON 里 `nodes` 数组顺序（`node_id` 从 0 开始，0 号必须是 depot）转成 `Node(node_id, x=0, y=0, demand=..., earliest=..., latest=..., service=...)`——**`x`/`y` 在这里没有几何意义，填 0 占位即可**，因为真实距离全部来自矩阵查表，不再从坐标现算。demand / earliest / latest / service 这四个字段是"配送场景假设"，不是路网数据本身，直接从 JSON 同名字段读（生成脚本那一步就要把这些假设值写进 JSON，不要在 loader 里现编）。
  - 从 JSON 的 `matrix.distance_m` / `matrix.duration_s`（二维数组，按 node_id 索引，允许非对称）构造一个闭包：
    ```python
    def leg_fn(a: Node, b: Node) -> tuple[float, float]:
        # 返回 (公里, 分钟)——注意在这里就把单位换算好，不要把米/秒原样传给下游
        dist_km = matrix["distance_m"][a.node_id][b.node_id] / 1000
        time_min = matrix["duration_s"][a.node_id][b.node_id] / 60
        return dist_km, time_min
    ```
  - 返回值：`(SolomonInstance(instance="SINGAPORE_DEMO", vehicle_nr=..., capacity=..., nodes=...), leg_fn)`——**复用 `SolomonInstance` 类，不要新建一个 `SingaporeInstance` 类**（会导致 `greedy.py`/`ortools_solver.py`/`routing.py` 的类型签名对不上，增加不必要的分叉）。
  - 明确校验：矩阵必须是 `n × n` 方阵（`n = len(nodes)`），depot（node 0）的 `demand` 必须是 0——参考 `solomon_loader.py` 里 `_parse_nodes()` 的校验风格（有问题直接 `raise ValueError`，带上文件路径和字段名）。

### 3.5 新增离线建图脚本 `scripts/build_singapore_network.py`

**这一步需要真实公网访问，只能在能连上 Overpass/Nominatim 的机器上跑，不要在网络受限的沙箱里跑**（见 0.3）。

用法：`python scripts/build_singapore_network.py`，跑完写出 `data/optimisation/singapore/network.json`。

```python
"""Offline, one-time build of the Singapore VRPTW network.

Run this manually on a machine with normal internet access (needs to reach
Overpass API + Nominatim). Commit the resulting network.json — nothing
downstream should need OSMnx or network access at test/run time.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import osmnx as ox

OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "optimisation" / "singapore" / "network.json"

# TODO(执行者): 把下面的查询串换成真实、可被 Nominatim geocode 到的地址。
# 第一条必须是 depot（冷链仓/配送中心），role 必须写 "depot"，且只能有一个 depot。
# 建议凑够 ARCHITECTURE.md §4.3 建议的规模：depot + 10~15 个真实新加坡医院/诊所/药房。
FACILITIES = [
    # (显示名, geocode 查询串, role)
    ("<真实冷链仓名称>", "<真实冷链仓地址, Singapore>", "depot"),
    ("Singapore General Hospital", "Singapore General Hospital, Singapore", "customer"),
    ("National University Hospital", "National University Hospital, Singapore", "customer"),
    ("KK Women's and Children's Hospital", "KK Women's and Children's Hospital, Singapore", "customer"),
    ("Tan Tock Seng Hospital", "Tan Tock Seng Hospital, Singapore", "customer"),
    ("Changi General Hospital", "Changi General Hospital, Singapore", "customer"),
    # ...补到 10~15 个
]

def main() -> None:
    depot_count = sum(1 for _, _, role in FACILITIES if role == "depot")
    if depot_count != 1:
        raise SystemExit(f"FACILITIES must have exactly one depot, got {depot_count}")

    graph = ox.graph_from_place("Singapore", network_type="drive")
    graph = ox.add_edge_speeds(graph)
    graph = ox.add_edge_travel_times(graph)

    nodes = []
    for name, query, role in FACILITIES:
        lat, lon = ox.geocode(query)
        osm_node = ox.nearest_nodes(graph, lon, lat)
        nodes.append({"name": name, "role": role, "lat": lat, "lon": lon, "osm_node": osm_node})

    # depot 排到第一位 -> node_id 0
    nodes.sort(key=lambda n: 0 if n["role"] == "depot" else 1)

    n = len(nodes)
    distance_m = [[0.0] * n for _ in range(n)]
    duration_s = [[0.0] * n for _ in range(n)]
    for i in range(n):
        lengths = nx.shortest_path_length(graph, nodes[i]["osm_node"], weight="length")
        times = nx.shortest_path_length(graph, nodes[i]["osm_node"], weight="travel_time")
        for j in range(n):
            if i == j:
                continue
            target = nodes[j]["osm_node"]
            distance_m[i][j] = lengths.get(target, float("inf"))
            duration_s[i][j] = times.get(target, float("inf"))

    output = {
        "instance": "SINGAPORE_DEMO",
        "vehicle_nr": 3,   # 假设值——报告/文档要注明这是演示假设，不是真实车队规模
        "capacity": 200,   # 假设值——对应一车能装的补发疫苗剂数，同上要注明
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "OSMnx graph_from_place('Singapore', network_type='drive'); OSM data via Overpass API",
        "nodes": [
            {
                "node_id": idx,
                "name": f["name"],
                "role": f["role"],
                "lat": f["lat"],
                "lon": f["lon"],
                "demand": 0 if f["role"] == "depot" else 30,        # 假设值，占位
                "earliest_min": 0 if f["role"] == "depot" else 540,   # 09:00
                "latest_min": 1440 if f["role"] == "depot" else 1020, # 17:00
                "service_min": 0 if f["role"] == "depot" else 15,
            }
            for idx, f in enumerate(nodes)
        ],
        "matrix": {"distance_m": distance_m, "duration_s": duration_s},
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_PATH} ({n} nodes)")

if __name__ == "__main__":
    main()
```

**执行者检查清单（这段是设计草稿，不是可以直接抄的成品）**：
- `FACILITIES` 第一条的冷链仓地址是占位符 `<真实冷链仓名称>`/`<真实冷链仓地址>`，必须换成一个真实存在、Nominatim 能查到的地址（不确定用哪个具体地点的话，直接问 Mia，不要自己编一个查不到的地名硬填进去导致 `ox.geocode` 抛异常）；
- `graph_from_place("Singapore", network_type="drive")` 会拉全岛路网，几分钟量级的运行时间是正常的，不是卡死；
- demand / time window / 车队规模这些字段是路网数据推导不出来的业务假设，**必须在生成的 JSON 里保留，并且要在文档里显式注明**"新加坡场景的配送量与时间窗为演示假设，非真实业务数据"——这是这个项目反复强调的诚实边界要求（`PROGRESS.md`/`ARCHITECTURE.md` 好几处都是这个基调），不要漏掉这一条。

### 3.6 新增测试 `tests/test_singapore_routing.py`

- `data/optimisation/singapore/network.json` 是需要联网才能生成的真实数据，**不应该在测试里重新生成**。测试直接读已提交的文件；如果文件还不存在，用 `pytest.mark.skipif` 跳过并给出清晰原因（不是报错），因为不是所有开发环境都已经跑过 3.5 的建图脚本。
- 至少覆盖：
  1. `load_singapore_instance()` 能正常加载：depot（node 0）`demand == 0`；矩阵是 `n × n` 方阵，`n == len(nodes)`。
  2. `solve_greedy(instance, leg_fn=leg_fn)` 能跑出结果（不强求 100% feasible——真实场景可能比 Solomon 紧张，允许有 unserved customer，但函数本身要能跑通不报错）。
  3. `solve_ortools(instance, leg_fn=leg_fn, time_limit_seconds=5)` 同上。
  4. **回归测试**：把现有 `tests/test_routing.py` 全部 6 个 Solomon 实例重新跑一遍，确认改造后（3.1–3.3 的 `leg_fn` 参数化）一个都没坏——这是整改里最重要的检查点，因为改的是 `evaluate_route`/`greedy`/`ortools_solver` 这几个被所有场景共享的核心函数。

### 3.7 GeoJSON 路线导出（对接 D，DAILY_PLAN C 角色 9/26 产出项）

同样需要联网（3.5 的前提满足后才能做）。新增 `scripts/export_singapore_routes.py`（或在 `run_routing_baselines.py` 里加一个 `--singapore` 分支）：把 `solve_greedy` / `solve_ortools` 解出来的路线，按 stop 顺序对每一段 leg 调 `ox.shortest_path` 拿真实道路折线（经纬度序列），拼成 GeoJSON，一条车辆路线一个 `LineString` feature，写到 `data/processed/singapore_routes.geojson`，供 D 的前端 Leaflet 直接加载（`data/processed/` 本身是 gitignore 的产物目录，这个文件不用提交，D 联调时按需重新生成即可）。

---

## 4. 执行顺序（按依赖关系排的，不要跳步）

1. 提交 0.1 列出的现有未提交代码（拆成合理粒度的几个 commit）。
2. 做 0.2 的环境检查，确认能跑 `pytest`、能 `import ortools`。
3. 做 3.1 / 3.2 / 3.3（`leg_fn` 参数化改造）→ 跑 `pytest tests/test_routing.py` 确认 6 个 Solomon 实例全部照常通过 → commit。
4. 写 3.5 的建图脚本代码（不一定能执行，取决于当前环境网络情况）→ commit。
5. **在有公网的真实环境**执行 `scripts/build_singapore_network.py`，生成 `data/optimisation/singapore/network.json` → commit 这个数据文件（体积应该很小，几十个节点的矩阵，不是整张地图）。
6. 写 3.4 的 `singapore_loader.py` + 3.6 的测试 → 跑通 → commit。
7. 写 3.7 的 GeoJSON 导出，在联网环境验证能生成 → commit 脚本本身（生成的 `.geojson` 不用提交）。
8. 把本次引入的假设（depot 地址、demand、time window、车队规模）写一段进 `docs/ARCHITECTURE.md` 第 4 节，或者新开一个 `docs/singapore_network_assumptions.md`，跟 C 角色在 `DAILY_PLAN.md` W2（9/23–9/26）的产出对上，方便 A/D 后续核对和报告引用。

## 5. 明确不要做的事

- 不要改 `models.py` 里 `SolomonInstance` / `Node` 的字段定义——新加坡数据复用这个类就够，不需要单独建 `SingaporeInstance` 类（会导致下游函数签名分叉）。
- 不要把原始 OSM 图（`.graphml` / pickle）提交进 git，只提交算好的 `network.json`（几十节点的矩阵，体积很小）。
- 没有联网条件时，不要编造或伪造 `network.json` 的内容然后假装完成了——宁可只交前面不需要联网的步骤，把需要联网的步骤明确标成"待在有公网的机器上执行"。
- 不要动 A / B / D 的模块代码，也不要碰 `ReshipmentOrder` / `ReplanResult` 的跨成员字段契约——那是 9/21 才由 A+C 敲定、D 评审的东西，这次改动只在 C 自己的模块内部。
