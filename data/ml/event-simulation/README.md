# 事件级仿真数据入口

这是项目自建的 `event-mechanism-simulation-v1`，与原3份设施月度CSV独立。
代码／规范入库，生成的数据不入本目录或Git；默认产物在 `data/processed/event-simulation-20261003/`。

```bash
LOKY_MAX_CPU_COUNT=1 .venv/bin/python scripts/generate_event_dataset.py --events 6000 --seed 42 --output data/processed/event-simulation-new
.venv/bin/python scripts/verify_event_dataset.py --dataset data/processed/event-simulation-new --report data/processed/event-simulation-new-validation.json
```

6,000事件，同一事件的温度／开门／电源／设备／进度日志与隐藏注入机理配对。
训练、验证、IID、未见设备、未见时序模板、参数偏移各有独立角色；歧义成员不跨角色。
`features.csv`只有33项允许观测特征，`index.csv`与`labels.private.jsonl`分离；不能将ID、角色、原因码、场景或种子入模。
保留正常、未知、多机理和观测等价对，缺测保持null／覆盖率，不填零。

完整机理定义、数据语义、字段隔离、留出政策与局限见 [事件级仿真数据规范](../../../docs/事件级仿真数据.md)。
这是模拟注入故障识别数据，不是药品报废／真实效价／厂家稳定性或人工独立gold。
后续离线基线已完成，见 [事件级模型基线评估](../../../docs/事件级模型基线评估.md)。
实验模型尚未推广到服务，不改旧ML契约、原数据或运行案例，也不新增具体货量／仓库余额要求。

```bash
LOKY_MAX_CPU_COUNT=1 .venv/bin/python scripts/evaluate_event_baselines.py --dataset data/processed/event-simulation-20261003 --output data/processed/event-baselines-new --bootstrap 300
```

训练拟合、验证选择、冻结后四角色分开评分；保留正常／未知／多故障／歧义分母。
误报与分布偏移问题尚未解决，不能把仿真候选分数作为放行／报废依据。

后续 [拒判与人工审核门禁](../../../docs/事件模型拒判与审核门禁.md) 已完成并用新seed批次验收；
当前候选质量不达预设门槛，策略全部转人工，默认不启用事件模型，不宣称零拒判错误或100%准确。

独立 [时序v2实验](../../../docs/事件时序模型v2评估.md)已有改善，混合训练和111项前缀统计不改v1物理／标签；
仍仅为研究产物，没有替换上述33项运行契约或默认启用。v2的部分候选门槛合格不等于多故障／真实业务已解决。

已有 [独立v2 shadow接口与演示入口](../../../docs/v2只读shadow接口与演示入口.md)，由管理员显式配置三文件包及开关，
默认关闭、全程人工确认；代码与隔离验收完成，不代表当前演示服务已经重建或启用。
