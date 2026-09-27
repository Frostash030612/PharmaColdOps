# Proposal 演讲前核查：提案 ↔ PPT ↔ 前端

核查对象与基准：

| 项目 | 文件 | 口径 |
|---|---|---|
| 提交件（已交 Canvas，冻结） | `proposal/PharmaColdOps-Proposal-Group 52.pdf`（源自 `PharmaColdOps-Proposal-EN.docx`） | 2026-09-13 提交的英文提案 |
| 提案源稿（提交后仍在修订） | `proposal/PharmaColdOps-Proposal-EN.md` / `-ZH.md` | §8.3 等数字已按 rubric v1.1 更新到 2026-09-14 |
| 课程要求 | `proposal/IRS practice module project proposal & final presentation guidelines v016.pdf`、`IRS practice module & exam briefing v2.17.pdf` | 演讲结构、评分项 |
| 演讲用 PPT | `proposal/PharmaColdOps_tune.pptx`（推荐版，带设计） / `PharmaColdOps-Proposal-Presentation.pptx`（旧版，12 页） | 两份都是 9/13 前写的，事实停在 W0 |
| 已修正版（本次生成） | `proposal/PharmaColdOps-Proposal-Presentation-Final.pptx`（17 页） | 由 tune 版生成，见下文「已做的修正」 |
| 前端 | `frontend-vue/`（Vue 3 + Vite + Pinia + Leaflet），后端 `src/api/main.py` | 2026-09-18 现状 |
| 演讲稿 | `proposal/演讲稿-4人版.md` | 四人分段，英文正文＋中文对照 |

**一句话结论**：提案本身是自洽且诚实的（它主动写清了自己的限制）；**PPT 与提案不对应的地方集中在 8 处，且全部是 PPT 单方面「说过头」**，一旦被追问就会与你自己提交的提案冲突——这是最需要优先修的。前端内容与提案**大方向对得上**，但有 **2 个必须先知道的演示陷阱**（§3.1，会直接影响你能不能把演示做出来）和 3 处待统一口径（§3.2）。

---

## 0. 最优先的三件事（演讲前必做）

1. **别用旧 PPT 直接讲**：`PharmaColdOps_tune.pptx` 第 1 页成员是 `[Member 2] [Member 3] [Member 4]`、日期写死「13 Sep 2026」（那是提案截止日，不是演讲日），第 12 页「下一步：9/13 前提交提案」也已经过期。→ 已生成修正版 17 页：`proposal/PharmaColdOps-Proposal-Presentation-Final.pptx`。
2. **删掉/改写 3 句会被当场打脸的绝对化表述**（§2 的 G1、G2、G6）：数据「real」、现有系统「不会推理」、MVP「multi-temperature zones」。这三句与提案原文直接冲突。
3. **补一页量化结果**：v016 指南第 10 页明确要「evaluation metrics and quantitative results / graphs」。旧 PPT 只列了「将用哪些指标」，一个数字都没有，而你们其实已经有 54/57、κ=0.6434、LightGBM ROC-AUC 0.925、新加坡 6.19% 距离下降——不展示等于白做。
4. **演示前先读 §3.1 的两个陷阱**：离线模式打开时决策沙盒（规则路径/证据/风险）是**点不出来**的；另外前端目前**没有**触发 `/api/route` 的入口。演示顺序必须按 §4 走。

---

## 1. PPT 内容是否满足课程要求（guidelines v016）

指南 14 页的结构要求 vs `PharmaColdOps_tune.pptx`（12 页）逐条对照：

| v016 要求 | 旧 PPT 现状 | 判定 | 修正版（17 页）怎么处理 |
|---|---|---|---|
| 1 标题页：课题、**组号**、成员**姓名＋学号**、演讲日期 | 第 1 页缺组号，成员是 `[Member 2..4]` | **不合格** | 已补齐 `Project Group 52`、四人姓名＋学号；日期改为演讲日（现填 22 Sep 2026，**按实际演讲日改**） |
| 2 Introduction（概述／重要性／目标） | 第 2–5 页覆盖问题、影响、方案 | 合格 | 不改结构，只改事实 |
| 3 Background / Market Context（背景、问题、研究或市场全景） | 有背景（2–4 页），**没有市场全景** | **缺失** | 新增第 13 页「Where PharmaColdOps Sits」 |
| 4 Literature Review / Market Research（文献或竞品与趋势） | **完全没有**；笔记里有 Solomon，正文没有 | **缺失** | 并入第 13 页（Solomon 1987、OR-Tools、XGBoost/LightGBM、SHAP + Controlant 定位） |
| 5 Project Scope（范围、聚焦的 IRS 技术、限制） | 第 7、11 页有技术组与 MVP 边界；**没有「不做/局限」清单** | 部分 | 第 11 页把「明确排除」写全（含真实处置授权与真实运输执行） |
| 6 Data Collection & Preparation（来源、获取与处理、挑战） | 第 9 页有来源，但**说成 "real data"，与提案「疑似合成/仿真」冲突** | 部分且**错误** | 第 9 页改为「来源可核实、性质如实披露」 |
| 7 System Design（架构图＋技术选型理由，提案阶段可选） | 第 6 页流水线示意图（无图注、无选型理由） | 基本合格 | 保留；口头补「为什么用规则引擎而不是端到端 ML」 |
| 8 Implementation（截图/演示、实现挑战） | **无截图、无进度** | **缺失** | 新增第 14 页「The Loop Is Already Closed」（含 proposal 里那张 API 模式截图） |
| 9 Results & Progress（量化结果、图表、与原计划的偏差） | 只有「将用什么指标」 | **缺失（最重要）** | 新增第 15 页「Preliminary Results」 |
| 10 Challenges & Roadblocks | 第 12 页只有「small data / rule complexity / scope creep」这类通用风险，**没有真实的** | 部分 | 新增第 16 页：κ 未达标、隔离召回 0/3、根因 Top-1 低于多数类基线、数据真实性、阈值出处 |
| 11 Future Work | 第 11 页周计划可代 | 合格 | 第 17 页补一句承诺清单 |
| 12 Conclusion | **无** | 缺失 | 新增第 17 页 |
| 13 Supplementary（AI 使用说明、致谢） | 无 | 建议补 | 提案 §15 已写 AI 使用声明，口头说明即可 |

另外两点硬性要求：

- **技术组 ≥ 3 个**（briefing v2.17 第 6 页）：你们覆盖 4 个，满足。PPT 第 7 页「This exceeds the minimum requirement of three」这句是对的，可以讲。
- **演示视频禁止 AI 生成讲稿 / 配音**（briefing v2.17 第 13 页评分项 5）。→ 本目录的演讲稿是**给你们的提纲**，最终视频与现场必须由本人用自己的话讲，不要照读机器合成的音频。

---

## 2. PPT 与提案的 8 处不对应（按危险程度排序）

全部是「PPT 说得比提案强」，评委一对照提交件就会发现：

| # | 位置 | PPT 原话 | 提案的相反口径 | 风险 | 已改成 |
|---|---|---|---|---|---|
| G1 | tune 第 9 页标题＋正文 | 「Data Sources: Public, Downloadable **Real** Data」+「We use **real**, publicly available datasets, **not fabricated data**」（旧版笔记里还有这句） | ZH §7.1 / EN §8.2：silent-failure「真实性未确认、**疑似合成**」；Electric Sheep 是「**仿真**」；疫苗分布「**疑似合成**，含实际地名」 | **最高**。这是评委最爱抓的一条，而你们自己的提案已经写实了 | 标题改「Verifiable, Disclosed Provenance」，讲「来源可核实、性质如实披露」 |
| G2 | tune 第 4 页 | 「Spreadsheets and simple alarms log the deviation — but cannot answer 'stop this batch?'」＋「**黑盒 AI 不可信**」的竞品式否定 | §3.3：商业产品**已**覆盖监控、可视化与部分质量流程自动化（Controlant 的 Product Stability Automation 会依据稳定性档案定放行状态），「不能把现有厂商概括为『只告警、没有处置能力』」 | 高：与提案的「unverified capabilities remain unknown」直接矛盾 | 第 4 页改为「Fragmented, Not Absent」：承认现有能力，缺口是**可检查的规则路径＋案件级连接** |
| G3 | tune 第 8 页「Optimisation」 | 「VRPTW solver handles time windows, **multi-temperature zones, and stockout priority** simultaneously」 | §6.4 / §9：替代库存选择、多温区、碳排放列为**扩展（未实现）** | 高：把 extensions 讲成已交付 | 改为「multi-temperature zones and stockout priority are listed as extensions, not delivered」 |
| G4 | tune 第 7 页「Cognitive Systems」/ 第 8 页 | 「knowledge graph with **natural-language** compliance Q&A」 | §6.5：`/api/qa` 是「受限意图识别 + 参数化 Cypher」的**结构化问句类型路由，不是自然语言分类**；LLM 非 MVP 必需 | 中高：问一句「你们用了什么 NLP 模型？」就答不上来 | 第 7 页写明「参数化 Cypher + 受限问句路由，不是自由文本聊天机器人」 |
| G5 | tune 第 6 页流程 | 「Root-Cause Diagnosis → link anomaly to equipment / events」画在主流水线上 | §6.1/§6.3：ML 分数**不进入决策 API**，候选原因是**离线实验** | 中：会被问「根因诊断怎么接进在线流程」 | 第 6 页该格改为「Candidate-cause classification（offline experiment；ML scores never enter the API）」 |
| G6 | tune 第 5、6、7 页 | 「Release / quarantine / retest / scrap / **reshipment**」并列摆成五类 | §1/§6.2：补发是**独立物流动作，不是第五个互斥处置类别** | 中：概念错误，评委很可能直接问 | 第 5 页明写「reshipment is a separate logistics action, not a fifth disposition」 |
| G7 | 旧版第 10 页笔记 | 「compared against greedy and **CP-SAT** baselines」 | §6.4：实现是 `RoutingModel` + `PATH_CHEAPEST_ARC` + `GUIDED_LOCAL_SEARCH`，**明确 not CP-SAT** | 中：口误级但显眼 | 笔记已不随新稿；口头务必说 Routing Solver / GLS，不要说 CP-SAT |
| G8 | tune 第 11 页 | 「**1–2 product classes**」 | §6.2 / §9：**4 个**原型类别配置（vaccine_2_8、frozen_m20、insulin_2_8、mrna_ultracold）是必交项 | 中：低估自己的交付，且与必交清单不符 | 改为「4 prototype product classes」 |

另有 2 处过期信息（非冲突但不专业）：第 1 页日期写成提案截止日；第 12 页「Next steps: Submit proposal by 13 September 2026」（提案已于 9/13 提交）。

**源稿比提交件新**：`README.md` 已登记 11 组差异，其中对演讲影响最大的是 §8.3——**提交件写「39/57, 68.4%」，源稿与当前引擎是「54/57, 94.7%（rubric v1.1, 2026-09-14）」**。演讲时请**明确说出**：提交后 rubric 第 4 条由 `quarantine/scrap` 未决改为 `scrap`，引擎与冻结测试同批更新，因此现在的数字是 54/57。否则评委按提交件问「为什么 PPT 写 94.7%」，你会很难解释。

---

## 3. 前端 ↔ 提案 ↔ PPT 的对应关系

前端本体已由 `docs/前端与提案一致性核查.md`（同一轮生成）逐条取证，下面两条最关键的结论由我独立复核过（含直接调用真实 API）。

### 3.1 两个演示陷阱（**演讲前必读**）

**T1 · 前端没有调用 `/api/route` 的入口 —— 端点是真的，界面没接。**

- 后端实测（本机 uvicorn + `data/audit/runs.jsonl` 里 18 个已结案案例）：`POST /api/route {run_id:"R20260918-022350-635"}` 返回 `order_id=RO-R20260918-022350-635`、`total_distance≈28.82 km`、1 车、`on_time_rate=1.0`、0 违规、0 未服务，并带 GeoJSON。**后端完全正常，且严格要求已结案案例**（`src/api/service.py:413` "Find a closed case, derive its order, solve…"）。
- 但前端 `stores/decisions.js:136` 的 `fetchRoute()` **在 `frontend-vue/src` 全仓零调用**，`routeResults` 也没有任何模板渲染它；`decisions.js:147` 还把错误吞掉了（`.catch(() => {})`）。
- 结论：提案 §1/§6.5 那句「客户端求解并展示**已结案案例**的补发路线」是**后端为真、界面未接线**。**演示时不要去找那条路线**——现场能看到路线，是因为走了 `/api/dispatch/*`（先 `previewDailyPlan`/`previewBranch` 再把案例提交进作业），那条链路是真的、可演示。
- 建议（P1，非演讲必需）：要么在 `CaseDrawer`/`ShowCase` 里接上 `fetchRoute(run_id)` 并把 `routeResults` 渲染到地图，要么把这段死代码删掉，避免评委翻代码时发现「有函数没入口」。

**T2 · 离线模式点不出决策沙盒 —— 必须起后端，且仓库里要有已结案案例。**

- `CaseDrawer`（装着规则路径、证据、风险指数、时间线等 10 个组件）只在 `overlay.caseOpen` 时渲染，而 `openCase()` 只有两个触发点：`IncidentList.vue:38` 与 `ReroutePanel.vue:57`。二者都依赖 `history.runs`（已结案归档）或 incidentEvents。
- 离线模式 `history.load()` 直接把 `runs` 置空（`history.js:51–58`），事件列表只显示「离线无归档」提示，按钮也只在 `useApi` 时出现（`IncidentList.vue:48,52`）。
- 结论：**直接开 `http://localhost:5173`（不带 `?api=`）只能看到地图与调度面板，看不到规则/证据/风险**。演示必须：① 起后端；② 用 `?api=http://127.0.0.1:8000`；③ 仓库里 `data/audit/runs.jsonl` 已有 18 条归档（本机实测），点最上面那条结案案例即可打开沙盒。若换到干净机器，需要先跑一次结案表单产生一条归档。
- 其他两个操作顺序细节：`confirmDailyPlan()` 会**自动发车**（`dispatch.js:370`），所以找不到独立「发车」按钮时不要慌；「逐单送达」没有手动按钮，是模拟时钟驱动的（`deliverNext` 同样是死代码）。

### 3.2 提案声明逐条判定

**对得上的（可以现场演示）**

| 提案声明 | 代码证据（已复核） | 判定 |
|---|---|---|
| 「Vue 是唯一前端，旧 vanilla 静态页 9/12 退役」 | 仓库内已无 `frontend/`，只有 `frontend-vue/` | 一致 |
| 「双语界面」 | `i18n/index.js:24–45`（`?lang=` ＞ localStorage ＞ 浏览器语言）、`HeaderBar.vue:52–55` EN/中文 切换，`<html lang>` 同步 | 一致 |
| 「离线/API 双模式」 | 模式只由 URL 参数 `?api=` 决定（`decisions.js:181–185`）；离线走 `lib/engine.js`、`lib/zone.js`、`lib/qa.js` 关键词兜底 | 一致 |
| 「在线模式连接**已结案案例**并求解补发单」 | 后端 `service.py:413`＋实测（见 T1） | **后端为真、界面未接线**（T1） |
| 「查询该案例的图谱证据，四态状态」 | `POST /api/qa`（`main.py:339`）；四态 `ok`/`no_case`/`insufficient_evidence`/`unsupported`（`schemas.py:294`、`qa.py:45`）；`QAPanel.vue:51–64` 四态都渲染本地化提示；无库时 503（本次实测确认） | 一致（DB 故障不是第五态，前端静默回落关键词回答） |
| 「把结案案例提交进实时配送作业（预留库存、分配车辆）」 | `dispatch.js:63–78` → `POST /api/dispatch/reshipments`（注释明写 "reserves stock and assigns a vehicle, unlike the stateless /api/route"） | 一致 |
| 「排线/发车/模拟时钟/紧急插单」 | `/api/dispatch/plan`、`/runs`、`/depart`、`/tick`、`/speed`、`/reshipments/preview`、`/reshipments`（OpenAPI 实测共 25 个端点） | 一致（另有 4 个后端端点前端未调用，见 §3.3） |
| 「Leaflet 地图」 | `LeafletMap.vue`（473 行）、`TransportView.vue` | 一致 |
| 「界面风险指数与 cause_code 是确定性启发式，不是 ML」 | `lib/risk.js`；`api.js:90–91`；`en.js` 的 `center.riskNote` 写明「rule-derived · deterministic, not an ML model」 | 一致 |
| 「结案历史为 JSONL」 | `main.py:57–65` 读 `data/audit/runs.jsonl`；`history.js` | 一致 |

**需要统一口径的 3 处**

1. **「选择目的地与数量的界面待建」**（§5.1 第 5 项 / §5.2 M5）：**目的地下拉其实已经有了**（`ExcursionInputs.vue:69–76`，选项来自 `sandbox.js` 的 10 家医院），而且确实随 `eventPayload` 传给后端（`api.js:25` `destination_facility_id`）。真正缺的是**数量**（固定 30 单位，`daily_orders.py:43`）与**完整候选目的地池**。演讲时按提案说「候选目的地池与替代库存选择待建」，**不要**说目的地也不能选——会被现场要求演示。
2. **「结案表单尚未传异常地点 facility_id」**：`NewInboundModal.vue` 里**完全没有**异常地点字段，只传补发目的地——与提案完全一致，是很好的「已知限制」素材。
3. **重复结案去重**：提案写「尚无去重」，代码同样没有。同上，主动披露。

### 3.3 前端与 PPT 的对应

旧 PPT 一个字都没提前端，v016 却要求「Implementation：screenshots or demos」。修正版第 14 页已放入 `proposal/figures/demo-route-qa-en.png`（2026-09-12 API 模式实拍），并注明该截图早于「提交进实时作业」能力——与提案 §6.5 的图注口径一致。

**⚠️ 该截图与当前前端样式已不一致**（2026-09-27 用户确认）。原因：截图摄于 9/13 14:38，此后 `frontend-vue/src` 有 19 个样式/组件文件变更，其中直接影响版式的有 `35ef820 feat(dispatch): map-first incidents and fleet constraints`（改为地图优先工作台）、`046a36f 运输视图——进度分段、大图、支线标记、改道前后对比`、`947cd81 配送面板新增「调度约束」输入`。**配色没变**（`styles.css` 仍是 `--navy #0f2a4a` / `--teal #0d9488` / `--bg #f4f7fb`，与截图主色一致），变的是布局。

**换图流程（已备好，两步）**：

```powershell
# 1) 截好图后放到任意位置，跑这个脚本：自动去边框并写成 demo-ui.png
.venv/Scripts/python.exe scripts/prepare_ui_shot.py "C:\path\to\your-shot.png"
# 2) 重建 PPT —— 脚本优先使用 demo-ui.png，找不到才回退旧截图
.venv/Scripts/python.exe scripts/build_presentation_final.py
```

图注里的日期由 `demo-ui.png` 的文件修改时间自动生成，所以截图当天生成即可。建议截图视角：`?api=` 模式、窗口 1600×1000、让**左侧地图（含车辆与路线）＋右侧调度面板与事件列表**同时入镜；幻灯片给图预留 7.4in × 约 5.1in，横构图比竖构图清楚得多。

另外，前端实现了**提案里没写**的 10 项能力（收工停靠选址、可编辑硬约束、PDPTW 取送、运行回放、按种子重掷、排序口径切换、可见性自动暂停、前端审计表、18 个预置场景等）——这些属于「value added」，Q&A 时主动说比被问出来更有分。未从前端调用的 4 个后端端点：`GET /api/dispatch/runs/{id}`、`/deliver-next`、`/emergency-preview`、`/emergency-accept`。

---

## 4. 演示前的可执行清单

```powershell
# 1) 后端 API（Neo4j 需要 docker compose 起，否则 /api/qa 返回 503）
docker compose up -d
.venv/Scripts/python.exe -m uvicorn --app-dir src api.main:app --port 8000

# 2) 前端（Vue 3 + Vite，需 Node LTS；用 pnpm）
cd frontend-vue
corepack enable pnpm      # 一次性
pnpm install
pnpm dev                  # 离线模式：http://localhost:5173
# 在线模式：http://localhost:5173/?api=http://127.0.0.1:8000
```

演示脚本建议（3 分钟，**按 T1/T2 的顺序来**）：起后端 → 打开 `?api=` 页面 → 右侧事件列表点最上面那条**已结案案例**（沙盒抽屉打开，看规则路径与四类处置）→ 提一个「为什么这样处置」的问题看图谱证据（四态提示）→ 生成今日批次并确认（会自动发车）→ 预览把本案例挂进在跑车辆的分支候选 → 提交进实时作业（预留库存＋分配车辆）→ 地图上看车辆按模拟时钟推进。**注意：不要去找「点一下就把该案例路线算出来」的按钮**——那是后端 `/api/route` 具备、但前端尚未接线的能力（T1）。

**演讲当天务必先自测的 5 件事**：① `?api=` 模式下右上角 API 状态灯是绿的；② 后端在 8000 端口、`data/audit/runs.jsonl` 里有至少一条归档案例（否则沙盒点不开）；③ Neo4j 容器在跑（`docker compose up -d`，否则问答 503）；④ 现场网络不可靠时**先用不带 `?api=` 的静态 `dist/` 兜底**（地图与调度面板仍可看），在线环节再切；⑤ 修正版 PPT 里的日期已改成实际演讲日。

> 备注：本次核查是在 DSH 沙箱里跑的，`vite dev` 因沙箱禁止子进程 spawn 而无法启动（`spawn EPERM`，属环境限制，非项目缺陷）；后端 API 已实际启动并验证通过。你们本机用 `pnpm dev` 正常。

---

## 5. 生成物与可复跑命令

| 文件 | 说明 |
|---|---|
| `proposal/PharmaColdOps-Proposal-Presentation-Final.pptx` | 17 页修正版（修 8 处事实冲突 + 补 5 页指南要求的内容） |
| `scripts/build_presentation_final.py` | 生成上面这份 PPT 的脚本，可重跑；改日期/文案只需改常量。每次重建都会跑一遍「与原文字数预算」检查 |
| `scripts/check_ppt_text_budget.py` | 逐框对比「原设计字数 vs 现在字数」——排版溢出/压叠的硬判据（见 §6） |
| `scripts/check-frontend-sfc.mjs`、`scripts/check-frontend-i18n.mjs` | 前端 Vue 模板编译校验、中英 i18n key 覆盖校验 |
| `scripts/prepare_ui_shot.py` | 把新截图去边框并写成 `proposal/figures/demo-ui.png`，PPT 优先取用它 |
| `scripts/export-slides.ps1`（可双击 `export-slides.cmd`） | 用 PowerPoint COM 把每页导出成 PNG，用于肉眼核对排版 |
| `scripts/dump_pptx_text.py`、`scripts/extract_pdf_text.py` | 零依赖的 PPTX 文本导出 / PDF 文本抽取小工具 |
| `proposal/演讲稿-4人版.md` | 四人分段演讲稿（英文正文 + 中文对照 + Q&A 应答卡） |
| `docs/前端与提案一致性核查.md` | 前端逐条取证报告 |

复跑：

```powershell
.venv/Scripts/python.exe scripts/build_presentation_final.py     # 生成 PPT + 版式预算检查
node scripts/check-frontend-sfc.mjs                              # 前端模板编译校验
node scripts/check-frontend-i18n.mjs                             # 中英 key 覆盖校验
.venv/Scripts/python.exe scripts/dump_pptx_text.py "proposal/PharmaColdOps-Proposal-Presentation-Final.pptx" out.txt
```

> 注：修正版 PPT 只在**文字层**做了改正与新增（沿用 tune 版母版与配色，新页为纯文本页，未加图标）。若要更精致，可在 PowerPoint 里给第 13–17 页套用与前面一致的图标/配色。
