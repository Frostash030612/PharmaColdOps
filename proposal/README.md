# Proposal 版本说明

本目录当前内容基准为 **2026-09-13 修订的中英文 Markdown、英文 SVG 配图和中文 Word 提案**。**英文提案已于 2026-09-13 提交**（提交件为下方 PDF）。提交后 Markdown 源稿又做了一轮修正，因此**源稿与提交件不再逐句相等**——差异逐条登记在文末「提交件与源稿的差异」。

| 文件 | 状态 |
|---|---|
| [中文提案](PharmaColdOps-Proposal-ZH.md) | 已更新项目范围、实现状态、数据、实验、标注结果及计划 |
| [英文提案](PharmaColdOps-Proposal-EN.md) | 与中文内容同步 |
| [英文配图目录](figures/en/) | 7 张 SVG 已与正文同步；两张演示截图于 2026-09-13 在 Vue 前端（API 模式）重新截取，原图见 `figures/raw/` |
| [正式 Word（中）](PharmaColdOps_正式Proposal_4人版.docx) | 已按本次中文 Markdown 重新生成；组名、成员姓名及学号已填入；仍需人工终审 |
| [正式 Word（英）](PharmaColdOps-Proposal-EN.docx) | 英文内容在 2026-09-13 的**版本之锚**（含人工对头部的简化）；**重建会覆盖这些人工修改** |
| [提交件（英）](PharmaColdOps-Proposal-Group%2052.pdf) | **2026-09-13 提交用**：由上述英文 Word 导出的 PDF（20 页 / 4,246 词 / Letter），内容与提交时的英文 Word 一致 |
| [提案 PPT](PharmaColdOps-Proposal-Presentation.pptx) | 旧版演示文稿，提交前需要同步范围、指标和未完成项 |
| [调整版 PPT](PharmaColdOps_tune.pptx) | 保留原文件，提交前需确认是否继续使用 |

本轮修订提案源稿、SVG 配图和中文 Word 提案，不改变程序行为、规则阈值、rubric 或 gold 标签。本次修订把 9/12 之后落地的实现同步进正文与配图：`/api/route` 与 `/api/qa` 已是真实端点（不再标 501），订单驱动的补发求解与调度运行状态持久化已实现并通过测试，前端对已归档补发案例会实时取路线与图谱回答；仍缺的是把中文静态页已有的配送调度台接入案例处置结论、补齐英文与 Vue 界面的对应界面，以及候选目的地池扩充。风险模型 §8.2 三行数字于 2026-09-13 用 `scripts/train_risk_full.py` 在 `requirements.txt` 记录的环境（seed 42）复跑得到，其中 LightGBM/XGBoost 的阈值与指标与原记录不同；原因实验（Top-1/Top-3/macro-F1）与新加坡路线结果仍为已有记录，本次未重跑。39/57 的引擎与 gold 一致计数已直接运行当前引擎复核。更早的 ground-truth 设计文档保留为历史设计，已完成的标注结果以正文 §8.3 和其链接的统计材料为准。

后续仍需同步并检查 PPT（本轮已修正两个 deck 共 12 处与正文矛盾的事实）、在终稿阶段复核提交记录。正文与两个 PPT 均以 A/B/C/D 表示职责，对照表见提案 §10.1（A Xu Wenzhe · B Zhu Jianyu · C Wang Lepeng · D Shen Ziyi），`PROGRESS.md` 分工表已同步姓名及 Git 提交身份。Word 已做结构检查和首页预览检查；当前环境缺少 LibreOffice/pdf2image，未完成全页 PNG 渲染检查。

---

## 提交件与源稿的差异（2026-09-13）

**为什么会有差异**：提交之后才发现中文静态页 `frontend/index-zh.html` 里已经有订单驱动的配送调度台（`63f75c6`，2026-09-12 20:05 提交，经 C 的 `/api/dispatch/*` 真实端点驱动）。因此源稿里「调度界面待建设」的说法过时，中英文 Markdown 各做了一轮**收紧修正**。**这些修正不在已提交的 PDF 与英文 Word 内**，提交件仍是收紧前的措辞。

**英文 Markdown 与提交件的差异（5 处）**：

| 位置 | 提交件（旧） | 源稿（修正后） |
|---|---|---|
| §1 | an order-driven dispatch screen and an expanded destination pool remain to be built | 写明调度台已在中文静态页存在；待建的是**接入案例处置结论、英文与 Vue 界面、候选目的地池扩充** |
| §5.1 第 4 项 | the frontend has no dispatch screen yet | 写明中文静态页的调度台可完成排线／发车／紧急插单，但**不由案例处置结论触发** |
| §5.2 M5 行的「待建」列 | Order-driven dispatch screen and expanded destination pool | Connecting the dispatch console to a case disposition; English and Vue parity; expanded destination pool |
| §6.5 演示图注 | The order-driven dispatch screen is not shown **because it is not built** | 改为说明它**只存在于中文静态页、需 API 模式、不由案例处置结论触发**（因此不能作为闭环已接通的证明——该结论不变） |
| §6.6 | what remains on the contract is the frontend dispatch screen | …is the dispatch screen **in the English and Vue interfaces and its wiring to a case disposition** |

**中文 Markdown 与中文 Word 的差异（6 处，同一组修正）**：位置同上的 §1、§5.1 第 4 项、§5.2 M5 行、§6.4、§6.5 演示图注、§6.6。中文 Word 同样**未**重建。

**已还原一致的部分**：英文 Word 里对头部的 4 处人工修改（删副标题行、Course 行简化、组名与成员拆两行、`As of 2026-09-13` → `By now`）**已回写进** `PharmaColdOps-Proposal-EN.md`，因此英文 Markdown 与英文 Word 在头部逐句一致；重建英文 Word 现在不会再丢这些改动（正文那 5 处除外，见上表）。

**若终稿阶段要消除这些差异**：重建两份 Word（英文重建前先按上表决定 §1/§5.1/§5.2/§6.5/§6.6 取哪一版口径），再由 Word 导出 PDF，最后更新本表。
