# M5 新加坡道路网络：运行与数据说明

## 范围与接口

这是 C 的 W2 新加坡算例接入。A/B/D 模块及补发单、ReplanResult 字段不变。
现有 `SolomonInstance` / `Node` 复用；新加坡节点的 x/y 为 0 占位，必须把 loader 返回的 `leg_fn` 传给求解器。
`leg_fn(a,b)` 返回距离与行驶时间。Solomon 默认返回两份欧氏距离；新加坡返回公里、分钟。
路线总时长含等待、服务和返回仓库，从仓库最早出发时刻计量。

OR-Tools 实现是 **Routing Solver + Guided Local Search**，不是 CP-SAT，也不保证全局最优。
目标为行驶距离最小化，不承诺车辆数优先最少；未找到解时明确输出未服务客户。
距离、时间分别整数化：默认每公里 1000 单位（1 米），每分钟 1000 单位（0.06 秒）。
行驶时间向上取整以保守满足时间窗；最终用原始矩阵重新排程校验，边界可能比连续模型略保守。

## 真实位置与模拟业务

首版 `facilities.json` 为 1 仓库 + 10 医院，符合 DAILY_PLAN 9/23 的起步规模；20–50 节点是后续扩展目标。

- 演示仓库：Kuehne+Nagel Singapore Logistics Hub，10 Pioneer Crescent。
  [官方地址](https://home.kuehne-nagel.com/locations?query=singapore%2F1000)；
  [官方冷藏设施说明](https://www.kuehne-nagel.com/sg/services/warehousing/singapore-logistics-hub)。
- 医院：NHCS、NUH、KKH、TTSH、CGH、SKH、NTFGH、Alexandra、KTPH、Woodlands Health。
  [政府医院目录](https://www.sgdi.gov.sg/other-organisations/hospitals)。
- SGH 名称查询实际返回同名行政区域，首版改选 SGH 园区内的 NHCS，地址以[官方页面](https://www.nhcs.com.sg/patient-services/contact-us)为准；不会把错误地理编码当成医院。
- 设施经纬度由 Nominatim 实际查询产生，保留查询串；映射至最近驾车道路节点并记录偏移距离。
  偏移超过 1000 米即停止。点位代表设施附近道路，不等同已核验的货运入口。
- **模拟假设**：3 辆车，每辆容量 200 配送单位；每家医院需求 30 单位；客户服务窗口 09:00–17:00，服务 15 分钟；仓库 08:00–18:00。
  单位不宣称为实际疫苗剂数。选择这些设施不意味着其有真实业务关系、库存或发运记录。

## 道路与时间含义

获取 Singapore 边界内 OSM `drive` 路网的最大弱连通部分，保留单行道；不声称覆盖所有私有道路、岛屿或货车专属通行限制。
每对设施固定选择最快路径，并对**同一组道路边**累加长度、行驶时间和几何；矩阵允许不对称。
OSMnx 以道路 maxspeed/同类道路速度估计缺失速度，最终兜底 30 km/h。
这是自由流估计，不包含实时拥堵、装卸入口延误或道路临时封闭。
不可达路径直接报错，禁止无穷值、NaN 或虚构直线距离替代。

原始图与 HTTP 缓存保存在 `data/processed/singapore_cache/`，不入 Git。
生成的 `network.json` 保存矩阵、设施、所有设施间道路折线及来源元信息，可提交以支持全离线求解和导出。
`provenance` 记录 OSMnx 版本、建图日期、图规模、设施配置 SHA256、速度假设。
重新构建同一数据集应使用同一缓存；显式移走缓存再运行才会重新取图。

道路数据：© OpenStreetMap contributors，遵守 [ODbL / 署名要求](https://www.openstreetmap.org/copyright)。
D 展示 GeoJSON 或地图时须保留该署名，网络数据不因放进代码仓库而改变许可。

## 运行方式

已验证的本机解释器为 `.venv/bin/python`（Python 3.13.12），不是旧方案记录的 3.10。
团队 `cold-chain` Python 3.12 环境本机尚不存在，不声称已验证该环境。
建图额外依赖 `osmnx`（连带 `networkx` 等）；矩阵 loader、贪心和 GeoJSON 导出本身仅依赖标准库。
OR-Tools 求解需 `ortools`，测试需 `pytest`。

```bash
# 在仓库根目录，选择已装好依赖的解释器；本机：
.venv/bin/python -m pip install 'osmnx>=2.1,<3'
.venv/bin/python scripts/build_singapore_network.py
.venv/bin/python scripts/export_singapore_routes.py --time-limit 10
.venv/bin/python -m pytest -q
```

构建需要 Overpass/Nominatim 网络访问；不要根据旧环境记录预判必然不可联网。
如请求失败，保留缓存，在网络正常的终端重跑同一命令。失败不会替换已有 network.json。
求解和导出不联网，无须在每个开发环境安装 OSMnx。导出目录：`data/processed/singapore/`，
包含 `greedy_routes` / `ortools_routes` 的 `.json` 排程和 `.geojson` 道路折线，均包含返仓段。
GeoJSON 使用 `[longitude, latitude]`，设施表使用 `lat` / `lon`，D 的 `loc.lng` 需在展示适配时映射。

## 验证

人工小矩阵仅用于测试方向、单位、等待、服务、返仓、非法输入及最快路径的一致性，不作为真实数据。
真实 network.json 不存在时仅真实数据集成测试跳过，其余测试必须通过。
每次共享算法变化需回归 6 个 Solomon 实例。真实示例的时间窗较宽，验收要求两算法均服务全部客户且零违规。

## 本轮验证记录（2026-09-10）

- 已运行全部原有测试及新增矩阵测试：80 passed，真实网络集成 1 skipped（network.json 尚未生成）。
- 6 个 Solomon 贪心实例全部服务 100 客户、零违规。额外 2 秒 OR-Tools 探测中 R101、RC101 未找到解，已如实记入 `data/processed/routing_comparison.md`；这不是不可行证明，不宣称所有 OR-Tools 大实例已通过。
- PyPI 可用，已安装 OSMnx 2.1.1 / NetworkX 3.6.1。Nominatim 地点查询可用，SGH 同名区域误匹配已改选 NHCS。
- 完整 OSMnx 路网下载未完成：默认 Overpass 请求失败/重试，备用服务未返回图；直接节点 lambert 在等待 55 秒后仍返回 HTTP 429。已停止下载，未生成或提交 network.json，也没有真实道路 GeoJSON。
- 下一步在服务恢复或可联网的终端运行上述两条 build/export 命令，再跑全量测试。真实矩阵与路径生成后，才可提交 network.json 并向 D 交付真实路线。
- `--overpass-url` 支持指定可用公共实例；遵守该实例的限流要求，不通过并发重试绕过限流。
