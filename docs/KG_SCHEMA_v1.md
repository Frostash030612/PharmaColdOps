# PharmaColdOps 知识图谱 schema v1（M6）

> 负责人：D · 状态：**v1 草稿**（9/10 出，W1 9/20 定稿）· 对应 DAILY_PLAN D「9/10 ①」与「W1 加载任务（9/14–9/19）」
> 定位：从 schema 文档 → `src/knowledge_graph/schema.py`（9/11 Cypher 约束）→ 加载脚本（9/14+）的唯一事实来源。
> 输入源：`docs/ARCHITECTURE.md`（M6/M7 与主链）、PROGRESS「前后端接口与上云」契约、`src/rule_engine/`（A 引擎字段）、`data/ml/DATA_DICTIONARY.md`（B 口径）。

## 0. 四条建模纪律（与全系统契约一致）

1. **字段名同源、禁自造别名**：`ExcursionEvent` / 决策字段一律用 A 已定字段（引擎 `models.py`、`POST /api/case_close` 记录）；跨成员字段变更必须先改契约文档再改代码。
2. **引用必须可核实**：`Regulation` 节点的条款号与摘要已于 2026-09-10 对照官方 PDF 逐条核对（每节点带 `source_url` + `verified`，**不杜撰条款号**）；A 的「阈值证据表」（9/11）核实后同步 `evidence_url` 属性。
3. **决策写入对齐审计 run**：每次结案（`case_close`）写一条 KG 决策链，节点主键 = `run_id`，幂等防重（对应 W2 9/24「每次判定写入 KG」）。
4. **占位必须标状态**：凡字段尚未定稿的实体（如 ReshipmentOrder 字段），属性表里写清 `pending` 与定稿日期，不"先填了再说"。

## 1. 实体总览（9）

| Label | 现实对应 | 主键 | 来源 | v1 状态 |
|---|---|---|---|---|
| `Product` | 4 款温度敏感产品 | `product_id` | `rules_config.json`（A） | 可加载 |
| `Regulation` | 合规文档（条款级 id 已对官方 PDF 核实） | `clause_id` | 引擎 `regulation` 字符串（A），build 8 条（WHO/EU GDP/ICH/HSA） | 可加载 |
| `SOP` | 操作标准流程 | `sop_id` | 公共程序性指引，文档级（CDC 温度偏移清单 / WHO shake test / EU GDP，2026-09-11 落地，原 9/16 计划提前） | 可加载（2026-09-11 真实来源替换占位） |
| `ExcursionEvent` | 一次结案的温控偏差事件 | `run_id` | `POST /api/case_close` 记录（D 实现的 API） | **case_close 写入已接**（writer，2026-09-11 提前实现，幂等 MERGE） |
| `Disposition` | 处置结果概念（4 类） | `disposition` | `models.Disposition`（A） | **case_close 写入已接**（2026-09-11 提前实现） |
| `Cause` | 决策侧主因代码 | `cause_code` | API `risk_score` 输出（D 实现） | **运行时写入**：随 case_close 经 writer MERGE（2026-09-11） |
| `Facility` | 冷库 / 医院节点 | `facility_id` | C M5 新加坡路由表（`network.json`，OSMnx/Nominatim 地理编码） | 可加载（2026-09-11） |
| `Shipment` | 一次发运（载体：产品 × 起讫设施） | `shipment_id` | **真实发运记录**：Kaggle Cold Chain Shipment Silent Failure Dataset（CC0）8,000 条（`SHP*`，带 `dataset` 属性，无设施/产品边——zone 为匿名编码）；真实事件的发运随 `case_close` 写入（9/24） | 可加载（审计链依赖） |
| `ReshipmentOrder` | 补发单 | `order_id` | 触发侧=引擎 `reshipment_required`；**字段 9/21 契约** | **case_close 写入已接**（仅 `reshipment_required=True` 时创建，2026-09-11 提前实现） |

> **2026-09-11 变更：场景预载移除。** `data/scenarios/scenarios.csv` 为 AI 起草的前端演示数据（57 行），此前由 build 脚本连同真实引擎判定一并写入图（`SHIP-*` / 场景事件 / 决策 / 补发单）。现全部移出图谱——虚构数据不得作为证据出现。scenarios.csv 仍留在磁盘上作为 M3 标注评估工件（proposal §8.3 双人标注），只是不入 Neo4j。运行时链（ExcursionEvent / Disposition / Cause / ReshipmentOrder）此后仅经真实 `case_close` 逐案写入——writer 已于 **2026-09-11 提前实现并接入 `close_case`**（原计划 W2 9/24，见 `src/knowledge_graph/writer.py`）：映射复用 `RULE_TO_REGULATIONS` / `RULE_TO_SOPS`，`Cause` 取 API `risk.cause_code`（确定性口径；`RULE_TO_CAUSE` 属 B 的 M4 根因映射，KG 不先行合并）。

## 2. 实体属性表

### `Product` — 产品与稳定性规格（来源：`rules_config.json`，A 定义；出处属性逐字来自其 `_sources`）

| property | type | 说明 |
|---|---|---|
| `product_id` | string | PK。当前 4 值：`vaccine_2_8` / `frozen_m20` / `insulin_2_8` / `mrna_ultracold` |
| `storage_min_c` | float | 存储下限（有真实来源：WHO TRS 961 Annex 9 / FDA 说明书 / Pfizer EUA） |
| `storage_max_c` | float | 存储上限（同上） |
| `allowable_duration_min` | int | 允许超限时长（原则锚定默认值，量级为工程取值，无公开逐产品数字） |
| `mkt_threshold_c` | float | MKT 阈值（原则锚定默认值，同上） |
| `retestable` | bool | 可否复检（设计假设，胰岛素一项存疑已注明） |
| `freeze_sensitive` | bool | 是否冻敏（WHO TRS 961 Annex 9） |
| `category` | string | 产品类别原型说明（逐字来自 `_sources[pid].category`） |
| `storage_source` | string | 储存范围出处（逐字来自 `_sources[pid].storage_range`） |
| `freeze_source` | string | 冻敏性出处（逐字来自 `_sources[pid].freeze_sensitive`） |
| `threshold_note` | string | 两阈值出处说明（逐字来自 `_sources[pid]`） |
| `design_notes` | string | 其余设计假设（如胰岛素 `retestable`，JSON 串） |
| `source_urls` | list[string] | 引用 URL（`_sources[pid].refs`） |

> 数值与出处的唯一入口是 `rules_config.json`；KG/前端/测试都不得另存一份阈值（同源原则）。出处属性由 `build_graph.py` 从 `_sources` 逐字载入，不在此文件起草。

### `Regulation` — 合规文档（来源：build_graph 8 条，条款号/摘要 2026-09-10 对官方 PDF 逐条核对）

| property | type | 说明 |
|---|---|---|
| `clause_id` | string | PK，如 `R-WHO-TRS961-FREEZE`、`R-EU-GDP-9.2`（与 build_graph 同源） |
| `title` | string | 文档标题 |
| `issuer` | string | `WHO` / `EU` / `ICH` / `HSA` |
| `clause` | string | 条款内容（已核对官方 PDF） |
| `summary` | string | 条款摘要 |
| `source_url` | string | 官方 PDF 出处 |
| `verified` | string | 核对说明（核对日期 + 出处） |

每条处置边上另存引擎**逐条**的 `regulation` 句（见 §3 `EVENT_LEADS_TO_DISPOSITION`），供审计原样回放。

### `SOP` — 操作标准（2026-09-11 起真实来源：公共程序性指引，文档级）

| property | type | 说明 |
|---|---|---|
| `sop_id` | string | PK：`SOP-GDP-001`（温度偏移响应）/ `SOP-GDP-002`（冻结处置 shake test）/ `SOP-GDP-003`（偏差记录与 CAPA） |
| `title` | string | 程序名 |
| `summary` | string | 步骤摘要——逐字取自出处文档（CDC 温度偏移清单 / WHO shake test / EU GDP），**不杜撰步骤** |
| `source_url` | string | 主要出处 URL |
| `verified` | string | 核对说明（核对日期 + 出处） |

> 边界（记录于 ARCHITECTURE.md §6）：真实企业**内部** SOP 为专有文件、公开不可得；本图 SOP 取自**公共程序性指引**，只到文档级。备选方案 B（未采用）：删 SOP 节点类型、功能并入 Regulation，QA 按「无证据不回答」答「该环节 SOP 未录入」。

### `ExcursionEvent` — 结案事件（来源：`POST /api/case_close` 的 `event` 块，A 定义字段）

| property | type | 说明 |
|---|---|---|
| `run_id` | string | PK，= 审计 `runs.jsonl` 的 `run_id`（幂等防重的去重键） |
| `product_id` | string | 产品（→`Product`） |
| `excursion_temp_c` | float | 偏离温度 |
| `duration_min` | int | 时长 |
| `mkt_c` | float | MKT |
| `packaging` | string | `intact` / `compromised` |
| `stage` | string | 环节（词表见 §2 SOP 注） |
| `facility_id` | string | **可选（占位，待 A 契约）**：事件发生设施，词表 = C `facility_id`；缺省不连 `EVENT_OCCURRED_AT` |
| `created_at` | datetime | 结案时间（写库键：同一 `run_id` 后写覆盖 = 幂等） |

### `Disposition` — 处置概念节点（来源：`models.Disposition`，A 定义）

| property | type | 说明 |
|---|---|---|
| `disposition` | string | PK：`release` / `quarantine` / `retest` / `scrap` |
| `reshipment_default` | bool | `scrap` / `quarantine` → `true`（= 引擎 `reshipment_required` 逻辑） |

> 处置**决策实例**不单开节点：每次判定的 `rule_no / reason / rule_path / regulation 句` 存在 `EVENT_LEADS_TO_DISPOSITION` 边的属性上（见 §3），`Disposition` 只作 4 类概念查询端点。

### `Cause` — 决策侧主因（来源：API `risk_score`，D 实现，确定性输出）

| property | type | 说明 |
|---|---|---|
| `cause_code` | string | PK。词表：`frozen` `overtemp` `duration` `mkt` `packaging` `near` `minor` `inband` |
| `score` | int | 同源风险分（3–99，规则启发式）可作事件属性，不单列 |

> 注意：与 B 的 M4 根因 `excursion_cause`（11 类）是**两套口径**——本表走决策 API 的确定性 `cause_code`（可解释、进 UI）；ML 根因只进报告。两套词表的跨映射属 B 的「规则 ↔ ML 特征接口」（9/15 起草 · 9/17 A 会签），KG 不先行合并。

### `Facility` — 设施节点（来源：C 的新加坡路由表 `data/optimisation/singapore/network.json`）

| property | type | 说明 |
|---|---|---|
| `facility_id` | string | PK，与 C M5 路由表**逐字同源**（`W-KN-PIONEER`、`H-NUH`…），禁自造别名 |
| `name` | string | 设施名（C 设施表，逐字） |
| `role` | string | C 词表：`depot` / `customer`（逐字，不重命名） |
| `type` | string | 由 C `role` 派生：depot→`Warehouse`，customer→`Hospital`（v1 客户全是公立医院） |
| `lat` / `lon` | float | **真实地理编码坐标**（OSMnx/Nominatim，OSM 新加坡路网抽取，`network.json` 2026-09-10） |
| `address` | string | 检索地址（C 的 `query` 字段，逐字） |
| `geocoded` | string | 地理编码解析地址（C 的 `geocoder_display_name`） |
| `source_url` | string | 设施出处 URL（sgdi.gov.sg / nhcs.com.sg / kuehne-nagel.com） |
| `verified` | string | 出处说明（network.json 生成时间 + OSM 抽取 sha256 + © OpenStreetMap contributors） |

> 版本变更（2026-09-11）：v1 原为 D 手写近似坐标（`W-TUAS`/`W-JURONG`/`W-CHANGI`、`P-OUTRAM`、`PH-*` 等，无出处）；现整体替换为 C 于 2026-09-10 交付的新加坡路由表（比原计划 9/23–24 提前），KG 的 Shipment 起运点与 ReshipmentOrder 目的地从此与 M5 求解器节点完全一致。药房/综合诊所暂不在 C v1 表内（起步规模 = 1 仓库 + 10 医院，20–50 节点为后续扩展目标），待 C 扩充设施表后经同一地理编码管线入图，不手填。
> 字段映射注意（C `singapore_network_assumptions.md`）：GeoJSON 用 `[longitude, latitude]`，设施表用 `lat` / `lon`；前端 Leaflet 渲染时按 C 约定适配。

### `ReshipmentOrder` — 补发单（v1 仅锚，字段待定）

| property | type | 说明 |
|---|---|---|
| `order_id` | string | PK |
| `destination_facility_id` | string | **占位（待 C 9/21 契约）**：补发目的地；writer 已预留读取（`record.destination_facility_id` 或 `event.destination_facility_id`） |
| 其余 | — | **待 A+C 契约 9/21 终版（D 评审）**——本 v1 不自行造字段；触发侧信息（`run_id` / `disposition` / 产品）暂由关系承担 |

## 3. 关系

核心四条（DAILY_PLAN 指定）+ 主链补强（标 ✚，现 6 条），本 schema 只定**方向与语义**；Cypher 方向与索引已在 `schema.py` 落地（D 9/11 ①，2026-09-11）。

| 关系 | 方向 | 基数 | 含义 | 例 |
|---|---|---|---|---|
| `REGULATED_BY` | `(:Product)-[r]->(:Regulation)` | Product 1—N Regulation | 产品的稳定要求由哪篇法规施加（build_graph 实际实现名，原计划名 `PRODUCT_HAS_REQUIREMENT`） | `vaccine_2_8` → `R-WHO-TRS961-FREEZE`（冻敏原则） |
| `EVENT_CAUSED_BY` | `(:ExcursionEvent)-[]->(:Cause)` | Event N—1 Cause | 本次事件主因 | 冻结事件 → `frozen` |
| `EVENT_LEADS_TO_DISPOSITION` | `(:ExcursionEvent)-[d]->(:Disposition)` | Event N—1 Disposition | **决策链实例**：边属性存现场（见下） | `run_id=…` → `quarantine` |
| `CITES` | `(:ExcursionEvent)-[:CITES]->(:Regulation)` | Event N—M Regulation | **本次案例**引用了哪条法规（由本次触发的 `rule_no` 经 `RULE_TO_REGULATIONS` 映射）。2026-09-13 修正：原先挂在共享的 `Disposition` 节点上（`DISPOSITION_CITED_BY`），导致同处置、不同规则的案例互相串证据；现与 `FOLLOWS` 一样挂在案例上 | `run_id=…` → `R-WHO-TRS961-EXCURSION` |
| ✚ `EVENT_OCCURRED_AT` | `(:ExcursionEvent)-[]->(:Facility)` | Event N—1 Facility | 事件发生在哪个设施（stage 词 → facility.role）；`EventIn.facility_id` 已于 9/12 进契约并落边，结案表单尚未传参（9/13） | `warehouse` 事件 → 对应 depot |
| ✚ `TRIGGERS_RESHIPMENT` | `(:ExcursionEvent)-[]->(:ReshipmentOrder)` | Event 0—1 Order | 判定需补发 → 生成补发单（M3→M5 锚点） | `scrap`/`quarantine` 事件 → 补发单 |
| ✚ `RESHIPS_TO` | `(:ReshipmentOrder)-[]->(:Facility)` | Order 0—1 Facility | 补发单目的地；`destination_facility_id` 已进契约，9/13 起该目的地同时进入 `audit_chain` 的证据列表 | `RO-…` → `H-NUH` |
| ✚ `FOLLOWS` | `(:ExcursionEvent)-[]->(:SOP)` | Event N—M SOP | 本次结案依循的操作流程（由 `rule_no` 经 `RULE_TO_SOPS` 映射；2026-09-11 随 writer 落地，**待 A/C 评审**；实现与 §4 问答路径均用 `FOLLOWS`，2026-09-12 命名对齐） | `run_id=…` → `SOP-GDP-001` |
| ✚ `CONNECTS` | `(:Facility)-[r]-(:Facility)` | Facility 全对全 55 条（无向） | 真实路网最短路径（C `network.json` 矩阵 + 逐对路线几何）：`distance_m` / `duration_s` / `geometry`（JSON 字符串，`[lon,lat]` GeoJSON 序——Neo4j 不支持嵌套列表故序列化）/ `source`；与 M5 求解器同一份矩阵 | `W-KN-PIONEER` ↔ `H-NUH` 13.0 km |
| ✚ `FOLLOWS_PROCEDURE` | `(:Product)-[]->(:SOP)` | Product 1—N SOP | 产品处置所依循的 SOP（由 产品条款 → `RULE_TO_REGULATIONS` → `RULE_TO_SOPS` 推导，与运行时 writer 同表；**待 A/C 评审**） | `vaccine_2_8` → `SOP-GDP-001/002/003` |

`EVENT_LEADS_TO_DISPOSITION` **边属性**（决策现场，审计可回放、可本地化渲染）：`rule_no`(int 1–6) · `reason`(引擎句) · `rule_path`(引擎整句) · `regulation`(引擎逐条句) · `reshipment_required`(bool) · `risk_score`(int) · `cause_code`(→`Cause`) · `decided_at`(datetime)。

## 4. 典型问答路径（W2 `/api/qa` 模板的骨架）

| 问题 | 路径 |
|---|---|
| 为何隔离/报废 | `(e:ExcursionEvent{run_id})-[d:EVENT_LEADS_TO_DISPOSITION]->(dis:Disposition)` → 返回 `dis.disposition + d.reason + d.rule_path` |
| 依据哪条法规 | `(e:ExcursionEvent{run_id})-[:CITES]->(reg:Regulation)`（本次规则映射，9/13 起为案例级） 或走 `d.regulation` 句 → 返回 `reg` 节点 |
| 依据哪条 SOP | `(e:ExcursionEvent{run_id})-[:FOLLOWS]->(sop:SOP)`（writer 由 `rule_no` 映射） → 无节点时返回 `status=insufficient_evidence`（「无证据不回答」已于 9/13 在 `qa.py` 落地） |
| 该原因最常见场景 | ✅ 已实现 `qa.cause_context`：默认取**本案例**的 `EVENT_CAUSED_BY` 主因码，再聚合全部结案案例的 `e.stage / e.product_id` 分布（`/api/qa` 的 `cause_context` 意图） |

## 5. 约束/索引（✅ 已由 `schema.py` 落地，2026-09-11）

- 幂等 `IF NOT EXISTS`；`build_graph` 每次重建前自动 `ensure_constraints`。
- 唯一约束：`Product.product_id` · `ExcursionEvent.run_id` · `Cause.cause_code` · `Disposition.disposition` · `Regulation.clause_id` · `Facility.facility_id` · `SOP.sop_id` · `ReshipmentOrder.order_id` · `Shipment.shipment_id` · `RootCause.cause_id`（后两者不在 9 实体 schema 内，但图内存在，约束保证运行时 writer 的 MERGE 安全）。
- 索引：`ExcursionEvent.product_id` / `stage` / `created_at`（问答聚合与「按产品查历史」用）。

## 6. 未决项（状态复核于 2026-09-13）

1. **Requirement 是否独立成实体** —— ✅ **已决：不拆**。触发条件「若问答需要『某产品允许超限时长多少』这类单点查询」已满足且由 `Product` 属性直接回答（`qa.product_requirements`，4 产品通过 `tests/test_kg_qa.py` 与 `scripts/evaluate_qa.py`）。
2. **条款级引用** —— ⏳ **仍等 A**：A 的阈值证据表尚未落地（仓库内无该文件）；现状每个 `Regulation` 已带 `source_url` + `verified`（文档级），条款级 `evidence_url` 待 A 的表出来再补。
3. **ReshipmentOrder 全字段** —— ✅ **已落地**：`src/optimisation/models.py` 的 `ReshipmentOrder` 已含 `order_id / run_id / product_id / origin_facility_id / destination_facility_id / demand_units / priority / requested_at`，writer 写出 `TRIGGERS_RESHIPMENT` + `RESHIPS_TO`；9/13 起目的地同时进入审计链证据与答案。
4. **Facility 坐标 & role↔stage 词表** —— 坐标 ✅ 已解决（C `network.json`）；role↔stage 词表 ⏳ 待 C 扩充设施表（药房/诊所等）时对齐。
5. **SOP 属性表** —— ✅ 已换真实文档级来源（9/11，决策见 ARCHITECTURE §6：CDC 清单 / WHO shake test / EU GDP，步骤逐字引用）；「用词评审」若 A/C 仍要做，属评审动作，不再是数据未决。
6. **9/13 复核补充**：`CITES` 由「挂在共享 `Disposition` 节点」改为**案例级**（`(ExcursionEvent)-[:CITES]->(Regulation)`，见 §3），修复同处置不同规则案例互相串证据；`/api/qa` 增加机器可读 `status` 四态（§4「无证据不回答」据此落地）；问答评估集见 `data/qa/`、评测脚本 `scripts/evaluate_qa.py`（57 场景 409/409 派生检查通过）。

---
变更记录：9/10 初稿 v1（D）· 基线：ARCHITECTURE M6 / 前后端契约 / A 引擎 `models.py` + `rules_config.json` + `service.py risk_score`。
· 2026-09-11：case_close→KG writer 提前实现（原 W2 9/24）并接入 `close_case`；qa.py 查询切 `run_id` + 边属性形态；`Regulation` 主键统一为 `clause_id`（对齐 build_graph 实际实现）；§3 关系对齐实现（`REGULATED_BY`）并增 `EVENT_FOLLOWS_SOP`（待 A/C 评审）。
· 2026-09-11（同日）：Facility 层补 C 路网边——`CONNECTS` 55 条（C 的 `leg_geometry` 实际含全部 55 对真实路线几何，非仅 depot 辐射 10 条）；`FOLLOWS_PROCEDURE`（Product→SOP 静态推导，待 A/C 评审）。
· 2026-09-11（同日）：writer 预留 facility 边分支（`EVENT_OCCURRED_AT` / `RESHIPS_TO`）——字段名为占位（`event.facility_id` / `destination_facility_id`），A 9/12 / C 9/21 契约到位后自动生效；qa 审计链顺带读出事件设施。
· 2026-09-11（同日）：9/11 ① 完成——`connect.py`（连接工厂，build/writer/qa/schema 统一走它）+ `schema.py`（§5 约束/索引落地）；发现 9/9 计划的仓库根 `docker-compose.yml`/`.env.example` 缺失，已记入 DAILY_PLAN 9/12 ④。
· 2026-09-12：SOP 节点换真实文档级来源（a8a531f：CDC 清单 / WHO shake test / EU GDP，步骤逐字引用出处）、Facility 整体改用 C `network.json`（虚构坐标设施移除）、新增 RootCause 11 类（B 词表）；§1 SOP 行与 §3 `FOLLOWS` 命名对齐实现；9/12 ④ 补齐 `docker-compose.yml` + `.env.example`。
· 2026-09-13：`CITES` 改案例级（修同处置串证据）、`/api/qa` 四态 `status` 落地、补发目的地进审计链证据、新增问答评估集 `data/qa/` + `scripts/evaluate_qa.py`；§6 未决项逐条复核状态。
