# PharmaColdOps 知识图谱 schema v1（M6）

> 负责人：D · 状态：**v1 草稿**（9/10 出，W1 9/20 定稿）· 对应 DAILY_PLAN D「9/10 ①」与「W1 加载任务（9/14–9/19）」
> 定位：从 schema 文档 → `src/knowledge_graph/schema.py`（9/11 Cypher 约束）→ 加载脚本（9/14+）的唯一事实来源。
> 输入源：`docs/ARCHITECTURE.md`（M6/M7 与主链）、PROGRESS「前后端接口与上云」契约、`src/rule_engine/`（A 引擎字段）、`data/ml/DATA_DICTIONARY.md`（B 口径）。

## 0. 四条建模纪律（与全系统契约一致）

1. **字段名同源、禁自造别名**：`ExcursionEvent` / 决策字段一律用 A 已定字段（引擎 `models.py`、`POST /api/case_close` 记录）；跨成员字段变更必须先改契约文档再改代码。
2. **引用只到文档级**：`Regulation` 节点只存文档级引用（WHO TRS 961 Annex 9 · EU GDP 2013/C 343/01），**不杜撰条款号**；条款级证据由 A 的「阈值证据表」（9/11）核实后同步，届时再补 `evidence_url` 之类属性。
3. **决策写入对齐审计 run**：每次结案（`case_close`）写一条 KG 决策链，节点主键 = `run_id`，幂等防重（对应 W2 9/24「每次判定写入 KG」）。
4. **占位必须标状态**：凡字段尚未定稿的实体（SOP、ReshipmentOrder、Facility 坐标），属性表里写清 `pending` 与定稿日期，不"先填了再说"。

## 1. 实体总览（8）

| Label | 现实对应 | 主键 | 来源 | v1 状态 |
|---|---|---|---|---|
| `Product` | 4 款温度敏感产品 | `product_id` | `rules_config.json`（A） | 可加载 |
| `Regulation` | 合规文档（文档级） | `reg_id` | 引擎 `regulation` 字符串（A） | 可加载 |
| `SOP` | 操作标准流程 | `sop_id` | D 起草占位 → 9/16 从文档级原则抽 | **占位** |
| `ExcursionEvent` | 一次结案的温控偏差事件 | `run_id` | `POST /api/case_close` 记录（D 实现的 API） | 可加载 |
| `Disposition` | 处置结果概念（4 类） | `disposition` | `models.Disposition`（A） | 可加载 |
| `Cause` | 决策侧主因代码 | `cause_code` | API `risk_score` 输出（D 实现） | 可加载 |
| `Facility` | 冷库 / 药房 / 医院节点 | `facility_id` | demo `realData`（depot/pharmacies）；坐标待 C M5 | 半占位（无坐标） |
| `ReshipmentOrder` | 补发单 | `order_id` | 触发侧=引擎 `reshipment_required`；**字段 9/21 契约** | **占位** |

## 2. 实体属性表

### `Product` — 产品与稳定性规格（来源：`rules_config.json`，A 定义）

| property | type | 说明 |
|---|---|---|
| `product_id` | string | PK。当前 4 值：`vaccine_2_8` / `frozen_m20` / `insulin_2_8` / `mrna_ultracold` |
| `storage_min_c` | float | 存储下限（当前为占位，A W1 校实） |
| `storage_max_c` | float | 存储上限 |
| `allowable_duration_min` | int | 允许超限时长 |
| `mkt_threshold_c` | float | MKT 阈值 |
| `retestable` | bool | 可否复检 |
| `freeze_sensitive` | bool | 是否冻敏（WHO TRS 961 Annex 9） |

> 数值改动的唯一入口是 `rules_config.json`；KG/前端/测试都不得另存一份阈值（同源原则，A 9/11 校实时同步导出）。

### `Regulation` — 合规文档（来源：引擎 `regulation` 字符串去重，A 提供）

| property | type | 说明 |
|---|---|---|
| `reg_id` | string | PK，文档级稳定 id，如 `WHO_TRS_961_ANNEX9`、`EU_GDP_2013_C343_01` |
| `title` | string | 与引擎 `regulation` 句同源的标题/原则句 |
| `issuer` | string | `WHO` / `EU` |
| `cite_level` | string | 固定 `document`（**禁止** clause 级杜撰） |

初始节点仅两篇；每条处置边上另存引擎**逐条**的 `regulation` 句（见 §3 `EVENT_LEADS_TO_DISPOSITION`），供审计原样回放。

### `SOP` — 操作标准（v1 占位）

| property | type | 说明 |
|---|---|---|
| `sop_id` | string | PK（草案：如 `SOP-<stage>-<context>`） |
| `context` | string | 覆盖环节（`transit` / `airport_dwell` / `warehouse` 等，词表与 `stage` 对齐） |
| `governing_reg` | string | 依据文档 `reg_id` |
| `status` | string | v1 = `PLACEHOLDER` |

> 表结构为 D 起草占位（引擎无 SOP 契约字段），9/16 只从 WHO/EU GDP **文档级**原则抽节点，请 A/C 评审词表。

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

### `Facility` — 设施节点（坐标待 C M5）

| property | type | 说明 |
|---|---|---|
| `facility_id` | string | PK（demo `realData`：`DEPOT` + `PHARMACIES[*].id`） |
| `role` | string | `depot` / `pharmacy` / `polyclinic`（词表随 C 设施表 9/23 核对） |
| `loc_lat` / `loc_lng` | float | v1 = 空，待 C OSMnx 新加坡坐标（9/23–24）入网 |

### `ReshipmentOrder` — 补发单（v1 仅锚，字段待定）

| property | type | 说明 |
|---|---|---|
| `order_id` | string | PK |
| 其余 | — | **待 A+C 契约 9/21 终版（D 评审）**——本 v1 不自行造字段；触发侧信息（`run_id` / `disposition` / 产品）暂由关系承担 |

## 3. 关系

核心四条（DAILY_PLAN 指定）+ 两条主链补强（标 ✚），本 schema 只定**方向与语义**；Cypher 方向与索引明日在 `schema.py` 落地。

| 关系 | 方向 | 基数 | 含义 | 例 |
|---|---|---|---|---|
| `PRODUCT_HAS_REQUIREMENT` | `(:Product)-[r]->(:Regulation\|SOP)` | Product 1—N 文档 | 产品的稳定/操作要求由哪篇文档施加 | `vaccine_2_8` → `WHO_TRS_961_ANNEX9`（冻敏原则） |
| `EVENT_CAUSED_BY` | `(:ExcursionEvent)-[]->(:Cause)` | Event N—1 Cause | 本次事件主因 | 冻结事件 → `frozen` |
| `EVENT_LEADS_TO_DISPOSITION` | `(:ExcursionEvent)-[d]->(:Disposition)` | Event N—1 Disposition | **决策链实例**：边属性存现场（见下） | `run_id=…` → `quarantine` |
| `DISPOSITION_CITED_BY` | `(:Disposition)<-[:CITES]-(:Regulation)` | 反向语义=处置被文档引用 | 某处置类别依据哪篇文档 | `quarantine` ← `WHO TRS 961 / EU GDP（hold for assessment）` |
| ✚ `EVENT_OCCURRED_AT` | `(:ExcursionEvent)-[]->(:Facility)` | Event N—1 Facility | 事件发生在哪个设施（stage 词 → facility.role） | `warehouse` 事件 → 对应 depot |
| ✚ `TRIGGERS_RESHIPMENT` | `(:ExcursionEvent)-[]->(:ReshipmentOrder)` | Event 0—1 Order | 判定需补发 → 生成补发单（M3→M5 锚点） | `scrap`/`quarantine` 事件 → 补发单 |

`EVENT_LEADS_TO_DISPOSITION` **边属性**（决策现场，审计可回放、可本地化渲染）：`rule_no`(int 1–6) · `reason`(引擎句) · `rule_path`(引擎整句) · `regulation`(引擎逐条句) · `reshipment_required`(bool) · `risk_score`(int) · `cause_code`(→`Cause`) · `decided_at`(datetime)。

## 4. 典型问答路径（W2 `/api/qa` 模板的骨架）

| 问题 | 路径 |
|---|---|
| 为何隔离/报废 | `(e:ExcursionEvent{run_id})-[d:EVENT_LEADS_TO_DISPOSITION]->(dis:Disposition)` → 返回 `dis.disposition + d.reason + d.rule_path` |
| 依据哪条法规 | 上一条后 `(dis)<-[:CITES]-(reg:Regulation)` 或走 `d.regulation` 句 → 返回 `reg` 节点 |
| 依据哪条 SOP | `(p:Product{product_id})-[PRODUCT_HAS_REQUIREMENT]->(sop:SOP{context: e.stage})` → 无节点则答「该环节 SOP 未录入」，**无证据不回答** |
| 该原因最常见场景 | `(c:Cause)<-[:EVENT_CAUSED_BY]-(e)` 聚合 `e.stage / e.product_id` 分布 |

## 5. 约束/索引计划（衔接 9/11 `schema.py`）

- 唯一约束：`Product.product_id` · `ExcursionEvent.run_id` · `Cause.cause_code` · `Disposition.disposition` · `Regulation.reg_id` · `Facility.facility_id` · `SOP.sop_id`。
- 索引：`ExcursionEvent.product_id` / `stage` / `created_at`（问答聚合与「按产品查历史」用）。

## 6. 未决项（W1 定稿前评审）

1. **Requirement 是否独立成实体**：v1 采纳「`Product` 属性承载 spec + `PRODUCT_HAS_REQUIREMENT` 边锚到施加文档」；若问答需要「某产品允许超限时长多少」这类单点查询，再考虑拆 `Requirement` 节点（9/20 前定）。
2. **条款级引用**：本 schema 禁存；A 阈值证据表 9/11 出来后同步补 `Regulation` 的证据属性。
3. **ReshipmentOrder 全字段**：9/21 A+C 终版后补属性表（D 评审）。
4. **Facility 坐标 & role↔stage 词表**：待 C 设施表（9/23–24）与词表对齐后填。
5. **SOP 属性表**为 D 起草占位，请 A/C 评审用词（避免与规则引擎/补发单字段撞名）。

---
变更记录：9/10 初稿 v1（D）· 基线：ARCHITECTURE M6 / 前后端契约 / A 引擎 `models.py` + `rules_config.json` + `service.py risk_score`。
