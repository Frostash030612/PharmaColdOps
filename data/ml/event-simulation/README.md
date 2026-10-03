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
尚未训练／推广新模型，不改旧ML契约、原数据或运行案例，也不新增具体货量／仓库余额要求。
