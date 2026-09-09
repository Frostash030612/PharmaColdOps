# 金标准标注 · 操作手册（给 B / C 标注者）

本目录是标注工作台。**你在这里标注，但标完的结果不要提交到 GitHub**（见 §4）。

## 0. 前置（先确认）

- 你是 **B** 或 **C**（两栏各自独立标，互不商量）。A 只仲裁，不参与标。
- 已拿到 A 签发的 **rubric v1**：`docs/annotation_rubric_v1.md`（本目录文件都基于它）。
- 你的排期：见 `docs/annotation_split_v1.md` §2（B、C 都各标全 57 条，分 9/11–9/13 三天）。

## 1. 打开哪份文件（标注输入）

打开 **[`input_v1.csv`](input_v1.csv)**：57 行，每行一个场景，**只有输入列**（产品 / 温度 / 时长 / MKT / 包装 / 环节），**没有答案列**。

> 它是 `data/scenarios/scenarios.csv` 去掉 `gold_label` 列后冻结的版本——原始文件里答案列就在输入旁边，直接开原始文件 = 看着答案标，务必用这份。

## 2. 怎么标

对着 [rubric v1](../../../docs/annotation_rubric_v1.md) 的 §3 产品表 + §4 六条规则，**逐行**给 `input_v1.csv` 里的场景判类别：

| disposition 取值 | 含义 |
|---|---|
| `release` | 放行 |
| `retest` | 复检（仅允许复检产品） |
| `quarantine` | 隔离 |
| `scrap` | 报废 |

- 数字直接比较、不四舍五入；边界语义看 rubric §5 示例。
- 判完把类别填进**答案模板**（下一步），不要改 `input_v1.csv`。
- 哪条规则让你犹豫，在 `note` 里写一句，别空着也别跳过。

## 3. 在哪填（答案文件）

打开 **[`answer_template.csv`](answer_template.csv)**：已预置 57 个 `scenario_id`，你在 `disposition` 列填类别（`note` 列可选）。

**操作建议**：把 `answer_template.csv` 另存为本地一份，用 Excel / 表格软件 / VS Code / 纯文本打开填。一次标一个场景、对着 rubric，别一次看很多行凭感觉猜。

## 4. 标完传哪里（关键）

1. 确认 57 行**全填完、无缺行**（`wc -l` 应 58 含表头；或表格里数 57 行）。
2. 把你填好的文件保存为 `gold_label_B.csv`（B）或 `gold_label_C.csv`（C）。
3. **9/13（周日）23:59 前，私发给 A**（微信 / Teams / 邮件等一对一渠道）。
4. **不要 push 到 GitHub**。公共分支上另一位标注者（或收件记录里的任何人）一旦看到你的答案，双人独立性就没了，kappa / 金标准全部作废。A 收齐后自己合并、算 kappa、仲裁，9/18 出 `data/scenarios/gold_labels.csv`。

## 红线（违反 = 标注作废）

- ❌ 不打开 `src/rule_engine/`、`tests/`、`src/api/`、demo 页面。
- ❌ 不看 `data/scenarios/scenarios.csv` 的 `gold_label` 列。
- ❌ 不和另一位标注者讨论答案（交稿、A 公布分歧后除外）。
- ✅ 拿不准就按 rubric 判 + 写 `note`。

## 文件清单

| 文件 | 作用 | 是否入库 |
|---|---|---|
| `input_v1.csv` | 盲标输入（57 行，无答案列） | ✅ 入库，git pull 即可拿 |
| `answer_template.csv` | 空白答案模板 | ✅ 入库，作起点 |
| `gold_label_B/C.csv` | **你填完的答案** | ❌ 不入库，私发 A |
| `docs/annotation_rubric_v1.md` | 判定说明书 | ✅ 入库 |
| `docs/annotation_split_v1.md` | 排期与流程 | ✅ 入库 |

> 阈值版本：本表对应 rubric **v1**（`rules_config.json` 2026-09-10 占位值）。若 A 核实后发 **v1.1**，只重标受影响产品的场景，清单由 A 随 v1.1 给出。
