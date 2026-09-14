# `data/qa/` — 问答评估（M6 / W4-D）

本目录是 **问答质量评估集**：ARCHITECTURE 给 M6 定的验收指标是「问答准确率 + 证据可追溯覆盖率」，
proposal §12 把「问答评估集」列为交付物，排期 W4 写明「D：QA 评估」。这里放**输入语料与标注**；
评测脚本在 `scripts/evaluate_qa.py`，生成的报告写到 `data/processed/qa_eval_report.json`（生成物，按仓库约定不入库）。

## 1. 答案层评测（已实现，可立即跑）

```bash
# 需要 Neo4j：docker compose up -d
/opt/anaconda3/envs/cold-chain/bin/python -m src.knowledge_graph.build_graph   # 首次/重建
/opt/anaconda3/envs/cold-chain/bin/python scripts/evaluate_qa.py               # 跑 57 条场景
python scripts/evaluate_qa.py --limit 5      # 冒烟
python scripts/evaluate_qa.py --keep         # 把案例留在图里当演示数据
```

退出码：`0` 全通过 · `1` 有检查失败 · `2` 连不上图谱（**绝不把"连不上"算成通过**）。

**输入语料**：`../scenarios/scenarios.csv`（57 条人工双标场景，已入库）。每条经**真实**
`service.close_case` 结案，所以处置/规则号/主因都来自真实引擎——没有任何手写或预置答案。

**测什么（期望值全部来自 `qa.py` 之外的产物）**：

| 指标 | 期望值来源 | 说明 |
|---|---|---|
| 证据覆盖率 | `RULE_TO_REGULATIONS` / `RULE_TO_SOPS`（`build_graph` 静态映射） | 返回证据必须**恰好等于**引擎实际命中规则所映射的法规/SOP，多一条少一条都算失败 |
| 答案 ↔ 记录一致 | `close_case` 返回的真实记录 | 处置、原因、超限数值必须与该案例自己的记录一致 |
| 产品阈值一致 | `src/rule_engine/rules_config.json`（A 的配置） | 防止 KG 节点与配置悄悄漂移 |
| 四态正确 | 契约本身 | `no_case` / `unsupported` 必须如实报告 |
| **跨案例隔离** | 同处置、不同规则的案例分组 | 同处置案例**不得互相串证据**（2026-09-13 修掉的 `CITES` 作用域缺陷的护栏） |

**为什么不是循环验证**：期望值来自静态映射与 A 的配置，**不是** `qa.py` 的输出。这和规则引擎
gold 标注那次破除循环是同一个纪律（proposal §8.3）。

**不测什么（诚实边界）**：
- **意图分类准确率**：需要人工标注的问句集，见下节。
- **设施级证据**：`scenarios.csv` 没有设施列，所以设施/补发目的地证据由单元测试覆盖
  （`tests/test_kg_qa.py::test_audit_chain_surfaces_the_reshipment_destination`、
  `test_facility_edges_are_written_for_a_case_carrying_facility_ids`），不在这里假造设施。

## 2. 意图标注 `intent_labels.csv`（**待人工填写**）

`expected_intent` 列**故意留空**：意图分类的正确答案只能由人判断。用分类器自己的关键词表
（`frontend-vue/src/lib/qa.js` 的 `TYPE_KEYWORDS`）去打分是拿表评表，属于循环验证，不做。

- `question` 列是**既有语料**（从 `frontend-vue/src/i18n/{zh,en}.js` 的 `qa.answers[].kw` 逐条复制，
  未新编），`source` 列标明出处。
- 请在 `expected_intent` 填以下之一（与 `/api/qa` 契约一致）：

  ```
  why_disposition | audit_chain | product_requirements | cause_context | disposition_stats | unsupported
  ```

  例：`复验,zh,...,why_disposition,`、`gdp,en,...,product_requirements,`
- ⚠️ `cause_context`（「该原因最常见场景」）在既有 i18n 关键词表里**没有对应语料**，所以本模板不含该意图的问句——
  那需要**新写**问句（属作者性内容，不由脚本代写）。要覆盖它请自行增行，例如「这个原因最常见在哪」。
- 可自由增删行；标完告诉 D，即可跑出「意图分类准确率」这一个数，并把结果补进本 README 与报告。

> 目前**没有任何**准确率数字被写进提案或报告——因为标注尚未完成。这是有意为之。
