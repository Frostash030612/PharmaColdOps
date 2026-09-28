# Proposal 版本说明

本目录当前内容基准为 **2026-09-13 修订的中英文 Markdown、英文 SVG 配图和中文 Word 提案**。**英文提案已于 2026-09-13 提交**（提交件为下方 PDF）。提交后 Markdown 源稿又做了一轮修正，因此**源稿与提交件不再逐句相等**——差异逐条登记在文末「提交件与源稿的差异」。合并远程 9/13 一批后，两文的 §1 / §5.1 / §5.2 / §6.4 / §6.5 实现状态已按实测重新对齐（含 QA 四态、图 4b、单一 Vue 前端与调度台接线）。

| 文件 | 状态 |
|---|---|
| [中文提案](PharmaColdOps-Proposal-ZH.md) | 已更新项目范围、实现状态、数据、实验、标注结果及计划；9/13 更新 §1 与 §6.5 的 KG/问答与事件触发路线集成状态；合并后按实测对齐调度台接线状态 |
| [英文提案](PharmaColdOps-Proposal-EN.md) | 与中文内容同步（含 9/13 更新与合并后的实测对齐） |
| [英文配图目录](figures/en/) | 7 张 SVG 已与正文同步；两张演示截图于 2026-09-13 在 Vue 前端（API 模式）重新截取。**两张未裁剪的全幅原件未入库**（仅在提交者本机 `proposal/figures/raw/`，本文件不指向仓库内路径），入库的是裁剪并引用的 `demo-rule-engine-en.png` / `demo-route-qa-en.png`；另含 2026-09-13 的 Neo4j Browser 实拍 `kg-neo4j-browser.png`（图 4b） |
| [正式 Word（中）](PharmaColdOps_正式Proposal_4人版.docx) | 已按**合并后**的中文 Markdown 重新生成（`scripts/build_proposal_docx.py`，零第三方依赖，图片随 Markdown 引用一并嵌入）；组名、成员姓名及学号已填入；仍需人工终审 |
| [正式 Word（英）](PharmaColdOps-Proposal-EN.docx) | 英文内容在 2026-09-13 的**版本之锚**（含人工对头部的简化）；**重建会覆盖这些人工修改** |
| [提交件（英）](PharmaColdOps-Proposal-Group%2041.pdf) | **2026-09-13 提交用**：由上述英文 Word 导出的 PDF（20 页 / 4,246 词 / Letter），内容与提交时的英文 Word 一致 |
| [提案 PPT](PharmaColdOps-Proposal-Presentation.pptx) | 旧版演示文稿，提交前需要同步范围、指标和未完成项 |
| [调整版 PPT](PharmaColdOps_tune.pptx) | 保留原文件，提交前需确认是否继续使用 |

### 演讲用的两份 deck（2026-09-28）

| 文件 | 定位 | 怎么改 |
|---|---|---|
| [`PharmaColdOps .pptx`](PharmaColdOps%20.pptx) | **演讲当天用这份**：10 页，队友在 `tune` 版基础上做了视觉美化（深蓝标题条、卡片版式、金色分隔线、侧栏配图），组号已为 41，第 7 页前端截图已恢复为未裁剪原图 | 直接在 PowerPoint 里改；文字与版式改动不会自动回流到生成器 |
| [`PharmaColdOps-Proposal-Presentation-Final.pptx`](PharmaColdOps-Proposal-Presentation-Final.pptx) | **生成版与留存版**：同一内容由脚本产出（`scripts/build_presentation_final.py --short`），字体/配色已按原设计对齐（Libre Baskerville + DM Sans、#454240 系、金色点缀） | 改 `scripts/build_presentation_final.py` 后重跑；**不要手改**，会被下一次生成覆盖 |

两份不要同时改同一处文案，否则会出现两个互相矛盾的版本；**已定稿：演讲用 `PharmaColdOps .pptx`，它不再由脚本生成**（见下）。运维脚本：`scripts/set_group_number.py`（统一改组号）、`scripts/restore_screenshot.py`（换回未裁剪截图）、`scripts/deck_theme.py`（配色与字体常量）、`scripts/check_decks.py` 与 `scripts/check_deck_theme.py`（校验）、`scripts/check_deck_facts.py`（把 deck 第 7 页的实测数字与仓库重算比对，数字漂了就报错）。

### 2026-09-28：演讲用 deck 定稿与事实同步

- **定稿基准 = `PharmaColdOps .pptx`**（10 页，队友手工美化）。演讲稿 `演讲稿-4人版.md` 的页序、页码归属与数字口径**全部以这份为准**；`PharmaColdOps-Proposal-Presentation-Final.pptx` 降级为脚本生成/留存版，**不再用于现场**（它仍停在 2026-09-27：封面缺学号、日期 22 Sep，第 7 页数字为旧值）。
- 已改 `PharmaColdOps .pptx` 三处（脚本 `scripts/fix_deck_facts.py`，运行前自动在 `proposal/` 生成带时间戳的备份）：
  1. 封面成员行下补学号行（A0328771W · A0353769L · A0357864L · A0350940J，10pt，与其余两行同款字体，避免溢出）；
  2. 封面演讲日期 `22 Sep 2026` → **`29 Sep 2026`**（实际演讲日）；
  3. 第 7 页 `13 of them dispatch operations` → **`15`**、`305 test functions across 35 files` → **`34 test files`**。
- 实测口径（2026-09-28，`scripts/check_deck_facts.py` 7/7 通过）：**23 条 API 路径／24 个操作，其中 dispatch 15 路径／16 操作；305 个测试函数分布在 34 个含测试的文件（第 35 个是 `conftest.py`）；25 条归档案例；`data/audit/dispatch.sqlite3` 的 `dispatch_runs` 56 行；Vue 客户端 23 个组件**。旧稿与 `build_presentation_final.py` 里写的「13 dispatch / 35 files」是硬编码字符串，已一并改正（生成版脚本第 426/435/721/724 行）。
- 讲稿同步项：对应 deck 改为 `PharmaColdOps .pptx`、封面口播加学号、P5 补 Controlant 具名例子与用户需求、P6 区分 ICH 稳定性依据与 WHO/EU GDP/CDC 程序性引用、P7 改为 23 路径／24 操作／15 dispatch／34 文件并加「技术挑战＝首解策略构造失败」、P8 按新版 deck 重写（闭环开场 + agreement 措辞）、P9 补具体应对策略、求解器口径统一为 `PARALLEL_CHEAPEST_INSERTION` + GLS（不是 CP-SAT）、Q&A 补市场定位与求解器两问、位置与 Q&A 引用路径修正；文末新增「口径速查」六条。口播实测约 1260 词（≈8.4 分钟 @150 词/分），A/B/C/D ≈ 1:33/1:42/2:11/2:40。

### 2026-09-28：第 8 页改版（闭环上主位）

- **动机**：原第 8 页把「引擎 vs 人工 gold 54/57 = 94.7%」放成整页唯一英雄位，等于让评委把项目读成"一个标注一致性实验"；而 94.7% 度量的是引擎与**我们自己的 rubric** 的一致率，不是系统效果，也不含领域有效性验证。项目主体是"温度事件 → 处置 → 补发单 → 路线 → 证据"的冷链闭环。
- **改版后**（`scripts/fix_deck_facts.py` 的第 4 项，可复跑）：标题改为 `The Loop Runs — and Every Number Reproduces`；左栏主数字为 `4`，**紧贴其右侧有两行解释**（`dispositions the rule engine can assign:` ＋ `release, quarantine, retest or scrap — reshipment is a separate logistics action, never a fifth outcome.`）——只写"4"或只加一个名词标签都会被读成装饰，必须就地说明它是什么；随后是「PROTOTYPE EVIDENCE」三条闭环事实（19 节点真实 OSM 路网／9 节点·8 类关系图谱证据；23 API 路径·24 操作·15 dispatch·25 归档案例·56 调度作业；声明的局限：模拟需求与时间窗、不声称运营节约）；右栏三层评测**等权并列**（处置层 54/57·κ=0.6434／路线层 142.63→133.81 km·−6.19%／风险层 F1 0.691·ROC-AUC 0.925 与低于基线的 Top-1 0.143）。原页面右侧描述框是 `word_wrap=False`，17pt 文字会冲出幻灯片右缘（改版前的截图即被裁切），现全部改为可换行、字号显式指定。
- 布局实现要点（踩过的坑，改这一页前先看）：① 该页旧框名与视觉顺序不一致，且早期版本会删框，**不要按旧框名分配内容**——脚本改为把 4 条循环内容放进自建的 `loop_0..3`，卡片九槽全部按模板重建；② 主数字框高必须 ≥ 该字号的 1.17×行高（56pt 需 0.91in），否则 PowerPoint 会**静默缩小**字号；③ 任何 `Inches(...)` 不要对已是 `Inches` 的值二次换算。
- **校验**：`scripts/check_deck_facts.py` 现在覆盖第 7、8 两页（7/7 + 14/14 通过）；新增 `scripts/check_deck_geometry.py` 全篇检查越界与文本框重叠（只剩第 10 页编号圆点与其文本的原设计重叠，属已知项）；新增 `scripts/check_speech_matches_deck.py` 逐条检查"deck 上要能答出来的事实是否都写进了讲稿"（31/31；封面日期故意不念，不计入）。
- 备份：`PharmaColdOps .backup-before-slide8.pptx`（你换成新版第 7 页截图之后、第 8 页改版之前的状态）。改版前的原始版式见 git 历史。
- 打印件：问答册的 Word 版 `QA准备-演讲稿配套.docx` 由 `scripts/build_qa_docx.py` 生成（A4、1.5cm 页边距、10.5pt 正文、每问 `keepNext` 不跨页）。它与讲稿 docx 共用 `scripts/docx_kit.py` 里的 OOXML 助手，所以两份外观一致，且都不依赖 python-docx 或 pandoc；改完对应 md 重跑对应 `build_*_docx.py` 即可。
- 讲稿 `演讲稿-4人版.md` 的 P8 已按新版重写（闭环开场、逐层报数、`agreement` 而非 accuracy；隔离召回 0/3 与 15→3 条差异照旧说明）。

> 已知小瑕疵：`演讲稿-4人版.docx` 第 5 页（PART D）估算约 103% 版心高，会多出 1 行；这是估算值（无字体度量），不影响讲稿，也不影响实际时长。


本轮修订提案源稿、SVG 配图和中文 Word 提案，不改变程序行为、规则阈值、rubric 或 gold 标签。本次修订把 9/12 之后落地的实现同步进正文与配图：`/api/route` 与 `/api/qa` 已是真实端点（不再标 501），订单驱动的补发求解与调度运行状态持久化已实现并通过测试，前端对已归档补发案例会实时取路线与图谱回答；仍缺的是把中文静态页已有的配送调度台接入案例处置结论、补齐英文与 Vue 界面的对应界面，以及候选目的地池扩充。风险模型 §8.2 三行数字于 2026-09-13 用 `scripts/train_risk_full.py` 在 `requirements.txt` 记录的环境（seed 42）复跑得到，其中 LightGBM/XGBoost 的阈值与指标与原记录不同；原因实验（Top-1/Top-3/macro-F1）与新加坡路线结果仍为已有记录，本次未重跑。39/57 的引擎与 gold 一致计数已直接运行当前引擎复核。更早的 ground-truth 设计文档保留为历史设计，已完成的标注结果以正文 §8.3 和其链接的统计材料为准。

后续仍需同步并检查 PPT（本轮已修正两个 deck 共 12 处与正文矛盾的事实）、在终稿阶段复核提交记录。正文与两个 PPT 均以 A/B/C/D 表示职责，对照表见提案 §10.1（A Xu Wenzhe · B Zhu Jianyu · C Wang Lepeng · D Shen Ziyi），`PROGRESS.md` 分工表已同步姓名及 Git 提交身份。Word 已做结构检查和首页预览检查；当前环境缺少 LibreOffice/pdf2image，未完成全页 PNG 渲染检查。

---

## 提交件与源稿的差异（基准 2026-09-13 提交；**2026-09-14 合并远程 9/13 一批后重做**）

**历史背景**：提交后才发现中文静态页 `frontend/index-zh.html` 里已有订单驱动的配送调度台（`63f75c6`，9/12 20:05，经 C 的 `/api/dispatch/*` 驱动），源稿里「调度界面待建设」的说法因此过时，当时做过一轮收紧修正。该页随后于 9/12 被团队整体退役（`frontend/` 删除，Vue 成为唯一前端），调度台迁入 Vue 并接上结案案例（`POST /api/dispatch/reshipments`），远程 9/13 一批又按实测对齐了 KG/问答状态——这两件事使下表多处口径再次变化。

**基准与口径**
- **英文提交件** ＝ `PharmaColdOps-Proposal-Group 41.pdf`（2026-09-13 交 Canvas）及其来源 `PharmaColdOps-Proposal-EN.docx`（版本之锚）。**二者自提交后未再重建**，是冻结的提交口径。（该 PDF 于 2026-09-28 随组号更正由 `…Group 52.pdf` 改名；内容未改，仍是 9/13 提交的那一版。）
- **英文源稿** ＝ `PharmaColdOps-Proposal-EN.md`，提交后经两轮修订：① 远程 9/13 一批；② 2026-09-14 合并后的实测重写与 §6.2/§8.3 对齐 rubric v1.1。
- **中文源稿** ＝ `PharmaColdOps-Proposal-ZH.md`；**中文 Word 已于 2026-09-14 按合并＋对齐后的源稿重建**。

**中文侧：无遗留差异。** 句子级比对（`scripts/diff_proposal_vs_docx.py`）显示中文 Word 与中文源稿**逐句一致**，仅剩生成器固有的排版归一化（首部数行合并为一段、加粗串后的空格、图注冒号后的空格）。中文 Word 从未作为提交件交出（提交件只有英文 PDF），终稿阶段可直接以它为中文底稿。

**英文源稿与提交件的差异（11 组）**

| 位置 | 提交件（冻结口径） | 当前源稿 | 来源 |
|---|---|---|---|
| §1 概述段 | “…KG case-write code have been developed. The frontend calls the live routing and graph QA endpoints for archived reshipment cases. An order-driven dispatch screen and an expanded destination pool remain to be built.” | 单一 Vue 客户端（旧 vanilla 静态页 9/12 退役）；在线模式求解并展示结案案例路线、查图谱证据、**并把案例提交进实时配送作业**（预留库存、分配车辆、发车、模拟时钟跟踪、逐单送达）；图谱链路 9/13 端到端验证；待建＝结案表单传异常地点 + 候选目的地池扩充 | 远程 9/13 一批 + 本次实测重写 |
| §5.1 第 4 项 | “…the frontend has no dispatch screen yet.” | Vue 客户端经 `/api/dispatch/*` 完成排线／发车／模拟时钟跟踪／紧急插单，且结案案例可提交进该实时作业（预留库存并分配车辆） | 远程 9/13 一批 + 本次 |
| §5.1 第 5 项 | “Archived reshipment cases already fetch live routes and case-specific graph answers; a screen for choosing destinations and quantities remains to be built.” | 案例→订单→路线→证据的关联与前端接线 9/12 落地（离线保留固定演示路线与关键词问答兜底）；选择目的地与数量的界面待建 | 远程 9/13 一批 |
| §5.2 M5／M6／M7 三行 | M5 待建“Order-driven dispatch screen and expanded destination pool”；M6 状态止于“…frontend answers available”、待建“Evidence evaluation and relevance scoring”；M7 状态止于“…case history available”、待建“Integrated acceptance and failure-state checks” | M5 状态加“结案案例可从 Vue 客户端提交进实时配送作业”、待建改为“候选目的地池扩充／替代库存选择／多温区”；M6 状态加“机器可读四态 `status`、57 场景问答评估集、数据库 9/13 端到端”、待建加“意图分类准确率待人工标注”；M7 状态加“结案→路线→证据→配送作业闭环 9/12–9/13”、待建加“干净环境复现” | 远程 9/13 一批 + 本次 |
| §6.2 已知限制 | “…and the unresolved quarantine/scrap policy for rule 4.” | 第 4 条已由 rubric v1.1（2026-09-14）定为 `scrap`，rubric 与引擎同批更新；该档背后的低温条证据缺口仍未闭合，rubric 与引擎均不再产出 `quarantine` | **本次**（本地 rubric v1.1 对齐） |
| §6.4 配送优化段 | “Vue shows precomputed routes for demonstration cases and fetches live routes for archived reshipment cases; temperature edits do not trigger solving. Single-depot reshipment solving is implemented over HTTP…” | 在线模式按**已结案案例**实时求解并展示，离线或未结案时回退预计算演示路线；温度变化本身不触发重求解；单仓补发单→求解器映射 9/12 落地 | 远程 9/13 一批 |
| §6.5 正文两段 | 第 1 段止于“…tracked by dispatch run state, not by the graph node.”；第 2 段止于“The frontend calls it in API mode and falls back to a keyword template offline.”（无 9/13 完成清单） | 第 1 段补“本流程任何一步都不代表发生实际运输”；第 2 段改为 Vue 在线调用，并补 9/13 完成清单（四态 `status`、补发目的地进证据、主因场景聚合、`CITES` 改案例级、466/466 评估集、数据库端到端）与剩余项（异常地点 ID 未传、重复结案未去重） | 远程 9/13 一批 |
| §6.5 图 4 图注 | “Figure 4: Conceptual case chain. Facility, shipment and route associations depend on the input contracts.” | 改为“案例链视图”；并写明**补发目的地字段已由结案表单传入**、异常地点字段已定义但尚未传入 | **本次**实测核对（`frontend-vue/src/lib/api.js`） |
| §6.5 图 4b 与演示图注 | **无图 4b**；演示图注为“Demo, 2026-09-13: … The order-driven dispatch screen is not shown because it is not built; this is not evidence of a completed integrated workflow.” | 新增图 4b（9/13 Neo4j Browser 实拍，9 节点／8 类关系）；演示图注改为“2026-09-12 截图、9/13 复核”，并说明该截图早于 Vue 获得“提交案例进实时作业”的能力，闭环以 9/13 端到端复核为准 | 远程 9/13 一批 + 本次 |
| §6.6 正文／图 5／契约段／图 6 | “…Leaflet, with a legacy static demo retained.”；“precomputed routes and HTTP interfaces not yet wired to a screen are shown separately”；“what remains on the contract is the frontend dispatch screen”；“Core modules exist, while connections remain to be implemented” | 旧 vanilla 静态 demo 9/12 退役、Vue 是唯一前端；图 5 改为“四层接线状态，9/13 起案例触发求解、实时图谱问答与提交案例进实时作业均已在 Vue 接通”；契约剩余项改为“结案表单传异常地点 ID ＋ 重复结案去重”；图 6 改为“主连接 9/12–9/13 已接通，尚缺人工复核／审批字段” | 远程 9/13 一批 + 本次 |
| §8.3 指标与判断句 | “Current engine agreement with gold 39/57, 68.4%”；“Eighteen differences …”；“scrap 18/33, 54.5%”；“Rule 4's quarantine/scrap choice remains an unresolved domain-policy question…”；“Tests freeze the eighteen known differences.” | **54/57，94.7%**（rubric v1.1；v1 下为 39/57）；残留 **3 条**（S034/S035/S052，gold 均为隔离，引擎分别为放行／放行／复检）；高后果召回**隔离 0/3、报废 33/33（100%）**；第 4 条已决为 `scrap`、不再是未决政策；测试冻结 3 条 | **本次**（本地 rubric v1.1 对齐；数字由当前引擎直接复算） |
| §10.2 W0–W5 分工行 | W0 止于“Review and submission due 9/13;”，W1–W5 未列 B/C 的具体项 | W0 补“组名、成员姓名与学号已填入”；W1 补 B（task spec／多折风险）、C（order mapping）；W2 补 B（原因与切分对比）；W4 补 B（实验／失败分析）、C（Solomon 与新加坡对比）；W5 补 D（视频） | 本地 9/13–9/14 一轮 |
| §11 风险表四行 | 缓解措施较短（如“Identify evidence level, product scope and assumptions;”、“Report κ, confusion and small-sample limits;”） | 分别补“retain human review”、“revise based on domain evidence”、“no audit-grade durability claim”、“keep personal annotations private”等 | 提交后、分叉前的 9/13 例行修订（两侧同源） |
| §6.4 新加坡算例规模 ＋ §7.1 数据表 OSM 新加坡行 | §6.4：“one depot, ten hospitals”（中文：“1 仓、10 医院”）；§7.1：“11 facilities, 11×11 matrices, 110 directed paths”（中文：“11 设施、11×11 矩阵、110 条有向路径”） | **当前实测规模：19 节点／19×19 矩阵／342 条有向路径**——1 主仓（Scarlett Westgate）＋1 第三方仓（Kuehne+Nagel，降为对照）＋**14 个医院收货点**（11 公立＋3 私立）＋3 个分拨点。演进：9/15 由 1 仓库 + 10 公立医院扩至 1 仓库 + 14 个接收点；9/16 再扩至 19 节点并把主仓移至 Westgate。§6.4 与 §7.1 已于 2026-09-27 按实测改写（中英各两处），依据与取舍见 `docs/singapore_network_assumptions.md` | 2026-09-27 本地扩网对齐（与远程无关） |
| 前端网络规模文案 | 前端 `i18n/{en,zh}.js` 的 `singapore.note` 曾写死“1 depot / 10 delivery sites”（中文“1 个仓库 / 10 个配送点”），`ReroutePanel.vue` 的 served 分母为 `nodes.length - 1`（会显示 /18） | 改为从已入库路网**计算**并在模板插值：`{nodes} facilities · {hospitals} hospitals + {distribution} distribution points · {depots} main depot`；served 分母改为医院数 14；`sandbox.js` 注释同步（该注释说“10 hospitals”，实际筛选 `role === "customer"` 得 14） | 2026-09-27 与提案口径同步 |

**已还原一致的部分**：英文 Word 头部的 4 处人工修改（删副标题行、Course 行简化、组名与成员拆两行、`As of 2026-09-13` → `By now`）已回写进英文源稿，故英文 Markdown 与英文 Word 在头部逐句一致。

**终稿阶段要做的**：① 先按上表逐条决定 §1／§5.1／§5.2／§6.2／§6.4／§6.5／§6.6／§8.3／§10.2／§11 取哪一版口径；② 重建**两份** Word（英文重建会覆盖头部手改，重建前先确认已回写）；③ 由 Word 导出 PDF 作为新提交件；④ 重跑本表的句子级比对并更新本文件。

**复核方法（可复跑）**：`.venv/Scripts/python.exe scripts/diff_proposal_vs_docx.py <源稿.md> <对照.docx> <输出报告.txt>`——按句子与表格单元格做包含比对，自动归一化链接（`文本 (URL)`）与表格拆格差异，只报真正不同的单元，并标注所属小节。

