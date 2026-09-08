# PharmaColdOps · ML 数据字典与审计（`data/ml/`）

> 本文件是**人工维护**的数据字典：每个数据集的来源、字段含义、标签语义、诚实说明与 ML 任务映射。
> 全量统计（缺失率 / 基数 / 数值范围 / 相关度 / 标签平衡）由
> `scripts/audit_datasets.py` 生成到 `data/processed/ml_audit_report.md`（不入库，可随时重跑）：
>
> ```bash
> .venv/Scripts/python.exe scripts/audit_datasets.py
> ```

---

## 0. 总览（先读这一段）

### 诚实结论：公开冷链数据几乎都是合成/仿真

本项目能拿到的**公开冷链数据本质上是仿真/合成数据**——真实药企的传感器与失效记录因商业敏感不公开。这不是缺陷，而是需要写进报告的事实。判定依据：

| 数据集 | 合成证据 |
|---|---|
| africa-cold-chain-iot | **自带 `is_synthetic` 列，100% = 1** |
| africa-synth-immunization… | 数据集名即 *synth* |
| electricsheepafrica/vaccine-cold-chain | Electric Sheep Africa 仿真项目 |
| cold-chain-silent-failure (Kaggle) | 高度疑似合成（见下「泄漏/真伪筛查」） |
| vaccine-distribution-temperature (Kaggle) | 字段形态高度规则化，疑似合成；**含真实地名**（Jharkhand/Pune/Delhi…） |

> **许可**：各数据集许可证见源页面，**提交前需逐一核实并写入报告附录**（目前不杜撰）。

### ML 任务 → 数据集映射（提案 §6.3 / §7.1）

| ML 任务 | 首选数据集 | 标签 | 备选 / 增强 |
|---|---|---|---|
| 风险预测（shipment 级二分类） | **cold-chain-silent-failure**（8,000） | `silent_failure` | africa-cold-chain-iot `label`（平衡 5k/5k，但全合成） |
| 温度超限异常检测 | vaccine-distribution-temperature（26,674） | 需派生（`out_of_bound_…>0` 等） | vaccine-cold-chain `temp_in_range_pct` 阈值化 |
| 质量风险分级 | africa-synth-immunization（3×10k） | `wasted` / `potency_compromised` | vaccine-cold-chain `wastage_rate_pct` |
| 根因诊断（多分类） | vaccine-cold-chain | `excursion_cause` / `wastage_cause_primary` | africa-synth `wastage_reason` |
| 与规则引擎对齐验证 | vaccine-cold-chain / africa-synth | `freeze_excursion_detected` 等 | demo 场景（`export_demo_data.py`） |

---

## 1. cold-chain-silent-failure（Kaggle，需 token）— 风险预测主数据集

- **文件**：`cold-chain-silent-failure/shipment-sensor-dataset.csv`
- **规模**：8,000 × 24 · 粒度：每批货（shipment）级传感器摘要 · 无重复 · 缺失极少
- **来源**：<https://www.kaggle.com/datasets/skarin/cold-chain-shipment-silent-failure-dataset>
- **模块**：风险预测 / 故障分类（W2 基线）

| 字段 | 类型 | 角色 | 含义 |
|---|---|---|---|
| `shipment_id` | str | id | 货批标识 |
| `transit_days` | num | feature | 运输天数（**与标签相关度最高 0.45**） |
| `door_opens` | num | feature | 开箱/开门次数（r≈0.39） |
| `temp_mean_c` / `temp_max_c` / `temp_min_c` / `temp_std_c` | num | feature | 温度均值/最高/最低/标准差（`temp_max` r≈0.44） |
| `temp_recovery_rate` | num | feature | 温度回落速率（0.8% 缺失） |
| `rh_mean` / `rh_std` / `rh_max` | num | feature | 相对湿度均值/标准差/最高（0–1；`rh_max` 4% 缺失） |
| `package_type` | int | feature | 包装类型码（疑似类别编码） |
| `product_volume_l` | num | feature | 货品体积（L） |
| `fill_ratio` | num | feature | 装载率 |
| `carrier_id` | int | feature | 承运商码 |
| `origin_zone` / `dest_zone` | int | feature | 起点/终点区域码 |
| `leg_count` | num | feature | 运输航段数 |
| `sensor_gap_hours` | num | feature | 传感器无数据时长 |
| `vibration_index` | num | feature | 振动指数 |
| `feature_x1` / `feature_x2` / `feature_x3` | num | feature ⚠️ | **匿名化/工程特征，无文档语义** |
| `silent_failure` | int | **label** | **1 = 静默失效**（未触发警报却失效）· 平衡度 1,574 / 8,000（**19.7% 正类，不平衡**） |

**泄漏/真伪筛查结论**（详表见审计报告）：
- 无重复行；`carrier_id`/`package_type`/`origin_zone` 与标签仅弱相关（<0.08），**无明显标识符泄漏**。
- 相关度集中在可解释字段（`transit_days`/`temp_max_c`/`door_opens`/`temp_std_c`）——特征故事成立。
- **真伪警示**：`feature_x1..x3` + 整数化的 zone/carrier/package + 完美无缺省，**高度符合 Kaggle 合成基准的特征**。报告需如实写「该数据集大概率由生成流程产出」，与「公开冷链数据多为合成」结论一致。
- 建模建议：SHAP 解释优先用可解释字段；`feature_x1..3` 语义不明，留作鲁棒性对照，勿当作「业务特征」讲。

---

## 2. vaccine-distribution-temperature（Kaggle，需 token）— 温度异常 / MKT 模拟

- **文件**：`vaccine-distribution-temperature/input_data.csv`
- **规模**：26,674 × 13 · 粒度：batch × 小时 传感器日志 · 30 batch / 12 地点
- **来源**：<https://www.kaggle.com/datasets/manankhanna0/vaccine-distribution-with-temperature-logging>
- **模块**：异常检测 / MKT 模拟；**demo 场景与 export_demo_data.py 的数据源**

| 字段 | 类型 | 角色 | 含义 |
|---|---|---|---|
| `Unnamed: 0` | int | drop | 空表头产生的行号，非数据 |
| `date` | datetime | feature | 采样时刻（`dd-mm-yyyy hh:mm`） |
| `batch_id` | str | id | 批次（30 个） |
| `location` | str | feature | 地点名（**真实地名**：Jharkhand / Pune / Delhi…12 个） |
| `current_hop` | str | feature | 流转环节（`source_hub` / `air_transit` / `dest_reefer_truck` / `dest_vaccine_storage_unit` / **`dest_discarded_vaccine_storage_unit`** / `immunization_site`…） |
| `external_storage` | str | feature | 外部仓储类型 |
| `thermal_shipper_temp_reading` | num | feature | **冷链温度读数 °C**（−71…15） |
| `room_temp_reading` | num | feature | 环境温度 °C |
| `room_humidity_reading` | num | feature | 环境湿度 |
| `item_expiry_hours` | num | feature | 距过期小时数（负值 = 已过期） |
| `ultra_low_temperature_freezer_hours` | num | feature | 累计超低温冷冻时长 |
| `out_of_bound_temperature_hours` | num | feature/派生标签 | **累计超限小时数**（19% 行 > 0） |
| `refrigeration_temperature_hours` | num | feature | 累计冷藏时长 |

**标签派生候选**（源数据无标签，需在 spec 中定死）：
1. `out_of_bound_temperature_hours > 0` → 超限片段（异常检测标签，注意跨产品温区语义不同）。
2. 行级温度带外（参考 demo 的 `classify_product` 思路）→ 严格异常标签。
3. 观察性「报废」代理：`current_hop == dest_discarded_vaccine_storage_unit`（存在真实置入废弃单元的记录）——**仅作探索**，它是当前环节快照而非最终结局，需谨慎。

> 本数据集是**单点读数**：同一 batch 内多行温度构成时间序列，适合做 MKT/越限片段切分，也是 demo `real_data.js` 场景的真实来源。

---

## 3. electricsheepafrica/vaccine-cold-chain（Hugging Face）— 设施级、与规则引擎同域

- **文件**：三个 CSV，**同一 46 列 schema，按 `facility_level` 分片**，各 10,000 行：
  `vaccine_coldchain_district_hospital.csv` · `vaccine_coldchain_regional_vaccine_store.csv` · `vaccine_coldchain_rural_health_post.csv`
- **规模**：3 × 10,000 × 46 · 粒度：设施 × 月
- **来源**：<https://huggingface.co/datasets/electricsheepafrica/vaccine-cold-chain>（仿真项目）
- **模块**：设施/路线级异常、**根因诊断**；含 `freeze_sensitive` / `shake_test_done` 等与规则引擎**同名字段**（天然对齐点）

| 字段组 | 字段（→ 含义） |
|---|---|
| 标识 | `id`, `facility_id`（设施标识）· `facility_level`（固定值=本文件层级）· `year`, `month` |
| 设施/人员 | `region_type`（区域类型）· `has_epi_officer`（有免疫官员）· `cold_chain_staff_trained`（人员受过冷链培训） |
| 设备 | `equipment_type`（设备类型）· `equipment_age_years`（设备年限）· `equipment_functional`（可用）· `backup_power_available`（有备电）· `power_outage_hours_last_month`（月停电小时）· `monitoring_type` / `monitoring_device_present`（监测方式/有监测设备）· `temp_log_complete`（温度记录完整） |
| 疫苗属性 | `vaccine_name` · `doses_per_vial`（每瓶剂数）· `requires_reconstitution`（需复溶）· **`freeze_sensitive`（冻敏——规则引擎同字段）** · `heat_sensitive`（热敏）· `schedule`（免疫规划） |
| 温度/超限 | **`temp_in_range_pct`（月内达标 %）** · **`freeze_excursion_detected` / `heat_excursion_detected`（冻结/热超限标记）** · `min_temp_recorded_C` / `max_temp_recorded_C` · **`excursion_cause`（超限原因——根因候选标签）** |
| VVM / 处置 | `vvm_checked` / `vvm_stage`（疫苗瓶监测标签 VVM）· `shake_test_done`（**摇匀试验——规则引擎提及的现场筛查**）· `vaccines_discarded_freeze`（因冻结报废剂数）· `acceptable_wastage_pct` |
| 库存/用量 | `vaccine_in_stock`（有库存）· `stockout_days_last_month` · `doses_received_last_quarter` / `doses_administered_last_quarter` |
| 损耗 | `wastage_rate_pct`（损耗率）· `wastage_within_acceptable` · `doses_wasted_last_quarter` · **`wastage_cause_primary`（损耗主因——根因候选标签）** |
| 外联/报表 | `outreach_sessions_planned` / `_conducted`（计划/执行外联场次）· `children_missed_due_to_stockout` · `monthly_report_submitted` / `report_timely` |

**ML 用途**：与规则引擎的「冻敏 → 冻结即报废」规则同域；`excursion_cause` / `wastage_cause_primary` 是**根因诊断（W3）的多分类目标**；`temp_in_range_pct` 可做回归或阈值化二分类。

---

## 4. electricsheepafrica/africa-synth-immunization…（Hugging Face）— 质量标签

- **文件**：三个 CSV，**同 27 列 schema，按交付渠道分片**，各 10,000 行：
  `vaccine_epi.csv`（`scenario=national_epi_program`）· `vaccine_outreach.csv` · `vaccine_private.csv`
- **来源**：<https://huggingface.co/datasets/electricsheepafrica/africa-synth-immunization-vaccine-quality-cold-chain-all>
  （**名称即 *synth* —— 合成**）
- **模块**：质量标签 / 数据增强（`wasted` 为正类；分片间平衡度略异，见审计报告）

| 字段 | 角色 | 含义 |
|---|---|---|
| `record_id` | id | 记录标识 |
| `scenario` | meta | 场景（本数据集 3 文件各固定一类） |
| `year` · `setting` | meta | 年份；设施层级（`health_facility`/`district_store`/`regional_store`/`central_store`） |
| `vaccine` | feature | 疫苗（8 种：pentavalent/PCV/OPV_IPV/rotavirus/MR/BCG/COVID19/tetanus…） |
| `fridge_type` · `fridge_functional` | feature | 冰箱类型 / 可用 |
| `temperature_logger` · `cold_chain_trained` | feature | 有温度记录仪 / 人员受训 |
| `power_outage` | feature | 停电标记 |
| `cold_chain_break` · `heat_exposure` · `freeze_exposure` | feature | 冷链断裂 / 热暴露 / 冻暴露 |
| `max_temp_recorded` / `min_temp_recorded` | feature | 记录到的最高/最低温 |
| `vvm_checked` / `vvm_stage` | feature | 检查过 VVM / VVM 阶段 |
| `potency_compromised` | **label 候选** | 效力受损 |
| `expired` · `is_falsified` | feature | 过期 / 疑似假药 |
| `wasted` | **label 候选** | 报废（20.2% 正类）· **`wastage_reason`** 为主因标签 |
| `dose_administered` / `seroconversion_expected` | feature | 已接种剂数 / 预期血清转换 |
| `aefi_occurred` / `aefi_reported` | feature | 出现/报告接种后不良事件 |
| `knows_vvm` | feature | 知道 VVM |

**ML 用途**：数据增强 + 质量分级；与 vaccine-cold-chain 互为「根因」与「结果」两面的对照。

---

## 5. electricsheepafrica/africa-cold-chain-iot（Hugging Face）— 全合成、网络安全混合

- **文件**：`africa-cold-chain-iot/train-00000-of-00001.parquet`
- **规模**：10,000 × 31 · 粒度：事件（冷链网络安全攻击）
- **来源**：<https://huggingface.co/datasets/electricsheepafrica/africa-cold-chain-iot>
- **诚实标注**：**`is_synthetic` 列 = 100%**；`label` 严格平衡（5,000/5,000）、`detected` 2,034（20.3%）

| 字段组 | 字段（→ 含义） |
|---|---|
| 标识/来源 | `record_id` · `intelligence_source` / `intelligence_source_url`（情报来源）· `country` · `product_type` |
| 事件本体 | `attack_type`（攻击类型）· `doses_affected` · `vaccines_spoiled`（报废剂数）· `patient_harm_risk` · `financial_loss_usd` |
| 篡改标志 | `temp_data_tampered` / `temp_spike_faked` / `temp_drop_faked`（温度数据被伪造）· `location_spoofed` · `route_diverted` |
| 脆弱性 | `solar_powered` · `offline_operation` · `weak_auth` · `no_encryption` · `default_creds` · `remote_challenges` |
| 标签/评分 | `detected`（被检测到）· `label`（基准二分类，平衡）· **`is_synthetic`（=1）** · `supply_chain_integrity_score` · `attack_impact_score` · `high_doses_affected` · `financial_loss_high` |
| 品类 | `is_vaccine` / `is_medication` / `is_diagnostic` |

**ML 用途**：与主流程（温度处置）相距较远；`label` 平衡可用作二分类基线对照/数据增强参考。**讲故事需谨慎——攻击场景与 PharmaColdOps 的核心处置流不直接相关。**

---

## 6. ClarusC64/clinical-quad-coldchain…（Hugging Face）— 仅 10 行，不可训练

- **文件**：`train.csv` / `tester.csv`（各 **10 行 × 5**，是它**本来的大小**，非下载 bug）
- **来源**：<https://huggingface.co/datasets/ClarusC64/clinical-quad-coldchain-temp-excursion-transit-delay-potency-loss-v0.1>
- **字段**：`temp_excursion_duration_hr`（超限时长）· `transit_delay_hr`（运输延误）· `packaging_integrity_index` · `site_storage_variance_index` · `label_potency_loss`（效力损失，回归目标）
- **结论**：10 行无法训练；**仅作 schema 参考**或口头提及。价值在于其字段命名与规则引擎输入几乎同构（超限时长+包装完好性 → 效力损失）。

---

## 7. 对 ML 模块的实操结论（写代码前的要点）

1. **silent-failure 是唯一「开箱即训练」的二分类主数据**：干净、信号强、可解释字段多；先处理 19.7% 不平衡（类别权重 / PR-AUC 评估），并对 `feature_x1..3` 与业务字段分别出 SHAP。
2. **根因诊断的目标在 vaccine-cold-chain 的 `excursion_cause`/`wastage_cause_primary`**，比 silent-failure 更贴近规则引擎语义（同有 `freeze_sensitive`、`shake_test_done`）。
3. **vaccine-distribution 无标签**：派生标签方案须先写进 task spec（第 2 小节），避免各成员各自定义造成不可复现。
4. **全合成属性要贯穿报告**：真实（地名/温度读数来自 Kaggle）与仿真（合成生成器）的边界必须在 §7 数据描述里讲清——这正是本字典与 `PROGRESS.md`「公开冷链数据多为合成」一致的地方。
5. **许可证需在源页面逐一核实**后写入报告附录（目前不杜撰任何 license）。
