# `data/qa/` — M6 问答评估

2026-10-03：分开**派生契约检查**与**独立人工准确率／证据相关性**。前者完成，后者等待真实人工标注。
`intent_labels.csv` 的37条原FAQ关键词及空 expected_intent 保留，不用关键词路由自身给它填“gold”。
它不是独立采样的自然问句集，不能直接称作完整用户问答基准。

## 1. 安全的契约评测

```bash
.venv/bin/python scripts/evaluate_qa.py
.venv/bin/python scripts/evaluate_qa.py --limit 5
.venv/bin/python scripts/evaluate_qa.py --keep
```

默认自建临时Neo4j和独立SQLite／JSONL，只初始化自己创建的空图谱；报告位于新的临时评测目录。
默认清理本批案例、队列和归档，按自建不可变ID移除容器。`--keep` 只保留本批独立存储／容器供检查，
不是把测试案例写进原演示图谱。需要Docker及已安装Neo4j镜像；不要求启动或重建项目原图谱。
仅在明确配置了**已初始化专用测试图谱**时用 `--configured-test-graph`，不得指向生产／共享项目库。

退出0：全部检查与清理通过；1：检查失败；2：环境／运行／清理失败。数据库不可达不算通过。

57场景通过真实 `service.close_case`，466项检查覆盖：

| 检查 | 期望来源 | 结论边界 |
|---|---|---|
| 案例记录一致 | 本次真实结案记录 | 不是人工答案正确性 |
| 规则对应法规／SOP集合 | build_graph 静态映射 | 不是独立证据相关性 |
| 产品阈值同源 | rules_config.json | 不是验证阈值临床有效 |
| 无案例／不支持状态 | API契约 | 不是人工拒答适当率 |
| 跨案例证据隔离 | 同处置不同规则分组 | 防止共享Disposition串证据 |

设施关联由专项图谱单测及业务端到端验收覆盖，本脚本场景无设施列，不伪造地点。

## 2. 双人盲评与独立评分

```bash
LOKY_MAX_CPU_COUNT=1 .venv/bin/python scripts/evaluate_m6_independent.py prepare --output data/processed/m6-blind-new
```

53条测试输入=37条原关键词＋16条显式作者编写的中英文问句，含 cause_context／超范围／无案例。
脚本使用前端实际路由及FAQ回退、真实服务快照；无人工参考标签自动产生。
输出空的双人意图CSV、封存后使用的回答评分CSV、全部参考来源、第三人仲裁模板及私有预测指纹。
先盲标意图并封存，再评答案与证据，不能先展示模型预测。全部行须由不同的真实人员填写，分歧须第三人仲裁。
六类为 why_disposition／audit_chain／product_requirements／cause_context／disposition_stats／unsupported；
有歧义用 ambiguous＋acceptable_intents，不把裸关键词强塞进单标签。

完整协议、实测计时、文件路径、评分命令与尚缺的人工输入见 [M6独立评估](../../docs/M6独立评估.md)。
本轮盲评包在 `data/processed/m6-blind-20261003-v3/`，生成物不入库；在真实标注完成前，准确率保持不可用。
