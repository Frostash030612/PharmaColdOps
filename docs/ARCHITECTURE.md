# PharmaColdOps 模块划分与实现路线

> 综合团队讨论结论，供 4 人并行开发时对齐接口与分工。配套文档：`proposal/PharmaColdOps-Proposal-ZH.md`（提案）、`proposal/处置决策-ground-truth评估方案.md`（§8.3 金标准设计）。
>
> 更新：2026-09-09

---

## 1. 模块划分（7 个）

按"技术职责 + 负责人 + 数据流"划分，比提案 §10 的四角色分法更细一档：

| # | 模块 | 负责人 | 干什么（输入 → 输出） | 评估 / 基准 |
|---|---|---|---|---|
| M1 | 数据接入与预处理 | B | 原始 CSV/parquet → 统一特征表 + 数据字典（偏移时长、MKT、开门次数、运输阶段） | 质量检查 |
| M2 | 偏移检测与事件生成 | B | 温度序列 → 偏移事件 `ExcursionEvent` + MKT 计算 | 派生标签交叉验证（注意 §8.3 反循环） |
| M3 | 处置规则引擎（**枢纽**） | A | `ExcursionEvent` → 放行/隔离/复检/报废 + 补发标志 + 法规依据（可审计决策链） | 场景库 + 双人独立标注（§8.3） |
| M4 | 风险预测 + 根因诊断 | B | 特征表 → 风险分 + 根因类别 + SHAP 解释 | `silent_failure`、`potency_compromised`、`excursion_cause`（11 类） |
| M5 | 配送改派优化（VRPTW） | C | 补发订单 → 改派路线（贪心 → Routing Solver (GLS) → GA），新加坡路网 | Solomon / CVRPLIB 已发表最优解 |
| M6 | 知识图谱 + 合规问答 | D | 决策链 + 根因 + 法规 → "为何隔离/依据哪条 SOP" + 审计报告 | 问答准确率、证据可追溯覆盖率 |
| M7 | 集成与展示 | D | 各模块输出 → FastAPI + 前端（异常列表 → 处置 → 路线 → 问答） | 端到端演示 |

**对 IRS 四大技术组的映射**：

- 决策自动化 = M3
- 知识发现 / 数据挖掘 = M2 + M4
- 资源优化 = M5
- 认知系统 = M6
- M1 / M7 为工程支撑层（数据层 + 展示层，提案 §6.6），不占技术组

**模块之间的 4 条内在逻辑**：

1. **主链（事件驱动）**：M1 → M2（发现偏移）→ M3（处置决策）→ M5（需要补发就改派）+ M6（生成解释）→ M7（展示）。一条"一次温度异常走完全程"的闭环。
2. **旁路（知识发现佐证）**：M1 的特征表并行喂给 M4，M4 的风险分只进报告做交叉验证（**不进决策 API**，与 PROGRESS「ML 不进 API」决策一致），根因**喂给** M6 做"为什么出事"的解释。
3. **评估线（横切支撑）**：每个有预测/决策的模块都挂一个独立的、非循环的基准（提案 §8.3 核心设计）。
4. **反馈环**：实际处置结果回写 M6 知识库（历史案例）与 M4 风险模型（持续改进，提案 §5 第 7 步）。

---

## 2. 模块关系示意图

```
                          法规与领域知识源 (WHO TRS 961 · EU GDP · ICH)
                              │  阈值 + 条款节点
                              ▼
  原始数据集(data/ml, solomon)        ┌──────────────────────┐
  ───────────────────────►           │  M1 数据接入与预处理 (B) │
                                     └──────────┬───────────┘
                                                │ 特征表
                          ┌─────────────────────┴────────────────────┐
                          ▼                                          ▼
        ┌────────────────────────────┐          ┌──────────────────────────────┐
        │ M2 偏移检测与事件生成 (B)     │          │ M4 风险预测 + 根因诊断 (B)      │
        │ 温度序列 → ExcursionEvent   │          │ LightGBM/XGBoost + SHAP       │
        │        + MKT 计算          │          │ 根因分类 (excursion_cause)      │
        └────────────┬───────────────┘          └──────────────┬───────────────┘
                     │ ExcursionEvent                          │ 风险分 / 根因 / SHAP
                     ▼                                         ▼
        ┌──────────────────────────────────────────────────────────────────┐
        │              M3 处置规则引擎 (A) ── 全系统枢纽                     │
        │   Event → release / quarantine / retest / scrap                  │
        │           + reshipment_required + 法规依据 (可审计决策链)          │
        └─────────────┬──────────────────────────────┬─────────────────────┘
                      │ 补发订单 (ReshipmentOrder)    │ disposition + 决策链
                      ▼                              ▼
        ┌────────────────────────────┐   ┌──────────────────────────────┐
        │ M5 配送改派优化 (C)          │   │ M6 知识图谱 + 合规问答 (D)      │
        │ VRPTW: 贪心→Routing(GLS)→GA │   │ 产品/设施/事件/法规/SOP 节点    │
        │ 新加坡路网 (OSMnx)          │   │ "为何隔离 / 依据哪条 SOP"       │
        │ Solomon 基准                │   │ + 审计报告                    │
        └─────────────┬──────────────┘   └───────────────┬──────────────┘
                      │ 路线方案                          │ 解释 / 报告
                      ▼                                  ▼
        ┌──────────────────────────────────────────────────────────────────┐
        │              M7 集成与展示 (D · FastAPI + 前端)                    │
        │         异常列表 → 处置建议 → 路线可视化 → 问答框                  │
        └──────────────────────────────────────────────────────────────────┘
        ▲                                                                    │
        └──────────── 实际处置结果回写 (§5.7 持续改进闭环) ──► M6 知识库 / M4 风险模型
```

**横切的评估支撑线**（箭头指向被评估的模块）：

```
  ┌─────────────────────────────────────────────────────┐
  │ 场景库 + 双人独立标注 (§8.3)      ──► 评估 M3         │
  │ silent_failure / potency_compromised ──► 评估 M4     │
  │ excursion_cause (11 类)          ──► 评估 M4 根因     │
  │ Solomon / CVRPLIB                ──► 评估 M5         │
  │ 问答准确率 / 证据覆盖率            ──► 评估 M6         │
  └─────────────────────────────────────────────────────┘
```

**读图要点**：M3 是唯一的枢纽——它左边被 M2（事件）和 M4（风险佐证）供着，右边同时触发 M5（物流动作）和 M6（合规解释），最后由 M7 收口；M4 是唯一"双向旁路"——产出既向上佐证决策、又向下支撑解释；反馈环保证系统不是一次性的，而是越用越准。

---

## 3. data 文件夹 → 模块映射

### 3.1 逐个文件的映射

| 文件 | 规模 / 关键字段 | 对应模块 | 说明 |
|---|---|---|---|
| `data/ml/cold-chain-silent-failure/shipment-sensor-dataset.csv` | ~8,000 行 × 24 列，**有标签** `silent_failure`（正例 19.7%）；特征含 `door_opens`、`temp_*`、`sensor_gap_hours`、`temp_recovery_rate` | **M4 风险预测**（主基准） | 全项目唯一"发运级、有真实标签"的 ML 数据集。**只有二值失败标签，没有根因标签** |
| `data/ml/vaccine-distribution-temperature/input_data.csv` | ~26,674 行；30 个 batch 的逐 hop 记录：`thermal_shipper_temp_reading`、`out_of_bound_temperature_hours`、`current_hop` 等 | **M2 异常检测 / MKT 模拟** + M3 场景素材 | 无显式异常标签；`current_hop` 含 34 条 `dest_discarded_vaccine_storage_unit`（被丢弃批），可当案例素材 |
| `data/ml/electricsheepafrica__vaccine-cold-chain/` 三个 CSV | 各 10,000 行 × 50 列；**有标签**：`excursion_cause`（11 类）、`freeze/heat_excursion_detected`、`wastage_cause_primary`（7 类） | **M4 根因诊断**（天然多分类标签）+ **M6 知识图谱**（核心数据源）+ M4 风险辅助 | 最富的一个数据集。设施/设备/疫苗/异常/原因/报废实体全齐，正好是 KG 的节点 |
| `data/ml/electricsheepafrica__africa-synth-immunization-vaccine-quality-cold-chain-all/` 三个 CSV | 各 10,000 行 × 27 列；**有标签**：`potency_compromised`（12.4% 正例）、`wasted`、`wastage_reason`（7 类） | **M4 风险预测**（第二基准）+ 数据增强 + M3 场景素材 | `potency_compromised` 是"冷链质量风险"的直接标签 |
| `data/ml/electricsheepafrica__africa-cold-chain-iot/train-...parquet` | 10,000 行；**冷链物联网网络安全**数据集（`attack_type`、`temp_data_tampered`、`route_diverted`、`vaccines_spoiled`） | 边缘用途：M4 根因诊断的"传感器篡改/漂移"类 + M6 安全案例节点 | **与核心闭环关系最弱**，报告里当补充数据即可 |
| `data/ml/ClarusC64__clinical-quad-coldchain.../train.csv`、`tester.csv` | **只有 ~10 行**（它本身就这么小） | 仅 schema 参考 | 不可训练、不可 benchmark |
| `data/optimisation/solomon/` 6 个 JSON | c101/c201/r101/r201/rc101/rc201 | **M5 算法基准** | Solomon 是 VRPTW 经典基准，公开发表最优解可直接对比 |
| `data/scenarios/scenarios.csv` | 自建场景库 | **M3 金标准** | 提案 §8.3 设计的一部分 |

### 3.2 数据是否足够（分模块结论）

| 模块 | benchmark 现状 | 结论 |
|---|---|---|
| M4 风险预测 | ✅ 两个带标签数据集：`silent_failure`（8k，19.7% 正例）+ `potency_compromised`（30k，12.4% 正例） | **够用**。8k 偏小但有 30k 兜底 + CV/类权重；F1/AUC/PR-AUC 都能算 |
| M4 根因诊断 | ✅ `excursion_cause` 有 **11 个自然类别**，3×10k 行 | **够用**，但 `not_applicable` 占 43%，训练前要过滤；Top-1/Top-3 准确率作 benchmark |
| M2 偏移/异常检测 | ⚠️ `freeze/heat_excursion_detected` 有标签但是**月汇总记录**，不是时间序列；26.7k 温度序列无标签 | **部分够**。序列级标签需按 §7.3 用阈值/MKT 派生 + 合成时间序列（注意 §8.3 反循环：别用要评估的规则去派生标签再评估同一条规则） |
| M3 规则引擎 | ❌ 公开数据没有"放行/隔离/复检/报废"标签 | **按设计走 §8.3**：自建场景库 + 双人独立标注 + 仲裁。人工标注是最慢的一环，**必须尽早启动** |
| M5 优化 | ✅ Solomon 6 实例 + CVRPLIB 全库可下 | **够用**，有已发表最优解做对比 |
| M6 知识图谱 | 不需要数值 benchmark | **数据源充足**：ES 数据集给实体，法规文档 + 规则表给规则类节点；评估靠问答准确率与证据覆盖率 |

**三个真正的缺口（需尽早决策，否则 W2 会卡）**：

1. **silent_failure 没有根因标签**——根因分类不能用它。两条路（建议都做）：
   - 用 ES 的 `excursion_cause` 做根因分类 benchmark（设施月度记录、特征空间不同）；
   - 在 silent_failure 上用 SHAP 特征归因输出"失败驱动因素"作为根因的解释性结果。
2. **温度序列没有序列级异常标签**——用阈值/MKT 从 26.7k 温度读数派生偏移片段（派生特征，不是"用引擎规则评估引擎"），配合 §7.3 的合成传感器时间序列。
3. **处置决策天然无公开标签**——§8.3 场景库 + 双人标注是唯一可行路径；两名组员只读书面 rubric 独立标注，这一步现在就可以开始。

---

## 4. 运输规划的新加坡本地化（M5）

> 实现与复现说明（2026-09-10）：见 [新加坡网络假设与运行说明](singapore_network_assumptions.md)。已支持有向距离/时间矩阵；下方早期示例的 `travel_time` 需先生成，矩阵不要求对称，当前求解器名称为 OR-Tools Routing Solver。

### 4.1 现状判断：哪些要本地化，哪些不用

| 模块 | 现有数据 | 跟新加坡有关系吗 | 要不要换 |
|---|---|---|---|
| M4 风险预测 / 根因诊断 | 合成/非洲数据，无地理含义 | 无关——温度偏移的物理规律（超限时长、开门、MKT）是**通用**的 | ❌ 不用换 |
| M2 异常检测 | 印度逐 hop 温度 | 无关 | ❌ 不用换 |
| M3 规则引擎 | 场景库 | 无关（产品稳定性阈值是药品属性，不是地点属性） | ❌ 不用换 |
| **M5 优化 VRPTW** | Solomon 6 实例 | **抽象欧氏坐标，不是新加坡街道** | ✅ **要动** |
| **M6 / M7 演示层** | 无地理实体 | 需要真实的新加坡设施节点（仓库/诊所/医院） | ✅ **要加** |

**结论**：ML 三件套 + 规则引擎是"地点无关"的，现有数据正确、不用动；真正需要"新加坡化"的只有 **M5 的路网** 和 **M6/M7 的设施实体**。这正是提案 §7.3 已写好的路线——"基于公开路网数据生成配送网络"。

### 4.2 路网方案选型：不推荐 Google Maps API

| 方案 | 费用 | 需要密钥/账单 | 限额 | 适合度 |
|---|---|---|---|---|
| Google Maps Directions/Distance Matrix API | 付费（无真正免费层，需绑定信用卡） | 要 | 按量计费 | ⚠️ 学生项目成本不划算，且要开通 billing |
| **OSMnx（推荐）** | 免费 | 不要 | 本地不限量 | ✅✅ Python 直接建新加坡路网 + 真实道路距离/时间 |
| OSRM / OpenRouteService | 免费层 | ORS 要免费 key | ORS 2000 次/天 | ✅ 提案已引用；20–50 节点全对全矩阵够用 |
| Valhalla | 免费 | 不要 | 自建 | ✅ 备选 |

**核心建议**：用 **OSMnx**（OpenStreetMap）。优势：无 key、无账单、本地跑，N 节点全对全距离矩阵不花钱；给出**真实道路**的行驶距离和时间（不是 Solomon 的欧氏直线距离）；新加坡 OSM 数据质量非常高。

```python
import osmnx as ox
G = ox.graph_from_place("Singapore", network_type="drive")   # 全岛驾车路网
route = ox.shortest_path(G, orig_node, dest_node, weight="travel_time")  # 真实驾驶路径与时间
```

### 4.3 落地步骤（只动两层）

**保留**：所有 ML 数据集 + Solomon 实例（Solomon 继续当**算法正确性基准**，证明 Routing Solver（GLS）/GA 求解器算得对，跟已发表最优解对比）。

**新增（新加坡配送网络层）**：

1. **节点清单**（用真实地址坐标）：
   - 冷库/仓库 depot：裕廊 / 大士（Tuas）冷链仓、樟宜冷链物流区；
   - 配送点：SingHealth / NUHS 各 polyclinic、SGH / NUH / KKH / TTSH / CGH 等医院、Guardian / Unity 药房。
2. **距离/时间矩阵**：用 OSMnx 对 20–50 个节点算真实驾驶距离 + 时间，替换 Solomon 的欧氏坐标，喂给 OR-Tools Routing Solver（GLS）/ GA。
3. **知识图谱**：把真实设施作为 KG 的 `Warehouse` / `Site` 节点，接上现有的产品、异常、法规节点。
4. **报告如实说明**：运营级传感器/风险数据是合成或非洲/印度来源（地点无关），**新加坡属性只注入在路网与演示层**。这个说法站得住，因为温度偏移物理规律通用。

---

## 5. 落地顺序建议（与提案 §10 对照）

| 阶段 | 内容 | 对应提案 |
|---|---|---|
| 立即 | 删除 `data/ml/` 两个重复目录；启动场景库双人独立标注（§8.3 第 2–3 步） | W1 |
| W1 | M1 预处理 + 数据字典（B）；M5 贪心基线 + Solomon 加载（C）；M6 KG schema v1 + M7 API 骨架（D）；M3 真实阈值（A） | W1 |
| W2 | M4 LightGBM/XGBoost 基线 + SHAP（B）；M5 接补发订单 + Routing Solver（GLS）v1（C）；M5 新加坡 OSMnx 路网矩阵（C）；M6 数据加载（D） | W2 |
| W3 | 端到端集成 v1：一次温度异常 → 处置建议 + 改派路线 | W3 |
| W4–W6 | GA 对比、多温区约束、KG 问答 v1、UI、视频、报告 | W4–W6 |

---

## 6. M6 知识图谱 SOP 节点来源决策（2026-09-11，供审查）

**问题**：`SOP`（标准操作规程）节点最初为 D 起草占位、无出处，却出现在每条决策审计链的证据里（`Decision -[:FOLLOWS]-> SOP`），等于审计报告引用"不存在的文件"。

**两条路（2026-09-11 评估）**：

- **A（已采用）：用公共程序性指引重建 SOP 节点（文档级）**。真实企业**内部** SOP 属专有文件、公开不可得；但公共程序性指引真实存在且可逐字引用：
  - `SOP-GDP-001` 温度偏移响应 ← [CDC Temperature Excursion Checklist](https://stacks.cdc.gov/view/cdc/142711/cdc_142711_DS1.pdf)（May 2014）+ EU GDP 9.2；
  - `SOP-GDP-002` 冻结处置（shake test）← [WHO shake test 验证文献](https://pmc.ncbi.nlm.nih.gov/articles/PMC2908964/)（475 瓶 × 8 类疫苗）+ WHO TRS 961 Annex 9 §6.9；
  - `SOP-GDP-003` 偏差记录与 CAPA ← EU GDP 1.2（官方 PDF 已核对）+ CDC 清单记录项。
  - 规范与 `Regulation` 节点一致：每个节点带 `source_url` + `verified`，步骤只到文档级、不杜撰。
- **B（备选，未采用）：删 SOP 节点类型**，功能并入 `Regulation`，删除 `FOLLOWS` 边；QA 对「依据哪条 SOP」按 schema「无证据不回答」答「该环节 SOP 未录入」。零编造风险，代价是审计链少一层操作细节。

**结论**：采用 A。若日后审查认为 SOP 层价值不足或出处维护成本过高，可按 B 回退——回退只动 `build_graph.py` 的 `SOPS` / `SOP_IMPLEMENTS` / `RULE_TO_SOPS` 与 schema 的 SOP 节，不影响主链。
