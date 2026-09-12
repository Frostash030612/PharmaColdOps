# PharmaColdOps 项目进度记录

> 每次开发的变更汇总，供团队快速了解进展与注意事项。

---

## 2026-09-12 — Vue 接入实时改派路线与结构化知识图谱问答

> 集中交付记录（成果、运行方式、前端验收步骤、提交边界）：[docs/实施交付记录_2026-09-12.md](docs/实施交付记录_2026-09-12.md)

- `frontend-vue/` 在 API 模式下保存已归档案例的 `run_id`，为确需补发的案例分别缓存贪心/OR-Tools 路线；地图、指标和站序使用后端结果。未结案、修改过归档案例输入或无需补发时，明确显示固定演示路线。
- 补足原前端草案遗漏的实时路线 `geojson`：后端按本次求解站序导出道路折线，避免地图在收到实时结果后缺字段报错。
- 合规问答用有限关键词映射到 4 种结构化问题类型；这不是自然语言分类。无当前案例时给出提示，Neo4j 或 API 不可用时明确标注离线示意，并保留原关键词回答。
- 旧 `frontend/` 未改；路线仍是固定 1 仓库 + 10 站全量算例，并非单笔订单动态优化。
- 验证：`pytest -q -k route` 为 **8 passed**；`pnpm build` 通过。浏览器实测离线关键词回答、在线未结案提示、补发案例两种算法请求与实时道路地图、非补发回退固定演示，以及 Neo4j 不可用时的明确离线降级。

---

## 2026-09-12 — 补发单 → 改派路线 → 知识图谱问答接口落地

- `EventIn` 新增可选异常地点与补发目的地；Python `ReshipmentOrder` 使用与 Neo4j 相同的 `RO-{run_id}` 标识。
- `/api/route` 从 501 改为真实接口：读取已关闭 case，校验确需补发，按贪心或 OR-Tools 返回新加坡路线与排程摘要。MVP 固定单仓库，目的地必须属于固定 10 站算例，复用全量算例求解，不是单订单动态优化。
- `/api/qa` 从 501 改为结构化问题接口，调用现有 4 类 Cypher 查询；不做自然语言分类，图数据库不可用时返回 503。
- 新增补发单、目的地、路线 API、QA 路由和数据库故障测试；补装 `requirements.txt` 已声明但当前 `.venv` 缺失的 `neo4j>=6.3` 后，全量验证为 **96 passed / 6 skipped**。跳过项均需真实 Neo4j；本机无 Docker，未声称完成数据库端到端验证，503 故障路径已用 mock 验证。

---

## 2026-09-12 — 金标准落地：57 场景 gold 换成独立双人标注（反循环闭合）

- 起因：`data/scenarios/scenarios.csv` 的 `gold_label` 一直是**引擎自己的输出**（占位），而 `tests/test_rule_engine.py` 断言「引擎 == gold」——等于让引擎给自己判卷，正是提案 §8.3 要打破的反循环。
- 做法：B、C 各自**盲标全部 57 条**（互不讨论），A 仲裁，产出 `data/scenarios/gold_labels.csv`，带 `decision_source` / `disagreement_type` / 已脱敏 `note` 三列。**18 条与 rubric v1 字面不符**：13 条「两人答案完全相同、且都与 rubric 不符」（规范缺口，责任在说明书）+ 5 条阈值政策分歧。
- **已用新 gold 替换 `scenarios.csv` 的 `gold_label` 列**（18 条变化）。复核过除该列外逐字节未动，无 BOM + CRLF 保持不变。
- **`tests/test_rule_engine.py` 不再断言 engine == gold**，改为四件事：① 未登记的偏离必须为零；② 冻结 18 条 `(引擎值, gold 值, 类别)`；③ 冻结清单须与 `gold_labels.csv` 的分类逐条对齐；④ 把 39/57 这个结论数字本身钉住。**做了扰动测试**：改未冻结条目、改冻结条目、改凭证分类——三者都会失败并指名道姓。
- 统计：B↔C 一致 44/57，**κ = 0.6434（低于 0.80 目标）**；引擎（忠实实现 rubric）vs gold = **39/57 = 68.4%**。见 `data/processed/agreement_stats.md`。**这个数字低不是失败，是这套设计要测出来的东西。**
- 入库落点与暂存清单（`_MANIFEST.md`，平铺在仓库根）不同，改为：`gold_labels.csv` → `data/scenarios/`（设计文档写的就是这个路径）、`evaluate_engine.py` → `scripts/`、四个探测工作台 → `data/scenarios/annotation/probes/`。逐条理由见 `data/processed/PROVENANCE.md` §2。
- `evaluate_engine.py` 入库时改了两处：路径基准由 `HERE` 改为 `ROOT`；B、C 作答改为 `--private-package` 显式传入。那两份文件按红线**永不入库**，原写法会让脚本在仓库里**必然跑不动**，与 `agreement_stats.md` 写的「可复跑」矛盾。
- `.gitignore`：`data/processed/` 由 `data/processed/` 改为 `data/processed/*` 并加两条否定规则——用 `/` 排除目录本身时 git 不会进入该目录，`!` 否定**不生效**。
- 顺带修正 `PROVENANCE.md` 一处指纹错误：`annotation_findings_v1.md` 原记 `67ca06f977ccbbd5`，实际（包内/暂存/仓库三处字节一致）为 `6a3be07b2f1a67d1`，原值对不上任何现存文件。
- 影响面：`src/knowledge_graph/qa.py` 的 `match_gold` 从此报**真实**一致率（原先恒为 100%，因为 gold 就是引擎输出）。D 侧无需改代码，也无已提交的 KG 产物需要重建。
- **决策（团队，2026-09-12）**：**κ 按 0.6434 报出**（Landis & Koch 属 substantial 0.61–0.80），**不为此修订 rubric 重测**；gold 中的 3 条 `quarantine`（S034 / S035 / S052，均 `arbitration` + 规范缺口——两人一致判 quarantine 而 rubric 推 `release`/`retest`）**保留**。留档理由：`κ ≤ po` 恒成立，而 `po = 0.7719 < 0.80`，故 0.80 在这批数据上**数学上不可达**（需 ≤ 7 条分歧，实为 13 条）。已写入 `agreement_stats.md` §1。
- **`scripts/check_provenance.py`（本轮新增）**：`PROVENANCE.md` 声称这些入库件「可审计」「可复跑」，但校验逻辑原先只活在一个**不入库**的工作脚本里（`_build_to_repo.py` 在仓库外的 Temp 目录）。现固化进仓库：离线跑 §2 指纹（15 份入库件）+ §3.1 探测工作台不得含 `S0xx` + §3.3 `answer_template.csv` 必须全空；加 `--private-package` 后再跑 §1 指纹（7 份逐人作答）与 §3.2 序列复现。`--selftest` 先自证校验器**会失败**（10 条断言）——一个永远通过的校验器和没有校验器是一回事，而且更糟。
- **§3.2 加严**：原口径只查「整列复现」，会漏掉「贴了半段」，而半段足以让同一批标注者重测时认出答案。现要求**非 CSV** 入库件里不得出现 **>= 8 条连续作答**（实测最长 1 条，离阈值很远）。该检查**只施加于非 CSV 件**：CSV 入库件本就合法持有 gold 列，而 gold 是双方答案的合并，两人一致的连续段落必然与各自序列重合，查了就是假警报。
- **新增一条文档纪律**：`PROVENANCE.md` §2 登记的 15 份入库件，**凡编辑必须同一提交内更新指纹**并在该文件留下说明（新增 §2.3 记录本次对 `agreement_stats.md` 的编辑）。理由是这张表本身就是自校验基准——文件被**合法**编辑而指纹不更新，校验就会对一个**正确**的文件报假警报，而假警报会让人开始忽略真警报（§3 已记过同一教训：校验器本身也要被校验）。
- 提交：`ae3ec61`（16 文件；7 份逐人作答按红线未入库，只留指纹于 `PROVENANCE.md` §1）+ `f64984d`（κ 决策）/ `6d24688`（第 4 条政策项悬置）/ `b8e8e5e`（指纹更新与 §2.3）/ `3a98534`（`check_provenance.py`）。**已推送 `origin/main`**；推送时远端已有 D 的 KG 批次（`2cce3f0`），rebase 后重算哈希（原 `7d3c207` → `ae3ec61`）。两批唯一重叠的文件是 `.gitignore`，改动落在不同段，自动合并干净。
- **给 A 的两条提醒（推送后生效）**：① `tests/test_rule_engine.py` 现在**冻结** 18 条偏离并把 39/57 钉住——日后改 rubric / 改第 4 条政策 / 改 gold，测试会立刻变红并要求显式更新冻结清单（**设计如此**，防擅自漂移，不是被谁改坏了）；② `docs/annotation_rubric_v1.md` 已进 `PROVENANCE.md` §2 指纹表，出 v1.1 时**必须同一提交更新指纹**，否则 `check_provenance.py` 会对一处正确改动报错。
- 验证：本批 rebase 前全量 **85 passed**；与 D 的 KG 批次合并后 **87 passed / 6 skipped**（跳过项需 Neo4j，属 D 侧设计）。`check_provenance.py` 离线与 `--selftest` 均全绿。

---

## 2026-09-11 — 前端包管理器统一为 pnpm（`frontend-vue/`）

- 起因：`frontend-vue/` 同时存在 `package-lock.json`（npm）与 `pnpm-lock.yaml`（pnpm）两个 lockfile。依赖全是 `^` 范围，两种包管理器解析出的版本树可能不同，症状是「我这跑得起来你那跑不起来」。团队决定**全面转 pnpm**。
- 删除 npm 的 `package-lock.json`。**`pnpm-lock.yaml` 是唯一 lockfile**，它锁死了依赖树里每一个包的精确版本，因此不同 pnpm 版本装出的依赖完全一致。
- 文档同步：`README.md` 快速开始、`docs/前后端技术栈与连接说明.md` §11.1/§11.2 改为 `corepack enable pnpm` + `pnpm install/dev/build`，并写明「请勿再跑 `npm install`」。`PROGRESS.md` 里的历史 `npm run build` 记录是当时事实，保留不改。
- **未采用 `packageManager` 字段钉版本**：实测（pnpm 12.3.4）加上该字段后，pnpm 会把 lockfile 从单文档改写成多文档新格式（文档 1 = `packageManagerDependencies` + 全平台 `@pnpm/exe`，文档 2 = 原依赖树），684 → 785 行；且 `.npmrc` 的 `manage-package-manager-versions=false` 挡不住。为不扰动 Wang 建立的原 lockfile、避免旧版 pnpm 读不了新格式，决定不加。依赖版本已由 lockfile 锁死，收益有限。
- 验证（本机）：无 `packageManager` 字段时，`pnpm install --frozen-lockfile` 与普通 `pnpm install` **都不会改写** `pnpm-lock.yaml`（装前装后 sha256 一致）；`pnpm build` 产物 contenthash 与 npm 构建**逐字节相同**（`index-C55tIITg.css` / `index-XzHbBlTt.js`）——换包管理器零输出差异。
- 注意：`frontend/`（零依赖 vanilla 版）不受影响；无 Node 时仍可照跑。没装 corepack 的环境先 `corepack enable pnpm`，不必 `npm i -g pnpm`。

---

## 2026-09-10 — Vue 配送面板接入真实新加坡预计算路线

- 右侧配送改派面板接入 Leaflet 真实道路 GeoJSON、仓库及 10 个配送点；不同车辆使用不同颜色。
- 支持贪心/OR-Tools 切换，指标和站序同步；点击地图或站点按钮查看到达、服务时间、需求及时间窗。
- 明确标注固定演示算例与模拟订单；温度/处置变化不触发重新求解。无需补发时仍可浏览地图。
- `export_singapore_routes.py --frontend-out frontend-vue/src/data/singaporeRoutes.json` 可再生前端数据。
- 验证：Vite 生产构建通过；浏览器实测地图、方案切换与站点详情。后端算法未改，不重复运行全量 Python 测试。

---

## 2026-09-10 — C：真实新加坡道路网络与配送算例完成

- 通过 BBBike 的公开 OSM XML 文件完成取图，校验发布方 MD5；不再依赖被限流的 Overpass。
- 本地筛选 drive 道路、按新加坡边界裁剪；在最大强连通路网匹配设施，解决最近节点可能无法返仓的问题。
- 已生成并提交 `data/optimisation/singapore/network.json`：11 个设施、11×11 有向距离/时间矩阵、110 条真实道路几何；路网 23,815 节点 / 45,557 边。
- 两算法均用 2 辆车服务全部 10 客户，零违规、零未服务；贪心 142.63 km，OR-Tools（10 秒）133.81 km。
- 已导出 `data/processed/singapore/{greedy,ortools}_routes.{json,geojson}`，可供 D 使用；运行产物按既有约定不入库，随代码提交网络文件后可离线再生。
- **82 项测试全部通过，无跳过**。文档：[网络假设与复现说明](docs/singapore_network_assumptions.md)。
- 下方“真实路网待生成”为之前阶段记录，现已补齐；A/B/D 代码与跨成员契约未改。

---

## 2026-09-10 — C：新加坡矩阵接入代码完成，真实路网待生成

- 已将遗留优化模型、贪心、OR-Tools 和基线脚本分批本地提交，清理贪心死代码。
- 共享 `leg_fn` 拆分距离与时间，支持有向矩阵；新增严格 loader、一次性 OSMnx 建图脚本和全离线 GeoJSON 导出。
- 所有边的距离、时间、道路几何来自同一条最快路径；客户需求/车队/窗口明确为模拟假设。
- 原有与新增测试合计 **80 passed / 1 skipped**；跳过项是依赖尚未生成真实 network.json 的集成测试。
- 本机 `.venv` 实测 Python 3.13.12，已安装 OR-Tools、OSMnx 2.1.1、NetworkX 3.6.1；未声称已建立团队 conda cold-chain 环境。
- 网络现状：Nominatim 与 PyPI 可用；全路网请求失败/限流，等待重试后仍 429，已停止。**真实 network.json 和 GeoJSON 未生成，真实新加坡算例未验收**。
- 复现命令、设施来源、许可及剩余步骤见 [singapore_network_assumptions.md](docs/singapore_network_assumptions.md)。本轮不修改 A/B/D 模块或跨成员字段契约。

---

## 四成员下一步分工（合作基线 · 随周更新）

> 依据提案 §10.1 角色分工与 §10.2 周计划（W1 9/14–20 · W2 9/21–27 · W3 9/28–10/4 · W4 10/5–11 · W5 10/12–18 视频/报告 · W6 10/19–25 终稿，**10/25 截止**）。角色用 A/B/C/D 字母，与提案一致；把姓名填进下表后即可认领。完成一项在勾选框打 ☑。

| 成员 | 角色（提案 §10.1） | 对应目录 | 当前已就绪 |
|---|---|---|---|
| A（姓名待填） | 项目负责人 · 规则/决策引擎 · 合规 · 报告 | `src/rule_engine/` | 规则引擎 v2 完成（冻结规则+法规引用+4 产品）；57 场景；10 测试 |
| B（姓名待填） | 数据与机器学习 · 根因诊断 · 实验评估 | `src/ml/` `data/ml/` | 数据字典+审计、LR/LGBM/XGB+SHAP 与根因全实验脚本**已跑通出数** |
| C（姓名待填） | 配送优化 · VRPTW · OR-Tools/遗传 | `src/optimisation/` | 数据已备（solomon 实例 + 真实新加坡路网）；贪心/OR-Tools 均已跑通出路线 |
| D（姓名待填） | 知识图谱/问答 · 后端 API · UI · 视频 | `src/knowledge_graph/` `src/api/` | demo 前端（EN+ZH）；KG 已接 Neo4j（容器 + 加载 + 问答），`/decide` 契约测试在位 |

### A —— 规则 / 决策引擎 / 报告

- [ ] **提案冲刺（9/13 前）**：终版提案定稿提交；把「真 ML 骨架已出数」写进 §6/§8（引用 PROGRESS 下方数字，务必带合成数据警示句）。
- [ ] **W1-A**：把 `src/rule_engine/rules_config.json` 的占位阈值按真实数据校一遍——demo 接真实数据后暴露「占位 allowable=30 min 把小时级超限全判报废」。产出：4 产品「阈值证据表」（来源链接到 WHO/GDP 文档级，不杜撰条款号）。阈值动 → 同步跑 `pytest`（gold 场景跟着改）。
- [ ] **W2-A**：报告方法论初稿（§8.3 反循环评估）：gold label 应改成独立人工标注流程（谁写场景、谁核 label 要分开），写清「与 ML 训练集不共用」。
- [ ] **W3-A**：规则↔ML 特征对齐接口设计（供 B 落地）；跨成员「补发单」字段契约与 C 对齐。
- [ ] 全程：维护本 PROGRESS、例会分派、风险清单（提案 §11）跟踪。

### B —— 数据与机器学习

- [ ] **提案冲刺（9/13 前）**：§7 数据描述贴 DATA_DICTIONARY 口径（来源/行数/合成声明）；**到源页逐一核实许可证**（当前是「待核实」占位，提交前必做）。
- [ ] **W1-B**：写 **ML task spec**——录入 schema ↔ 模型特征对齐表、vaccine-distribution 派生标签方案定死、**时间切分矛盾正面决策**（silent-failure 无时间戳 → 接受随机切分+注明，或改用带 `date` 的 vaccine-distribution 建时间序列任务补充）。
- [ ] **W2-B**：把已跑通骨架升级成报告正式版：多折 CV 实验表、SHAP 图并进实验节、把 `data/processed/` 关键数字同步回 PROGRESS/报告。
- [ ] **W3-B**：根因特征正当性分析（核心问题：只用前置上下文 vs 结果列的权衡、防「用结果解释结果」）+ macro-F1/top-3 正式表 + SHAP/特征重要性图。
- [ ] 全程：每次实验交代 seed / 切分 / 阈值选择，保证可复现。

### C —— 配送优化（VRPTW）—— 仓库侧还空着，任务量最大

- [ ] **提案冲刺（9/13 前）**：确认 OR-Tools 可行性（装 `ortools` 出 hello-world 即可）；demo 右栏「简化启发式 ≠ 正式求解器」口径在提案/README 一致（已注）。
- [ ] **W1-C**：建 `src/optimisation/` 包 + 输入/输出 schema 定义（**补发单 → 仓库分配 → 车辆路线**的数据契约，字段与 A/B/D 对齐）；贪心基线正式化（把 demo 的 NN+2-opt 思路搬成带时间窗/容量约束校验的 Python 实现）。
- [ ] **W2-C**：OR-Tools / CP-SAT v1 求解器，跑通 solomon c101（有全局最优参考值可对）。
- [ ] **W3-C**：主流程打通 + 贪心 vs CP-SAT 对比表；多温区 / 缺货优先级留 W4（可选）。
- [ ] 产出文件固定位：`data/optimisation/`（输入已入库）→ 结果写 `data/processed/`（不入库）。

### D —— 知识图谱 / 问答 / 集成 / UI

- [ ] **提案冲刺（9/13 前）**：准备提案要用的 1–2 张 demo 截图/流程图；确认 demo 里合规问答的定位（KG 概念示意 or 查图真问答）在提案里口径一致。
- [ ] **W1-D**：建 `src/knowledge_graph/`：schema v1（实体/关系：产品、规则、法规、案例/补发单）+ 数据加载脚本（从 rules_config + scenarios 导节点）。
- [ ] **W2-D**：`src/api/` FastAPI 骨架：`/decide`（接 A 引擎）、`/route`（接 C，先留 stub）、`/qa`（接 KG）三个路由契约定死——这是四模块集成的锚点。
- [ ] **W3-D**：打通「异常 → 处置 → 改派」最小闭环的 API + 前端；KG 问答要么换成真查询、要么维持概念示意并在报告如实标注。
- [ ] **W5-D**：视频脚本（demo 录屏走查）+ 报告集成章节。
- [ ] **W4–W5·部署（D 主导，全员试）**：契约端点 + `Dockerfile` + 上云（Render/HF/静态兜底），演示前一晚全网实测——**架构基线见「前后端接口与上云」节**。

### 跨成员契约（防各做各的）

1. **异常事件 schema**：`ExcursionEvent`（产品/温度/时长/MKT/包装/环节）是全系统入口——A 已在引擎定义，C/D 不要再自造字段。
2. **补发单 → 改派**：A 引擎产 `reshipment` 标志 → C 收到「补发单」生成改派路线 → D 展示。字段契约 W2 前三方定死。
3. **风险分 ↔ 前端**：demo 现用规则启发式风险指数（确定性、同阈值同源）；B 的 ML 分只进报告不接 UI（schema 错位已论证），若最终要接 UI 需 B+D 先做 feature bridge。
4. **git 纪律**：一功能一 commit、commit message 写清做了啥（历史里出现过 `9.8 0.4`、`重复` 这类无效消息）；**只 commit 源码/文档/数据集，`data/processed/` 与模型产物不入库**（`.gitignore` 已拦）。

---

## 前后端接口与上云（架构基线 · 随周更新）

> 面向 W2–W5：demo 现在**纯静态**（规则引擎的 JS 忠实移植 + `real_data.js`，零后端也能跑）。这是特点也是风险——JS 逻辑与 Python 引擎是**两份实现**，接口与部署要把「何时用 Python 真实现」定清楚，别等答辩周才补。

### 1. 推荐：前后端解耦 + 契约优先，同一份 demo 双模式

前端不重写，加一个 `API_BASE` 配置点（config 常量 / 环境变量），三种取值切三种形态：

| `API_BASE` | 形态 | 谁在算 |
|---|---|---|
| `''`（空） | 静态演示模式（现状，默认） | 前端 JS `evaluate()` |
| `http://127.0.0.1:8000` | 本地联调 | 本机 FastAPI 接真 Python 模块 |
| `https://…onrender.com` | 上云全栈 | 云端 FastAPI |

事件录入表单两种模式共用，只是「判/算」换成调后端。**离线 demo 永不失效，答辩现场网络挂了也有兜底。**

### 2. 四个契约端点（W2-D 前定死 schema）

Pydantic 模型 = 引擎 dataclass 的序列化（`model_dump`），**不要手写两遍 JSON 映射**。字段名以现有 `Decision` 输出为准（README-zh 承诺过「JS 与 Python 引擎一致」），谁都不许再造别名。

| 端点 | 输入 | 输出 | 后端实现 | 状态 |
|---|---|---|---|---|
| `POST /api/decide` | `ExcursionEvent` JSON | `Decision` JSON（disposition / risk / evidence / regulation） | `src/rule_engine`（现成） | 引擎已可用，只差套壳 |
| `POST /api/route` | 补发单 → 仓库/订单 | 改派路线（车辆序列 + 时间窗） | `src/optimisation`（C） | W2-C 起，此前 stub 501 |
| `POST /api/qa` | 自然语言问题 | 答案 + 依据节点 | `src/knowledge_graph`（D） | 此前 stub 501 |
| `GET /api/health` | — | `{status: ok}` | — | 探活用 |

建议加 `tests/test_api_contract.py`：断言 demo JS 里用到的键 ⊆ FastAPI 返回 JSON 键，防「前端改字段、后端不知道」。

**诚实边界：ML 模型不进 API。** 风险分是规则启发式（确定性、同阈值同源）；真 ML 只进报告（schema 错位已论证）。好处是**后端不用打包任何模型产物**——`data/processed/` 本来 gitignored 不上云也成立，B 的活不受部署影响。

### 3. 上云怎么做（分层，演示日永不裸奔）

- **Level 0 · 纯静态兜底（现在就能做）**：`frontend/` 推 GitHub Pages / Vercel，零后端上线。前端字段已是演示全集。
- **Level 1 · 全栈默认路径（推荐 Render 免费 Web Service）**：
  1. W2-D：`src/api/main.py` FastAPI + uvicorn 跑通 3 个 stub + `/api/decide` 接上引擎；
  2. 根目录加 `Dockerfile`（`python:3.11-slim` → `pip install -r requirements.txt` → 拷 `src/` + `data/` → uvicorn 启动）；
  3. push GitHub → Render 连仓库自动部署（数据文件都在 repo 里，demo 规模**不需要数据库**）；
  4. 前端 `API_BASE` 指向 Render 域名，打开即全栈 demo。
- **备选 / 学校额度**：Hugging Face Spaces（Docker，偏 ML 展示）、Azure for Students / AWS Educate（NUS 学生若可申请，配额更高）。
- **注意**：① 免费实例闲置会休眠，再次请求冷启动几秒——**演示前先访问一次预热**；② 免费条款会变，**演示前一晚全网实测一遍**（别答辩当天第一次上云）；③ 数据全为合成/公开，无敏感信息，但 CORS 白名单要设、key 别写进前端；④ 国内网络不稳的话，本地 `uvicorn` + `localhost` 演示即可，上云只给演示日 / 新加坡现场用。

### 4. 时间线归属（并入分工清单）

契约定死 → W2-D 骨架 → W3 最小闭环 → W4/W5 Docker + 上云 + 录屏。D 主导联调与部署，C/A 保证 `/route` `/decide` 真实现，B 无需参与（ML 不上 API）。

---

## 2026-09-10 — A：金标准标注 rubric v1 草案 + 57 场景分包规划（`docs/annotation_*.md`）

### 做了什么

- **`docs/annotation_rubric_v1.md`**（标注说明书，给 B/C）：纯文字判定说明书——类别定义（release/retest/quarantine/scrap）、4 产品规格表（储存范围/允许时长/MKT/冻敏/可否复检）、6 条按优先级的判定规则 + 快速判定表、7 个**非场景库**工作示例（含边界比较：恰好等于允许时长 → retest、不可复检产品近限 → release）。**不含代码 / rule 编号 / 引擎 reason**；阈值标版本（rules_config 2026-09-10 占位），A 核实后发 v1.1 只重标受影响场景；法规仅文档级。
- **`docs/annotation_split_v1.md`**（分包与流程）：B、C **各独立全量标 S001–S057**（两人份交集 = 57，kappa 才可算；A 分工表「各半」措辞已按 B/C 两栏排期澄清为双人全量）；排期表（B 9/11–13 分 30/15/12 条；C 分 20/20/17 条，均 9/13 交 A）；独立性规则；回稿格式；A 侧 9/14 kappa → 9/15–16 阈值落地触发的补标子集 → 9/18 `gold_labels.csv` 替换占位 → 9/19 评估表。
- 动机：`scenarios.csv` 占位 `gold_label` + `test_rule_engine.py` 断言引擎==gold 是反循环；改为独立人工双标注打破（提案 §8.3）。

### 待办 / 交接

两份均为 **A 起草草案**：A 复核判定顺序与阈值口径 → 9/10 ① 发给 B/C（rubric v1）；阈值核实（9/10–11）落地后若数值变，出 v1.1 + 受影响场景补标清单。DAILY_PLAN A 9/9 ②③ 已 ☑（① 填姓名仍待认领）。

---

## 2026-09-10 — B：6 份 dataset 许可证到源页逐一核实（`data/ml/DATA_DICTIONARY.md`）

### 做了什么

- 清掉数据字典里「许可证待核实」占位：**6 份公开 dataset 全部到源页面逐条核实** license（不据转载 / 文件头推断）。
- 核实路径（可复现，均已记录在 §8）：
  - **Hugging Face 4 份** → 读数据集卡 raw `README.md` 的 YAML `license:` 字段（比渲染卡片权威）：Electric Sheep Africa 三份（vaccine-cold-chain / africa-synth-immunization / africa-cold-chain-iot）→ **CC BY 4.0**；`ClarusC64/clinical-quad-coldchain…` → **MIT**。
  - **Kaggle 2 份**（skarin / manankhanna0）→ 公开 API `GET /api/v1/datasets/view/{owner}/{slug}` 的 `licenseName` → **CC0: Public Domain**。
- DATA_DICTIONARY 各数据集节补「许可」行；§7 结论 5 更新为「已核实」；新增 **§8 许可证逐条核实记录**（表：平台 / 作者 / license / 核实位置 / 使用义务 + 报告写作提醒），可直接搬进报告 §7 数据描述与致谢。
- 义务提醒（写报告时用）：CC BY 4.0 ×3 需**署名 Electric Sheep Africa** 并附许可链接；MIT ×1 随分发保留版权声明；CC0 ×2 法律上免署名、建议仍标注来源。

### 验证

纯文档改动（单文件 diff）；核实日期 2026-09-10，报告引用此日期即可。数据本体 / 审计产物仍在 `data/processed/`（不入库），数据字典本身入库。

---

## 2026-09-10 — W0 前置收尾：`src/optimisation/` Solomon loader（C 侧）+ KG schema v1（D 侧）

### C · 9/10 ①：optimisation 包骨架 + Solomon 统一加载器（`src/optimisation/`）

- 新建 `src/optimisation/`（此前整块不存在）：`__init__.py`（M5 定位，注明 `ReplanResult` / `ReshipmentOrder` 字段契约 9/21 定、不在此自造）、`models.py`（统一数据类 `Node` / `SolomonInstance`：节点/坐标/需求/时间窗/服务时长）、`solomon_loader.py`（`load_instance` / `load_dir` 读 `data/optimisation/solomon/` 6 个 JSON，带结构校验）。
- **关键澄清**：JSON 里的 `cost` 列实为 Solomon **服务时长**（C 类 90、R/RC 类 10、depot 0），并非成本——统一数据类如实命名 `Node.service` 并留注释，避免下游贪心 / CP-SAT 误当成本；输入侧仍校验源键。
- 测试 `tests/test_solomon_loader.py`：6 实例全覆盖（101 节点 = depot + 100 客户、时间窗 / 需求 / 服务时长断言，缺 depot / 重复 id / 时间窗倒挂 / 负需求 → `ValueError`）。`.venv/Scripts/python.exe -m pytest -q` → **36 passed**（原 19 + 新 17）。
- 下一步（C）：W1 贪心基线直接消费这批数据类；`ReplanResult` 输出契约 9/11 起草、9/21 终版。`c101` 文献最优 828.94 已作模块注释里的对照锚。

### D · 9/10 ①：KG schema v1 文档（`docs/KG_SCHEMA_v1.md`）

- 8 实体属性表 + 6 关系（`EVENT_LEADS_TO_DISPOSITION` 边属性承载决策现场 rule_no / reason / rule_path / regulation / risk）+ 典型问答路径骨架（喂 W2 `/api/qa` 模板：为何隔离 / 依据哪条法规 / 依据哪条 SOP / 最常见场景）。
- 四条纪律写死：字段名与引擎 / API 契约同源不造别名、法规引用只到**文档级**不杜撰条款号、决策写入对齐审计 `run_id` 幂等、SOP / ReshipmentOrder（9/21 契约）/ Facility 坐标（待 C M5）一律标 `pending`。
- 下接：9/11 `src/knowledge_graph/schema.py`（约束 / 索引落地）、9/14+ 加载脚本、W1 9/20 定稿。

**DAILY_PLAN**：C、D 两栏 **9/10 ①** 已打 ☑。

## 2026-09-10 — 跨会话过往记录 + 结案归档 + 弹窗 UX（`frontend-vue/`，API 模式）

### 归档语义（后端决策定死，前端只管入口与文案）

沙盒里的判定只是**实时预览，绝不自动入库**；只有用户显式「结案入库」才归档一条。`data/audit/runs.jsonl` 追加日志改为**每个结案的入库案例一条**（append-only，后端运行日志，已加 `.gitignore` 不入库）。

| 端点 | 行为 |
|---|---|
| `POST /api/decide` | **仅预览**，永不写运行日志 |
| `POST /api/case_close` | 按提交的输入用确定性引擎重算 → 追加**一条**归档记录并返回（含 `run_id`/`created_at`/`started_at`/可选 `remark` + decision/evidence/risk + `event` + `spec`） |
| `GET /api/runs?limit=200` | 归档列表，**最新在前** |

事件记录只存六个输入（产品/温度/时长/MKT/包装/环节）——不回声 `spec_override`，防止把一次性规则配置当成该单的既定事实泄漏给后续读表方。

### 前端（`frontend-vue/`）交互

- **标题栏两个入口（仅 API 模式）**：「过往记录」→ 居中弹窗；「+」→ 新增入库弹窗，位于「EN/中文」左边。
- **新增入库 = 居中弹窗**（背景虚化）：表单（产品/阶段/包装/温度/时长/MKT）+ 可折叠规则配置（默认产品阈值）+ 批次/备注；**实时判定预览**（处置色带/补发/风险/根因/规则路径，与页面同源纯函数）。**结案入库前完全不碰原页面**；点结案才 `POST /api/case_close`，成功后弹窗关、整条流程灌回主页面沙盒、滚回顶部。
- **过往记录弹窗**：全表居中、背景虚化；**点任一行 → 该记录的 `event`+`spec` 还原到主页面沙盒**（时间线/判定横幅/边界图/规则路径/风险/证据全部由 event+spec 重新推导），弹窗关、回顶部，可再编辑/回放。底部原「过往记录」区块保留，与弹窗共用同一张表。
- 新拆 `overlay` store（同时只开一个弹窗 + 弹窗时锁 body 滚动）；`history` store 纯读归档；`sandbox.restoreCase(record)` 供两处载入共用。

### 验证

后端契约测试 19 条全绿；`npm run build` 通过；浏览器手测（用户）：标题栏「过往记录」/「+」开合、新增结案后主页面刷新、点历史行载入对应流程，EN/ZH × 离线/API 两模式正常（离线不显示这两个入口与归档区）。

### 数据纪律

`data/audit/` 已进 `.gitignore`——运行日志只在本地生成，绝不上库（`data/processed/` 纪律的延续）。

---

## 2026-09-09 — 前端 Vue 化落地：`frontend-vue/`（Vue 3 + Vite，双模式保真）

### 决策

需求方明确「前端目前需求要 vue 做」。方案：**新建顶层 `frontend-vue/` = Vue 3 + Vite 完整 SFC 工程（纯 JavaScript，不用 TS）**；旧 `frontend/` 两个自包含静态页**原样保留并行、继续可用**，直到日后 demo 切换（README/docs 已标「切换前仍可用」）。双模式语义原样迁移：有 `?api=` → FastAPI 真引擎；无 → 内置 JS 引擎兜底；两模式与 vanilla 逐字节一致。

### 共同前置（谁要跑 Vue 谁先装，非可选）

- **Node.js LTS**（本机 winget per-user 装 v24.19.0）：`node -v` / `npm -v` 验证。Vite 硬前提，无 node 跑不了 dev/build。
- 永不提交 `frontend-vue/node_modules/`、`frontend-vue/dist/`（根 `.gitignore` 已追两条；frontend-vue/.gitignore 亦有）。

### 工程形态

| 项 | 内容 |
|---|---|
| 栈 | Vue 3 `<script setup>` SFC + Vite 8（`base:'./'` → dist 任意静态托管可跑）+ Pinia 双 store（`sandbox`/`decisions`）|
| i18n | 轻量自研模块（**不用 vue-i18n**）：`en.js`/`zh.js` 平行字典 + `t(key,{param})`；语种默认 `navigator.language`，Header EN/中文开关存 `localStorage` |
| 地图 | **双层**：离线手写 360×210 SVG 兜底 + 联网时升级 Leaflet——仅当节点带 `loc`(lng/lat) 激活；今日数据全 `loc:null` → 恒 SVG、零网络 |
| 纯逻辑 | `frontend-vue/src/lib/*` 为框架无关 ES 模块（不 import Vue/i18n），收 `L` 措辞包 → EN/ZH 同源，可单测、可与 vanilla 对比 |
| 数据 | `scripts/export_demo_data.py` 加 **`--out-esm`**（增量，默认输出字节不变）：单次运行同源双出 `frontend/real_data.js` + `frontend-vue/src/data/realData.mjs`（后者仅多 `export const` 与节点 `loc: null`，防双源漂移）|

### 未动的（范围纪律）

后端 `src/api/`、`src/rule_engine/`、Python 测试、两个 vanilla 文件**本轮未改**；既有代码唯一改动是 `export_demo_data.py` 的增量 `--out-esm`。`frontend/real_data.js` diff 为空。契约测试 15 条全绿；`check_demo_js.py` 对 vanilla 仍 [ok]。

### 验证

- 纯函数 parity（Node 冒烟 24 项）：金场景 scrap/rule3/risk99、冻结→scrap/rule1、rule_path 打 code 非 label（两种语种）、override 翻转、SVG 尺寸、zone 格 26×18、QA 关键词等，离线 = 后端语义。
- EN/ZH SSR 启动冒烟全过（各面板双语渲染）；`npm run build` 后 `dist` 静态伺服 200。
- 浏览器手测（用户做）：见 `docs/前后端技术栈与连接说明.md` §11——api pill 连接中→已连接→不可达→≤4s 自动重连、只拖滑杆不重发 grid、Leaflet 待 `loc` 出现才激活、EN/ZH × 离线/API 与 vanilla 并排对照。

---

## 2026-09-09 — demo → frontend 更名 + audit 日志 + 团队文档合并

- **目录更名**：`demo/` → `frontend/`（`git mv` 保历史）；全库 `demo/` 路径、`-d demo`、脚本默认输出路径同步改 `frontend/`；起静态页改为 `python -m http.server 5500 -d frontend`。
- **audit 日志**：`src/api/service.py` 每次 `/api/decide`（grid/batch 亦有）在 uvicorn 控制台打印「收到什么 → 判定结果」，演示/录屏直接可见前端往返（详情见 docs/前后端… 第 6 节）。
- **代码地图**：README 与 docs 文档顶部新增「前端 = frontend/、后端 = src/api/、判定核心 = src/rule_engine/」对照，防止组员改错目录。
- **并入队友提交**：`docs/ARCHITECTURE.md`（M1–M7 模块分工，保留）＋ `requirements.txt` 重写（fastapi/uvicorn 已入 M7 节，与本文档互相引用）。

---

## 2026-09-09 — 前后端分离：FastAPI 决策服务 + demo 全后端模式（双模式）

### 本轮内容（纯代码；requirements/Dockerfile/README 上云说明留下一轮）

- **引擎**：`Decision` 增 `rule_no`(1–6) + `reason` 字段，`_decide` 带参存储 —— API/审计无需镜像 6 条分支（7 引擎测试仍绿）。
- **后端新增 `src/api/`**（FastAPI + uvicorn，装进 .venv）：
  - `POST /api/decide` → 语义 dict（disposition/rule_no/reshipment/event+spec 回声/evidence 分类/risk{score,cause_code}）；未知产品 → 422 附合法 id。
  - `POST /api/grid` → 一次返回热力图矩阵（依赖 spec 不随滑杆变，避免逐格请求）；`POST /api/decide_batch` → 预置卡片 disposition。
  - `POST /api/route` `/api/qa` → 501 占位（C/D 未上 HTTP）。`GET /api/health`。
  - CORS 全开（支持 file:// 直开 demo）。**沙箱 override 随请求显式带**，服务端默认仍以 rules_config 为准（每请求 `resolve_spec` + 副本引擎，不改模块级 specs）。
- **切分点（答辩口径）**：后端只判**语义**（disposition/rule_no/cause_code/evidence 分级）；reason/法规/cause **文案按语言在前端本地化**（`RULE_TEXT[rule_no]`/`CAUSE_TEXT[code]`/`EV_LBL` 表）——避免后端背 EN/ZH 两套语言。
- **demo EN/ZH**：`?api=<base>` 进入「全后端」模式（决策/热力图/预置卡以后端为准，防抖 ~80ms `/api/decide`）；无 `?api` 默认离线，逐字节回落本地 JS 引擎，行为与旧版完全一致。滑杆/换产品时 `syncGrid()` 一次重拉。
- **测试**：`tests/test_api_contract.py` 8 条（health/黄金 shape/422/override/grid/batch/API==直连引擎前 5 场景/501），与引擎测试合计全绿；`uvicorn` 实机冒烟通过。
- **JS 自检**：`scripts/check_demo_js.py`（esprima 语法检查，无 DOM）两个 demo 均 [ok]。

### 验证命令

```bash
.venv/Scripts/python.exe -m uvicorn --app-dir src api.main:app --port 8000   # 仓库根
# 浏览器：python -m http.server 5500 -d frontend
#   frontend/index.html            → 离线（默认，行为不变）
#   frontend/index.html?api=http://127.0.0.1:8000   → 后端判定 + pill 状态指示
```

---

## 2026-09-09 — 数据处理纪律：修正「切分前全局填充」泄漏

### 问题

三个训练脚本的缺失值中位数都在 **train/val/test 切分之前对全表计算**（`df = fill_median(df)` 在 `train_test_split` 前）→ 测试行的统计量（各列中位数）泄漏进了训练特征。表无时间轴，所以准确说是 **feature-distribution leakage**，不是「未来数据」穿越；但规则相同：**划分先行，全局统计只从 train 算**。

### 修复（数字基本不变，消除答辩会问的泄漏点）

| 文件 | 改动 |
|---|---|
| `src/ml/evaluate.py` | `fill_median(df, fill=None)` 支持传入常量 Series；默认仍自算，注释写明纪律 |
| `scripts/train_risk_full.py` | 先按行索引切 70/15/15 → `fill = df.loc[itr].median()` → `fill_median(df, fill=…)` |
| `scripts/train_root_cause.py` | 先按位置切 80/20 → `fill = X.iloc[pos_tr].median()` → 同一常量填全表再 to_numpy |
| `scripts/train_risk_model.py` | 切 80/20 后 `fill = Xtr.median()`，`Xtr/Xte` 用同一常量填 |

复跑验证：risk-model 与 risk_full 的 LR 数字与改前一致（AUC 0.891–0.893、F1 0.626），silent-failure 缺失仅 2 列 ≤4.2%，影响可忽略。

### 纪律（B 的 W1-B task spec 继承，答辩口径）

1. **划分先行**：任何 train/val/test 切分在所有全局统计**之前**完成。
2. **train-only 拟合**：填充值 / 分位截断阈值 / scaler / 编码器，一律只从 train 行计算，val/test 用**同一常量**，绝不在 val/test 上重算。
3. 现在的代码顺序即范本：`split（按行索引/位置）→ train 算 fill → 全局填 → train fit scaler → 变换 va/te`。
4. 树模型（LGBM/XGB）原生支持 NaN 可作为将来选项，但当前缺失率低、且与 LR 共用 StandardScaler 矩阵，维持「train 中位数填充」即可，不为此分叉管道。

---

## 2026-09-09 — ML 完全体骨架：风险全实验（LR/LGBM/XGB+SHAP）+ 根因多分类

### 决策

把提案 W2/W3 的「真 ML」骨架提前搭好、已跑通出数；脚本一次写对、默认超参，只读回指标行。训练本地免费，token 只花在写码（已封顶）。

### 新增 `src/ml/`（正式模块目录）

| 文件 | 说明 |
|---|---|
| `src/ml/__init__.py` | 模块标记 |
| `src/ml/evaluate.py` | 共享评估工具：类别平衡权重、验证集选 F1 最优阈值、二分类指标、多分类 top-1/top-3/macro-F1 |
| `scripts/train_risk_full.py` | 风险全实验：LR/LGBM/XGB（均 balanced），70/15/15 分层，阈值从验证集选（非固定 0.5），两组特征对照 + SHAP beeswarm |
| `scripts/train_root_cause.py` | 根因多分类：vaccine-cold-chain `excursion_cause`（10 类），上下文特征，LGBM(balanced) vs 多数类 |

### 风险预测结果（silent-failure，8,000 行，正类 19.7%，seed=42）

| 特征集 | 模型 | thr | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|
| interpretable | LR (balanced) | 0.55 | 0.626 | 0.891 | 0.651 |
| interpretable | **LGBM (balanced)** | 0.35 | **0.688** | **0.925** | **0.745** |
| interpretable | XGB (balanced) | 0.30 | 0.659 | 0.919 | 0.734 |
| all | LGBM (balanced) | 0.45 | 0.708 | 0.926 | 0.760 |

- **LGBM > LR/XGB；`all` 相对 `interpretable` 仅 +0.001 AUC** → 匿名 `feature_x1..3` 依旧无实质增益。
- SHAP beeswarm 存到 `reports/ml/shap_risk.png`；|SHAP| top 特征：`rh_std`、`transit_days`、`door_opens`、`temp_max_c`（可解释字段主导——好故事）。
- ⚠️ 数据无时间戳 → **非时间切分**（70/15/15 分层随机），报告须注明；数据疑似合成，指标只描述生成器。

### 根因诊断结果（vaccine-cold-chain，16,192 条超限行 × 10 类）

| 模型 | top-1 | top-3 | macro-F1 |
|---|---|---|---|
| majority-class | 0.161 | 0.284 | 0.028 |
| LGBM (balanced) | 0.143 | **0.421** | **0.125** |

- **诚实解读**：只用「前置上下文」（设备/电源/监测/疫苗属性）→ top-1 弱于多数类（balanced 权重牺牲 top-1 换 macro-F1），但 top-3 0.42 有信号。原因类更多编码在「温度/用量结果列」里——把结果列加进来会虚高且接近描述仿真构造。**这是 W3 的核心分析问题**（哪些特征可正当用于诊断、如何防「用结果解释结果」），留给 B 组员。

### 复现

```bash
pip install -r requirements.txt            # 含 lightgbm xgboost shap matplotlib
python scripts/train_risk_full.py          # → data/processed/risk_model_full_results.md
python scripts/train_root_cause.py         # → data/processed/root_cause_results.md
```

结果 md 均在 `data/processed/`（不入库），复跑即得。

### 下一步

1. W3：根因特征正当性分析 + 把 SHAP 图/实验表并进报告实验节。
2. 时间切分矛盾：或改用带 `date` 的 vaccine-distribution 另建一个时间序列任务作为补充实验。

---

## 2026-09-09 — demo 风险指数（规则启发式）+ ML 基线首次出数

### 决策（省 token 且诚实）

放弃「把 ML 模型接进 demo」——模型输入（shipment 级汇总）与 demo 录入（单条超限事件）schema 错位，接进去要先扩录入表单 + feature bridge，成本高且难自圆其说。改为两轨：

1. **A｜demo 风险指数 = 确定性规则评分**（替换原「ML 风险评分（概念示意）」占位）。
2. **B｜真 ML 基线只进报告**（训一次 LogisticRegression，数字落盘，不接 UI）。

### A 做了什么（`frontend/index.html` + `index-zh.html`）

- `riskInfo()` 重写为**规则启发式风险指数**：分量 = 温度越出温带幅度（按带宽归一）· 超限时长/允许值 · MKT/阈值 · 包装破损；冻敏 ≤0 °C 冻结（规则 1）与破损包装（规则 2）各自置顶最低值。与规则引擎同一组阈值 → **与处置结果同源、可解释、随滑杆实时翻转**。
- 文案从「ML 风险评分（概念）」改为「风险指数（规则启发式 · 确定性，非 ML 模型）」；脚注同步说明仅 VRPTW 与知识图谱问答仍为概念示意。
- 函数经括号配平校验；两文件逻辑一致、文案本地化。

### B 做了什么（`scripts/train_risk_model.py`）

- 一次性脚本：silent-failure 8,000 行，缺失中位数填充，80/20 分层随机切分（**数据集无时间戳 → 无法时间切分，报告需注明**），StandardScaler + LogisticRegression。
- 对比两组特征：`interpretable`（剔除匿名 `feature_x1..3`）vs `all`。

**首次结果（seed=42，正类 19.7%）**

| 模型 | acc | prec | rec | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|---|
| 多数类基线 | 0.803 | 0 | 0 | 0 | 0.500 | 0.197 |
| interpretable | 0.851 | 0.673 | 0.476 | 0.558 | **0.893** | **0.674** |
| all（含匿名特征） | 0.851 | 0.674 | 0.467 | 0.552 | 0.893 | 0.673 |

- **`all` 与 `interpretable` 几乎持平 → 匿名 `feature_x1..3` 无信息增益**，佐证「只用可解释特征讲故事」的取舍正确。
- ⚠️ **该 Kaggle 数据集疑似合成**（DATA_DICTIONARY §1）：AUC 0.89 只在生成器上有效，**不代表真实世界的静默失效预测**——数字进报告必须带这句。
- LightGBM/XGBoost 留给 B 组员跑正式实验表（脚本已留接口：装了 lightgbm 再跑会自动追加一行）。

### 修改文件

| 文件 | 说明 |
|---|---|
| `frontend/index.html` / `index-zh.html` | `riskInfo` 重写 + 标题/脚注文案 |
| `frontend/README-zh.md` | 风险指数说明更新（非 ML 模型；离线基线数字 + 诚实警示） |
| `scripts/train_risk_model.py` | 新增：一次性 LogisticRegression 基线 |
| `requirements.txt` | 未动（sklearn 仅本机装了；组员装 `pip install scikit-learn`） |

### 验证

- 打开 `frontend/index.html`：风险条随「超限温度/时长/MKT」滑杆实时变化，标签已不含「ML/概念」。
- `python scripts/train_risk_model.py` → 结果写入 `data/processed/risk_model_results.md`（不入库）。

### 下一步

- task spec（录入 schema ↔ 模型特征对齐）仍建议先写，作为 W2 B 组员的工作输入。
- 报告需要时把 AUC/PR-AUC 表 + 合成警示贴进 §7/§8 实验节。

---

## 2026-09-09 — ML 起步：数据字典 + 数据审计（`data/ml/`）

### 做了什么

1. 新增 `data/ml/DATA_DICTIONARY.md`（**人工维护的数据字典**）：6 组数据集逐一给来源/行数/粒度/字段含义/标签语义/诚实标注 + 「ML 任务 → 数据集」映射表 + 实操结论。
2. 新增 `scripts/audit_datasets.py`（**可复现审计脚本**，纯 pandas）：对 `data/ml/` 全部 CSV/parquet 输出行数/重复/逐列缺失率·基数·数值范围、标签平衡、top 相关特征（泄漏筛查）。全量报告 → `data/processed/ml_audit_report.md`（不入库）。用法：
   ```bash
   .venv/Scripts/python.exe scripts/audit_datasets.py
   ```
3. 首个「开箱即训练」判断（写进了字典 §7）：**silent-failure（8,000×24）是唯一可直接做二分类的主数据集**；根因诊断目标在 vaccine-cold-chain 的 `excursion_cause`/`wastage_cause_primary`；vaccine-distribution 无标签，派生标签方案须先写进 task spec。

### 审计发现（重要，写报告要用）

- **几乎全是合成/仿真数据**（与既有结论一致）：africa-cold-chain-iot 自带 `is_synthetic` 列且 =100%；africa-synth 名称即 synth；Kaggle 两数据集形态高度规则化、**疑似合成**（silent-failure 有匿名化 `feature_x1..3`，报告需如实写）。
- silent-failure：无重复、缺失极少（`temp_recovery_rate` 0.8% / `rh_max` 4.2%）；`silent_failure` 正类 **19.7%**（不平衡）；相关度集中在可解释字段（`transit_days` 0.45 / `temp_max_c` 0.44 / `door_opens` 0.39），**无标识符泄漏**。
- vaccine-cold-chain 与规则引擎**同名字段**（`freeze_sensitive` / `shake_test_done` / 冻结·热超限标记）——是模块对齐的天然锚点。
- ClarusC64 每文件仅 10 行，是它本来的大小，不可训练。
- **许可证未逐一生成，需提交前到源页面核实并写入报告附录（字典里不杜撰）。**

### 新增 / 修改文件

| 文件 | 说明 |
|---|---|
| `data/ml/DATA_DICTIONARY.md` | 新增：数据字典 + 诚实标注 + ML 任务映射 |
| `scripts/audit_datasets.py` | 新增：可复现审计脚本 |
| `README.md` | data 布局表链接到 DATA_DICTIONARY.md + audit 用法 |

### 下一步（B 角色的顺序建议）

1. 写 **ML task spec**（target/特征命名空间/时间切分/防泄漏），把字典第 2 小节 vaccine 派生标签方案定死。
2. 修规则引擎 W1-A 阈值前，可用 silent-failure 先出 **LogisticRegression / LightGBM 首基线**（需装 sklearn/lightgbm，正式排期 W2）。

---

## 2026-09-08 — demo 接入真实数据集

### 做了什么

1. 写 `scripts/export_demo_data.py`：从已下载数据集抽取真实数据，生成 `frontend/real_data.js`。
2. `frontend/index.html` / `index-zh.html` 改为加载 `real_data.js`，替换原来的硬编码合成场景与药房/路线数据。
3. 真实数据来源：
   - **场景事件（18 个）** 来自 Kaggle `vaccine-distribution-temperature`（真实温度 / 超限时长 / 地点 / 流转环节，含真实 `discarded` 报废记录）。
   - **配送数据** 来自 Solomon VRPTW `c101.json`（10 个客户的真实坐标 / 需求 / 时间窗）+ 最近邻 + 2-opt 简化路线求解。

### 诚实说明（重要）

- `mkt_c` 由单点温度读数近似（源数据无 MKT 列）；`packaging` 固定 `intact`（源数据无此字段）；`stage` 由真实 `current_hop` 映射；产品类别由温度区间推断（源数据无 `product_id`）。映射逻辑见脚本顶部注释。
- **真实数据 + 占位阈值（allowable 30 min）→ 真实超限事件（时长 1–6 小时）几乎全部判报废，只有「在途正常」数据判放行**。这暴露了占位阈值需要按真实小时级超限重新校准（W1-A 的一部分）。
- 配送路线求解（最近邻 + 2-opt）是简化启发式，非真实 VRPTW 求解器；单辆车 + 紧时间窗导致违规数偏高，属预期。

### 修改文件

| 文件 | 说明 |
|---|---|
| `scripts/export_demo_data.py` | 新增：真实数据 → demo JS |
| `frontend/real_data.js` | 生成：18 真实事件 + 10 Solomon 客户 + 路线 |
| `frontend/index.html` / `index-zh.html` | 加载 real_data.js，删除硬编码数据 |
| `frontend/README-zh.md` | 数据来源说明 |

---

## 2026-09-08 — 规则引擎 v2：冻结规则 + 法规引用 + 4 产品

### 做了什么

1. **补冻结损坏缺口（最高优先级新规则）**：旧引擎只看「破损包装 + 温度>上限」和时长/MKT，一个冻敏疫苗被冻到 −5°C（短时长）会被错误判为 `release`。新增规则 1：`freeze_sensitive 且 温度 ≤ 0°C → scrap`，依据 WHO TRS 961 Annex 9（冻敏疫苗冻结即失效）。
2. **每个决策带法规依据**：`Decision` 新增 `regulation` 字段（同时进 `evidence`），6 条规则各挂 WHO TRS 961 Annex 9 / EU GDP 2013/C 343/01 文档级引用（**未杜撰具体条款号**，答辩前需核实）。
3. **产品 2 → 4**：新增 `insulin_2_8`（胰岛素 2–8°C，冻敏、可复验）与 `mrna_ultracold`（mRNA −90…−60°C，非冻敏、不可复验）；现有 `vaccine_2_8` 标为冻敏。
4. **场景库 47 → 57**：新增冻结场景、冻敏 vs 非冻敏对照、胰岛素 4 类处置全覆盖、mRNA 3 类处置。
5. **测试 3 → 7**：新增冻结触发报废、冷冻品不触发冻结规则、新产品加载、法规字段存在性 4 个测试。
6. **演示前端同步**（`frontend/index.html` + `index-zh.html`）：4 产品可选、6 条规则、冻结规则移植、证据面板加「冻结风险」行 +「法规依据」行。

### 新增 / 修改文件

| 文件 | 说明 |
|---|---|
| `src/rule_engine/models.py` | `ProductSpec.freeze_sensitive`、`Decision.regulation` |
| `src/rule_engine/engine.py` | 冻结规则（规则 1）+ 6 条规则法规引用 + `FREEZING_POINT_C` |
| `src/rule_engine/rules_config.json` | 2 → 4 产品，`freeze_sensitive` 标志，更新 `_note` |
| `data/scenarios/scenarios.csv` | 47 → 57 条 |
| `tests/test_rule_engine.py` | 3 → 7 个测试 |
| `frontend/index.html` / `frontend/index-zh.html` | 前端同步（4 产品、冻结规则、法规展示） |

### 如何验证

```bash
.venv/Scripts/python.exe -m pytest -q   # 7 passed
```

### 设计决策与注意事项（重要）

1. **冻结阈值用 0°C（冰点），不是 `storage_min`**：冻结损坏的本质是结冰，发生在 ≤0°C；而「低于 storage_min 但 >0°C」的「低温未冻结」是另一种更轻微的越限，暂未单独建规则（沿用时长/MKT 规则），代码里已注释，可作为后续低严重度规则。
2. **诚实约束不变**：WHO TRS 961 Annex 9 / EU GDP 给的是**原则**，不是逐产品数值阈值；新增产品（胰岛素/mRNA）的数值阈值仍是**占位值**。唯一例外是 mRNA 有真实可引的厂商多级稳定性窗口（解冻后 2–8°C ~30 天、室温 ~6h），本引擎用**单阈值近似**并已在 `_note` 标注，后续可升级为多级阶梯模型。
3. **冻结规则一律报废（scrap）**：WHO 对冻敏疫苗立场是「冻结即弃用」。真实操作中有「摇匀试验（shake test）」作为现场筛查手段（WHO 亦有提及），更精细版本可把「冻敏 + 冻结」降级为 `quarantine` 做摇匀试验——当前 demo 用保守的 scrap 默认。

### 下一步（建议顺序）

1. A：继续替换真实阈值（W1-A），mRNA 多级稳定性窗口可做成 `stability_tiers` 列表。
2. 两名组员独立标注 + 仲裁（§8.3 第 2–3 步），把 gold_label 从「规则推导占位」换成「独立人工标注」。
3. B/C/D：`src/ml/`、`src/optimisation/`、`src/knowledge_graph/` 基线。


## 2026-09-08 — data/ 目录按模块重组

### 做了什么

把 `data/` 从「按来源（huggingface / kaggle / cvrplib）」改为**按项目模块**组织，与 `src/` 一一对应：

```
data/
├── ml/               # 风险预测与根因诊断模块（知识发现）—— 4 个冷链数据集
├── optimisation/     # 配送改派模块（资源优化）—— Solomon VRPTW 算例
└── processed/        # §7.3 预处理输出（跨模块共享），生成、不入库
```

> 注：`data/scenarios/`（规则引擎金标准场景库）为自建伪数据，不计入数据布局。

### 修改文件

| 文件 | 变更 |
|---|---|
| `scripts/download_data.py` | HF 数据集 → `data/ml/<名称>/`；Solomon → `data/optimisation/solomon/`；清单改为 `data/MANIFEST.md` |
| `.gitignore` | `data/raw/` → `data/ml/` + `data/optimisation/`（`data/processed/` 与 `*.parquet` 保持忽略） |
| `README.md` | 新增 Data layout 表格 |

### 数据集 → 模块映射

| 数据集 | 目标目录 | 模块 |
|---|---|---|
| Cold Chain Shipment Silent Failure（Kaggle，需 token） | `data/ml/cold-chain-silent-failure/` | 风险预测 / 故障分类 |
| Vaccine Distribution w/ Temperature Logging（Kaggle，需 token） | `data/ml/vaccine-distribution-temperature/` | 异常检测 / MKT 模拟 |
| Electric Sheep vaccine-cold-chain（HF） | `data/ml/electricsheepafrica__vaccine-cold-chain/` | 设施 / 路线级异常 |
| Africa Synth Immunization Quality（HF） | `data/ml/electricsheepafrica__africa-synth-immunization-vaccine-quality-cold-chain-all/` | 数据增强 / 质量标签 |
| Solomon VRPTW（CervEdin 镜像） | `data/optimisation/solomon/` | 改派算法基准 |


---

## 2026-09-07 — 仓库骨架 + 规则引擎 v1 + 场景库扩充

### 做了什么

1. **搭好仓库骨架**：README、requirements.txt、conftest.py（让 tests 能 import `src/`）。
2. **规则引擎 v1（决策自动化模块）**：`ExcursionEvent → Decision`，5 条优先级规则输出 `disposition`（release / quarantine / retest / scrap）+ `reshipment_required` + 可审计的 `rule_path`。
3. **场景库从 6 条扩到 47 条**（金标准，覆盖 4 类处置 + 边界情况）。
4. **建 venv + 装 pytest**，测试套件全部通过（3 个测试，其中主测试遍历 47 条场景逐条断言）。

### 新增 / 修改文件

| 文件 | 说明 |
|---|---|
| `README.md` | 项目说明、模块表、快速开始 |
| `requirements.txt` | 目前仅 `pytest` |
| `conftest.py` | 把 `src/` 加入 import 路径 |
| `src/rule_engine/__init__.py` | 包标记 |
| `src/rule_engine/models.py` | `ExcursionEvent` / `Decision` / `ProductSpec` / `Disposition` |
| `src/rule_engine/engine.py` | 规则引擎（5 条优先级规则） |
| `src/rule_engine/rules_config.json` | 产品阈值（**占位值**） |
| `data/scenarios/scenarios.csv` | 金标准场景库（47 条） |
| `tests/test_rule_engine.py` | 引擎 vs 金标准断言 |
| `.gitignore` | `data/` → `data/raw/`+`data/processed/`；移除 `*.csv` 全量忽略（让场景库可被提交） |

### 场景库分布（47 条）

- 处置类别：release 12 · retest 8 · quarantine 13 · scrap 14
- 产品：vaccine_2_8（2–8°C，33 条）· frozen_m20（−20°C，14 条，不可复验）
- 包装：intact 45 · compromised 2
- 覆盖的边界：duration = 24 / 30 / 60（阈值点）、MKT = 9.5 / 10 / 13、包装破损、冷冻品不可复验

### 如何验证

```bash
.venv/Scripts/python.exe -m pytest -q   # 3 passed
```

### 设计决策与注意事项（重要）

1. **阈值是占位值**：`rules_config.json` 里的「2–8°C 允许超限 30 min」等是示例，需按 WHO TRS 961 Annex 9 / EU GDP 2013/C 343/01 及供应商稳定性数据确认后替换（对应 W1-A）。
2. **gold_label 目前是「规则推导」的占位**，**不是** §8.3 第二步要求的「独立人工标注」。它现在的用途是：① 校验引擎行为符合预期；② 作为场景库的种子。后续必须由两名组员只读书面 rubric（不看代码）独立标注 + 第三人仲裁，替换这些 label，才算完成 §8.3 的独立金标准。
3. **「reshipment」建模为派生标志**：提案里「放行/隔离/复验/报废/补发」5 类中，「补发」不是批次处置、而是物流动作，故代码里用 `reshipment_required`（scrap/quarantine 时为 True）表达；`gold_label` 只取 4 个主处置类别。此映射已写在 `models.py` 的 docstring 里，写报告时需向评审说明。
4. **venv 与大型数据不入库**：`.venv/`、`data/raw/`、`data/processed/`、`*.parquet` 均在 `.gitignore`。

### 下一步（建议顺序）

1. A：替换 `rules_config.json` 真实阈值（W1-A）。
2. 两名组员对 47 条场景独立标注 + 仲裁（§8.3 第 2–3 步）。
3. B：下载数据集，搭 `src/ml/` 风险预测基线（LightGBM / XGBoost）。
4. C：搭 `src/optimisation/` 的 greedy 基线（VRPTW）。
5. D：搭 `src/knowledge_graph/` 的实体-关系 schema。

---

## 2026-09-07 — 数据集调研 + 下载脚本

### 做了什么

1. 逐条核实提案 §7.1 的 5 个主数据集是否真实存在、能否下载、真实 vs 合成、访问限制。
2. 另找到 2 个补充的 Hugging Face 冷链数据集。
3. 写 `scripts/download_data.py`，下载**免登录**的数据源，并生成 `data/raw/MANIFEST.md` 清单。

### 数据集调研结论（重要）

| 数据集 | 来源 | 状态 | 说明 |
|---|---|---|---|
| Cold Chain Shipment Silent Failure (~8k 行) | Kaggle | **需 Kaggle API token** | 提案 §7.1 风险预测主数据，含 `label`/`silent_failure` |
| Vaccine Distribution w/ Temperature Logging (~26.7k 行) | Kaggle | **需 Kaggle API token** | 温度异常检测 / MKT 模拟 |
| vaccine-cold-chain (3×10k 行) | Hugging Face | ✅ 已下载 | Electric Sheep Africa，设施/线路级冷链异常 |
| africa-synth-immunization-vaccine-quality-cold-chain-all (3×10k 行) | Hugging Face | ✅ 已下载 | 数据增强 / 质量标签补充 |
| CVRPLIB (Solomon VRPTW) | atd-lab PUC-Rio | ✅ 已下载 6 实例 | 配送优化基准（c101/c201/r101/r201/rc101/rc201） |
| africa-cold-chain-iot（parquet） | Hugging Face | ✅ 已下载（补充） | IoT 传感器类 |
| clinical-quad-coldchain…v0.1（9 行） | Hugging Face | ✅ 已下载（补充） | 仅 9 行的 demo，**样本量太小，仅作参考** |

**结论：几乎所有公开冷链数据都是合成/仿真数据**（真实药企传感器数据因商业敏感不公开）。这一点需在报告里如实说明——我们用「公开合成数据 + 自建金标准场景库 + 规则生成的仿真时间序列」来兜底（对应提案 §8.3 反循环设计）。

### 下载脚本

- 文件：`scripts/download_data.py`
- 用 `huggingface_hub` 直接拉**原始文件**（CSV/parquet/json），**不用** `datasets.load_dataset`——后者会执行加载脚本、只给 1~10 行的样例 split，而非全量数据（这是之前踩的坑）。
- 用 `requests` 从 CervEdin 的 Solomon JSON 镜像拉 6 个 VRPTW 实例（官方 `vrplib` 只读不下载、`cvrplib` 不在 PyPI 上）。
- 运行：
  ```bash
  .venv/Scripts/python.exe scripts/download_data.py            # 全部（免登录）
  .venv/Scripts/python.exe scripts/download_data.py --hf-only  # 只 HF
  .venv/Scripts/python.exe scripts/download_data.py --vrp-only # 只 Solomon
  ```

### 下载结果（已验证大小/行数）

- HF 6 个大 CSV 各 **10,000 行**（10001 行含表头），parquet 约 202 KB——**全量，非样例**。
- Solomon 6 个 JSON 实例各 ~9–10 KB。
- `ClarusC64` 的 2 个 CSV 各只有 9 行，是它**本身的真实大小**（小样本 demo），不是下载 bug。

### 注意事项

1. **Kaggle 两个数据集未下载**（需 API token）。手动步骤：到 Kaggle 账号 → Settings → Create API Token 生成 `kaggle.json`，放到 `~/.kaggle/`，再 `pip install kaggle` 后用 `kaggle datasets download -d skarin/cold-chain-shipment-silent-failure-dataset` 与 `-d manankhanna0/vaccine-distribution-with-temperature-logging`。
2. `data/raw/` 不入库（已在 `.gitignore`），只保留 `MANIFEST.md` 当记录即可（当前也未入库，等需要时再决定）。

---

*尚未提交到 GitHub（按约定先不 commit）。*
