# 来源凭证 · 标注包 v1

**目的**：让标注结果**可审计**，同时**不分发**原始作答文件。

原始作答含两位标注者（下称 B、C）的逐条判断。按项目红线，
两人在各自提交前不得看到对方的答案——一旦泄露，独立性与 κ 全部作废。
因此**文件本身不入库**，只在此登记指纹。

**核验方式**：任何持有原始文件的人都可以用
`sha256sum <文件>`（Windows：`certutil -hashfile <文件> SHA256`）比对下表。
不一致即表示文件被改动过，本批数据不可信。

---

## 1. 原始作答文件（**不随仓库分发**）

| # | 文件 | 字节 | SHA-256 |
|---|---|---|---|
| 1 | `gold_label_B(1).csv` | 787 | `a3ff749e911ccc94a6858d922a76e2e02514584724415d424e438f86e88e6d07` |
| 2 | `gold_label_C.csv` | 795 | `6fd4f3136dc7a93442f3f4b17a85cc7b4c62f6752f2a20b8e6222cbf654d0175` |
| 3 | `探测作答_B.csv` | 1468 | `69d1a9b9a076549af8a423408d4019241aeb1997388219241a753de7577d0769` |
| 4 | `探测作答_C.csv` | 1441 | `4d89dc4d62122ab851d23fa0bb7a7a6658f2ae2a0853d72ec4185d742c2c8150` |
| 5 | `规则定位作答_B.csv` | 1383 | `57bb5d3dd8227c1903afef7c86492e944ce93fa46c3294d2d2ebb06790e4bcca` |
| 6 | `规则定位作答_C.csv` | 1394 | `ea5ee6b2e179e9532fe8bdafeeed990b522363db7a85766c8576e0924199d098` |
| 7 | `探测题号对照_勿公开.csv` | 1144 | `bff7bb4c3cd462ac27bb81c795a6e97ba3d4ed69988d53cc252ab434984afdff` |

**说明**：

- 1、2 为原轮 57 条的作答（`scenario_id, disposition, note`）。
- 3、4 为温度轴探测的作答（17 场景 + 1 问答）。**该轮数据不可用于修订 gold**，
  理由见 `agreement_stats.md` §8。
- 5、6 为规则定位探测的作答（21 条，含「命中第几条」与「实际判什么」两列）。
- 7 是探测题号 → 原轮场景号的回连表。**本身不含答案**，
  但它暴露了"哪几条被重测"，配合任何一份作答即可还原，故同样不入库。

> 📌 **为什么把回连表也列为敏感**：探测轮刻意在页面源码里剥掉了 `S0xx`，
> 就是为了不让标注者认出被重测的是原轮哪几条。回连表一旦外流，这层设计即失效。

## 2. 入库件（随仓库分发）

以下文件**不含任何一方的逐条作答**，已通过自动校验（见 §3）。

| 文件（**仓库内路径**） | SHA-256（前 16 位） |
|---|---|
| `data/scenarios/gold_labels.csv` | `c62069d46e5aac0e` ⚠️ **已脱敏，见 §2.1** |
| `scripts/evaluate_engine.py` | `ac8c597f7caa7375` ⚠️ **见 §2.2** |
| `data/processed/agreement_stats.md` | `cf25aa8b5aea94b3` ⚠️ **见 §2.3** |
| `docs/annotation_rubric_v1.md` | `a762ceed3ad725d4` |
| `docs/annotation_split_v1.md` | `bd5f2a232b37f06a` |
| `docs/annotation_findings_v1.md` | `6a3be07b2f1a67d1` |
| `data/scenarios/annotation/README.md` | `eb8c6ff05ba7b114` |
| `data/scenarios/annotation/input_v1.csv` | `6e8680263c0a75b2` |
| `data/scenarios/annotation/answer_template.csv` | `aa48d27375cb2d56` |
| `data/scenarios/annotation/标注工作台_B.html` | `f48a2148eede0d52` |
| `data/scenarios/annotation/标注工作台_C.html` | `4a2b7a3866da908e` |
| `data/scenarios/annotation/probes/探测工作台_B.html` | `20e8bca3f8158cf8` |
| `data/scenarios/annotation/probes/探测工作台_C.html` | `9c20edb7ed371dc5` |
| `data/scenarios/annotation/probes/规则定位工作台_B.html` | `c27148c2846c19da` |
| `data/scenarios/annotation/probes/规则定位工作台_C.html` | `6fb99b864a21c10b` |

> **落点说明（2026-09-12 入库时定）**：本表路径为**仓库内实际路径**，与
> `_MANIFEST.md` 的暂存布局（全部平铺在仓库根）不同。三处改动及理由：
>
> 1. `gold_labels.csv` → `data/scenarios/gold_labels.csv`。设计文档
>    （`annotation_split_v1.md` §、`data/scenarios/annotation/README.md` §4、
>    `DAILY_PLAN.md` 9/18 ②）写的都是这个路径，且与 `scenarios.csv` 同目录。
> 2. `evaluate_engine.py` → `scripts/`。仓库所有 Python 入口都在 `scripts/`。
>    移动后脚本改为按 `ROOT`（`scripts/` 的上级）解析数据路径，见 §2.2。
> 3. 四个 `*工作台_*.html` → `data/scenarios/annotation/probes/`。
>    `_MANIFEST.md` 自己建议了这个位置但未新建目录。
>
> `_MANIFEST.md` 本身是搬运说明，**未入库**——暂存目录已不存在，留着会误导。

> `gold_labels.csv` 的表头为
> `scenario_id, gold_label, decision_source, disagreement_type, note`——
> **没有 B 列或 C 列。**

### 2.1 ⚠️ `gold_labels.csv` 的 `note` 列已脱敏

**列结构干净不等于内容干净。** 原文件的 26 条 `note` 写的是

> 「仲裁：**B 判** retest、**C 判** quarantine；按 rubric 第 5 条取 retest」

——点名了双方各自判了什么。57 条里有 **26 条（46%）** 可从中还原出标注者的答案。
若日后对**同一批标注者**重测，这等于把答案直接给他们。

入库前按下表规则去掉**人名归属**，保留**判定依据**：

| 原文 | 入库版 |
|---|---|
| 仲裁：B 判 X、C 判 Y；…… | 两人判读不同；…… |
| 采信 B、C 一致判读 X | 两人一致判读 X |
| 采信 C 的严判 X（B 判 Y） | 采信严判 X |
| ……，B 的 Y 与其自身政策不符 | （删除） |
| B、C 在盲测复述题中各自独立确认 | 两人在盲测复述题中各自独立确认 |

**脱敏是构建步骤，不是一次性手工操作**——写在 `_build_to_repo.py` 里，
每次重建 `_to_repo/` 都会自动执行，并在自检中校验
「note 列不得再点名任何一方」。手改一遍然后被下次构建覆盖，是这类脱敏最常见的失效方式。

**包内 `gold_labels.csv` 保持完整版**（含人名归属，供 A 追溯）。
两份文件同名、内容不同，差异仅在此处——以本节的哈希为准。
仓库版哈希 `c62069d46e5aac0e`，包内完整版哈希 `461366a87a06bb17…`。

### 2.2 ⚠️ `evaluate_engine.py` 入库时改过两处

原脚本假定自己与数据同处一个目录（`HERE` 即仓库根），且两份逐人作答就在旁边。
搬到 `scripts/` 后这两条前提都不成立，故改：

1. **路径基准改为 `ROOT`**（`scripts/` 的上级），`data/` 下的一切由 `ROOT` 解析；
2. **B、C 作答改为显式外部输入**：新增 `--private-package <标注包目录>`
   （或环境变量 `PHARMACOLDOPS_ANNOTATION_PACKAGE`）。缺文件时给出一条
   说明原因与出路的错误，替换原来那句含混的「文件不完整」。

理由不是洁癖：那两份文件按 §1 **永不入库**，原写法使脚本在仓库里**必然跑不动**，
而 `agreement_stats.md` 开头写着「可复跑」——两者不能同时为真。
现在仓库副本可复跑，前提是手上有标注包。

> ⚠️ **顺带修正一处指纹错误**：原表把 `docs/annotation_findings_v1.md` 记为
> `67ca06f977ccbbd5`，但该文件在包内、暂存目录、仓库三处**字节一致**，
> 实际哈希均为 `6a3be07b2f1a67d1`；`67ca06f9…` 对不上任何现存文件，
> 应是 00:18 最后一次编辑之前算下的。已按实际值更正——否则本文件的自校验
> 会对一个**从未被改动过**的文件报假警报。

### 2.3 ⚠️ `agreement_stats.md` 入库后改过（2026-09-12）

原指纹 `fd4e709ee4129386` 是**首次入库时**的值。入库后该文件补了两处**文字说明**
（不改任何数字）：§1 记「为什么 0.80 在这批数据上不可达」与团队 κ 决策；
§5 标注第 4 条政策项仍悬置。指纹随之变为 `cf25aa8b5aea94b3`。

**为什么必须改本表而不是放任**：本表是自校验的基准。一旦文件被合法编辑而指纹不更新，
校验就会对一个**正确**的文件报假警报——而假警报会让人开始忽略真警报
（§3 记录的同一个教训：校验器本身也要被校验）。

> ⚠️ **规矩**：凡编辑本表 §2 列出的入库件，**必须同一提交内更新指纹**，
> 并在本文件留下改动说明。数字若也变了，需另行说明理由。

## 3. 泄露校验（可复跑）

入库件在生成时逐一验证：

1. **四个 `*工作台_*.html` 不得含 `S0xx`**——
   否则标注者能从源码认出被重测的原轮场景。实测 **0 处命中**。
2. **不得整列复现任一份作答**——
   比对 `disposition` / `gold_label` 列与 7 份原始作答的完整序列，无命中。
3. **`answer_template.csv` 必须全空**（57 行、已填 0 行）。

校验脚本：**`scripts/check_provenance.py`**（已入库，可复跑）。

```bash
python scripts/check_provenance.py                      # §2 指纹 + 上述 1、3 项
python scripts/check_provenance.py --private-package <标注包目录>   # 追加 §1 指纹 + 第 2 项
python scripts/check_provenance.py --selftest           # 先自证校验器会失败
```

> 📌 第 2 项比原来**加严了**：原口径只查「整列复现」，会漏掉「贴了半段」——
> 而半段足以让同一批标注者重测时认出答案。现在同时要求非 CSV 入库件里
> **不得出现 >= 8 条连续作答**（实测最长 1 条，阈值离实测很远）。
> 该检查**只施加于非 CSV 文件**：CSV 入库件本就合法持有 gold 列，而 gold 是
> 双方答案的合并——两人一致的连续段落必然与两人各自的序列重合，查了就是假警报。

> ⚠️ **第一版校验器有 bug**：它按**格式**识别作答文件
> （`^S0\d\d,(release|retest|…)`），而 `gold_labels.csv` 与 `answer_template.csv`
> 跟作答文件恰好同格式，于是产生两个**假警报**。
> 已改为**序列比对**。留下的教训：假警报会让人开始忽略真警报，
> 校验器本身也要被校验。

## 4. 未随仓库分发、但存在的文件

| 文件 | 为何不分发 |
|---|---|
| `仲裁工作台_A.html` | 含双方答案，供 A 裁决用 |
| `标注诊断报告_给A.md` | 旧版，含双方逐条答案 |
| `标注诊断报告_给A_v2_终版.md` | **含双方逐条答案**（全文列出「B 判什么 / C 判什么」）。仓库里的结论件是对应的 `docs/annotation_findings_v1.md` |
| `从哪里开始.md` | 包内封面，指向标注截止日，属包内材料 |

---

*本文件只登记指纹，不包含、也不指向任何一方的逐条判断。*
