# PharmaColdOps 项目进度记录

> 每次开发的变更汇总，供团队快速了解进展与注意事项。

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
