# Proposal 版本说明

本目录当前内容基准为 **2026-09-13 修订的中英文 Markdown、英文 SVG 配图和中文 Word 提案**。**英文提案已于 2026-09-13 提交**（提交件为下方 PDF）。提交后 Markdown 源稿又做了一轮修正，因此**源稿与提交件不再逐句相等**——差异逐条登记在文末「提交件与源稿的差异」。合并远程 9/13 一批后，两文的 §1 / §5.1 / §5.2 / §6.4 / §6.5 实现状态已按实测重新对齐（含 QA 四态、图 4b、单一 Vue 前端与调度台接线）。

| 文件 | 状态 |
|---|---|
| [中文提案](PharmaColdOps-Proposal-ZH.md) | 已更新项目范围、实现状态、数据、实验、标注结果及计划；9/13 更新 §1 与 §6.5 的 KG/问答与事件触发路线集成状态；合并后按实测对齐调度台接线状态 |
| [英文提案](PharmaColdOps-Proposal-EN.md) | 与中文内容同步（含 9/13 更新与合并后的实测对齐） |
| [英文配图目录](figures/en/) | 7 张 SVG 已与正文同步；两张演示截图于 2026-09-13 在 Vue 前端（API 模式）重新截取。**两张未裁剪的全幅原件未入库**（仅在提交者本机 `proposal/figures/raw/`，本文件不指向仓库内路径），入库的是裁剪并引用的 `demo-rule-engine-en.png` / `demo-route-qa-en.png`；另含 2026-09-13 的 Neo4j Browser 实拍 `kg-neo4j-browser.png`（图 4b） |
| [正式 Word（中）](PharmaColdOps_正式Proposal_4人版.docx) | 已按**合并后**的中文 Markdown 重新生成（`scripts/build_proposal_docx.py`，零第三方依赖，图片随 Markdown 引用一并嵌入）；组名、成员姓名及学号已填入；仍需人工终审 |
| [正式 Word（英）](PharmaColdOps-Proposal-EN.docx) | 英文内容在 2026-09-13 的**版本之锚**（含人工对头部的简化）；**重建会覆盖这些人工修改** |
| [提交件（英）](PharmaColdOps-Proposal-Group%2052.pdf) | **2026-09-13 提交用**：由上述英文 Word 导出的 PDF（20 页 / 4,246 词 / Letter），内容与提交时的英文 Word 一致 |
| [提案 PPT](PharmaColdOps-Proposal-Presentation.pptx) | 旧版演示文稿，提交前需要同步范围、指标和未完成项 |
| [调整版 PPT](PharmaColdOps_tune.pptx) | 保留原文件，提交前需确认是否继续使用 |

本轮修订提案源稿、SVG 配图和中文 Word 提案，不改变程序行为、规则阈值、rubric 或 gold 标签。本次修订把 9/12 之后落地的实现同步进正文与配图：`/api/route` 与 `/api/qa` 已是真实端点（不再标 501），订单驱动的补发求解与调度运行状态持久化已实现并通过测试，前端对已归档补发案例会实时取路线与图谱回答；仍缺的是把中文静态页已有的配送调度台接入案例处置结论、补齐英文与 Vue 界面的对应界面，以及候选目的地池扩充。风险模型 §8.2 三行数字于 2026-09-13 用 `scripts/train_risk_full.py` 在 `requirements.txt` 记录的环境（seed 42）复跑得到，其中 LightGBM/XGBoost 的阈值与指标与原记录不同；原因实验（Top-1/Top-3/macro-F1）与新加坡路线结果仍为已有记录，本次未重跑。39/57 的引擎与 gold 一致计数已直接运行当前引擎复核。更早的 ground-truth 设计文档保留为历史设计，已完成的标注结果以正文 §8.3 和其链接的统计材料为准。

后续仍需同步并检查 PPT（本轮已修正两个 deck 共 12 处与正文矛盾的事实）、在终稿阶段复核提交记录。正文与两个 PPT 均以 A/B/C/D 表示职责，对照表见提案 §10.1（A Xu Wenzhe · B Zhu Jianyu · C Wang Lepeng · D Shen Ziyi），`PROGRESS.md` 分工表已同步姓名及 Git 提交身份。Word 已做结构检查和首页预览检查；当前环境缺少 LibreOffice/pdf2image，未完成全页 PNG 渲染检查。

---

## 提交件与源稿的差异（基准 2026-09-13 提交；**2026-09-14 合并远程 9/13 一批后重做**）

**历史背景**：提交后才发现中文静态页 `frontend/index-zh.html` 里已有订单驱动的配送调度台（`63f75c6`，9/12 20:05，经 C 的 `/api/dispatch/*` 驱动），源稿里「调度界面待建设」的说法因此过时，当时做过一轮收紧修正。该页随后于 9/12 被团队整体退役（`frontend/` 删除，Vue 成为唯一前端），调度台迁入 Vue 并接上结案案例（`POST /api/dispatch/reshipments`），远程 9/13 一批又按实测对齐了 KG/问答状态——这两件事使下表多处口径再次变化。

**基准与口径**
- **英文提交件** ＝ `PharmaColdOps-Proposal-Group 52.pdf`（2026-09-13 交 Canvas）及其来源 `PharmaColdOps-Proposal-EN.docx`（版本之锚）。**二者自提交后未再重建**，是冻结的提交口径。
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
| §7.1 数据表 OSM 新加坡行 | “11 facilities, 11×11 matrices, 110 directed paths”（中文：“11 设施、11×11 矩阵、110 条有向路径”） | “**15 facilities, 15×15 matrices, 210 directed paths**”（中文：“15 设施、15×15 矩阵、210 条有向路径”）——2026-09-15 把本地路网由 1 仓库 + 10 公立医院扩至 **1 仓库 + 14 个接收点**（11 公立医院站点 + 3 私立医院），理由与取舍见 `docs/singapore_network_assumptions.md` | **本次**（本地扩网，与远程无关） |

**已还原一致的部分**：英文 Word 头部的 4 处人工修改（删副标题行、Course 行简化、组名与成员拆两行、`As of 2026-09-13` → `By now`）已回写进英文源稿，故英文 Markdown 与英文 Word 在头部逐句一致。

**终稿阶段要做的**：① 先按上表逐条决定 §1／§5.1／§5.2／§6.2／§6.4／§6.5／§6.6／§8.3／§10.2／§11 取哪一版口径；② 重建**两份** Word（英文重建会覆盖头部手改，重建前先确认已回写）；③ 由 Word 导出 PDF 作为新提交件；④ 重跑本表的句子级比对并更新本文件。

**复核方法（可复跑）**：`.venv/Scripts/python.exe scripts/diff_proposal_vs_docx.py <源稿.md> <对照.docx> <输出报告.txt>`——按句子与表格单元格做包含比对，自动归一化链接（`文本 (URL)`）与表格拆格差异，只报真正不同的单元，并标注所属小节。

