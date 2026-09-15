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
**2026-09-15 扩展为 1 仓库 + 14 个接收点**（11 个公立医院站点 + 3 家私立医院），仍在 `M5_singapore_network_plan.md` 自定的「depot + 10~15」规模内。

- 演示仓库：Kuehne+Nagel Singapore Logistics Hub，10 Pioneer Crescent。
  [官方地址](https://home.kuehne-nagel.com/locations?query=singapore%2F1000)；
  [官方冷藏设施说明](https://www.kuehne-nagel.com/sg/services/warehousing/singapore-logistics-hub)。
- 公立医院站点（11）：SGH、NUH、KKH、TTSH、CGH、SKH、NTFGH、Alexandra、KTPH、Woodlands Hospital、Buangkok Green Medical Park。
  前 9 家的来源为[政府医院目录](https://www.sgdi.gov.sg/other-organisations/hospitals)；SGH 与 Woodlands Hospital 用该目录各自的条目
  （[sgh](https://www.sgdi.gov.sg/ministries/moh/others/sgh)、[wh](https://www.sgdi.gov.sg/ministries/moh/others/wh)）。
- 私立医院（3）：Mount Elizabeth Hospital、Mount Alvernia Hospital、Parkway East Hospital。
  **来源强度弱于公立**：不在政府目录里，`source_url` 用各自官网（Mount Alvernia 的域名取自 OSM 该医院的 `website` 标签 `mtalvernia.sg`）；
  官网对自动化抓取返回 403，故只在**域名层面**核实存在，未取得正文核实。加入理由见下一条。
- **选点理由（2026-09-15）**：先按「地理覆盖是否有空白」筛，再按地理编码是否干净决定。实测（Nominatim）：
  Parkway East 距最近节点约 5.3 km（Marine Parade 一带原本没有节点）✔；Mount Alvernia 约 2.5 km、Mount Elizabeth 约 1.4 km ✔。
  被**否决**的私立候选：Mount Elizabeth Novena（距 TTSH 仅 283 m）、Thomson Medical Centre（距 TTSH 732 m）、Farrer Park（距 KKH 835 m）——
  都太近，加进去只是同一片区域多几个点；Gleneagles 的查询结果落在 Napier Road 的一个出租车站（`geocoder type=taxi`），按下面的原则不用。
- **SGH 的决定被复核并改写（2026-09-15）**：首版记录「SGH 名称查询返回同名行政区域，故改选园区内的 NHCS」。复核后改为**直接用 SGH**，理由：
  ① SGH 在 SGDI 的 MOH 医院名单上，而 NHCS 是专科中心、不在该名单，用它代表 Outram 院区在口径上更站得住；
  ② 用不带 `dedupe` 的查询交叉核对，SGH 的医院实体坐标为 (1.27945, 103.83627)，与那个同名分区一致，且距 NHCS 仅约 107 m——
  即两者是同一个院区，不会把点位放到别处；③ 该节点的 snap 偏移 110 m，落在全表 45–295 m 的既有范围内。
  实现上**不放松全局校验**：建网脚本仍要求 customer 必须命中 `type=hospital` 且名称匹配，只在 `facilities.json` 里为这一个节点显式写
  `geocoder_accept: ["hospital","administrative"]`，原因与坐标核对过程随该节点的 `note` 一并进入 `network.json`。
  ⚠️ 代价要说清：该节点的 `geocoder_type` 在入库文件里是 `administrative` 而不是 `hospital`，是**已知且有记录**的例外。
- 同理，**Woodlands 节点改名**：原名 Woodlands Health 现在的首条查询结果是「Woodlands Health Campus」公交站（`type=bus_stop`），
  建网校验会拒绝；改用 SGDI 的官方名称 Woodlands Hospital（`type=hospital`、名称匹配）。
- 同理，**IMH 节点按院区命名**：OSM 里「Institute of Mental Health」这个名称只落在一个出租车站上（`type=taxi`），医院本体映射为
  Buangkok Green Medical Park（`type=hospital`）；IMH 的地址就在该院区（10 Buangkok View），故节点取院区实体并在此记录。
- 设施经纬度由 Nominatim 实际查询产生，保留查询串；映射至可互相到达的主路网最近节点，并记录偏移距离。
  偏移超过 1000 米即停止。点位代表设施附近道路，不等同已核验的货运入口。
- **模拟假设**：3 辆车，每辆容量 200 配送单位；每个接收点需求 30 单位；客户服务窗口 09:00–17:00，服务 15 分钟；仓库 08:00–18:00。
  单位不宣称为实际疫苗剂数。选择这些设施（含私立医院）不意味着其有真实业务关系、库存或发运记录。

## 道路与时间含义

从 [BBBike 发布的新加坡 OSM 文件](https://download.bbbike.org/osm/bbbike/Singapore/)筛选与 OSMnx 2.1 `drive` 一致的道路类型，再按新加坡行政边界裁剪并保留单行道。
先保留最大弱连通图，再将设施匹配到其中的最大强连通部分，确保配送与返仓均可达。
这会排除无法往返的单向支路；不声称覆盖所有私有道路、岛屿或货车专属通行限制。
每对设施固定选择最快路径，并对**同一组道路边**累加长度、行驶时间和几何；矩阵允许不对称。
OSMnx 以道路 maxspeed/同类道路速度估计缺失速度，最终兜底 30 km/h。
这是自由流估计，不包含实时拥堵、装卸入口延误或道路临时封闭。
不可达路径直接报错，禁止无穷值、NaN 或虚构直线距离替代。

原始图与 HTTP 缓存保存在 `data/processed/singapore_cache/`，不入 Git。
已生成并随代码提交的 `network.json` 保存 15×15 矩阵、设施、210 条有向设施间道路折线及来源元信息，支持全离线求解和导出。
`provenance` 记录 OSMnx 版本、建图日期、图规模、源文件与设施配置 SHA256、速度假设。
实际源文件 SHA256：`41350c08ebb8c777213d904e56ae32643ec005ff7750c36b852db047ddd3f84c`；
发布方 MD5 `93c87c18dc5f07d3618fe5df6bbc64eb` 已核对匹配。源发布页显示 XML 文件更新于 2026-09-06。
重新构建同一数据集应使用同一缓存；显式移走缓存再运行才会重新取图。

道路数据：© OpenStreetMap contributors，遵守 [ODbL / 署名要求](https://www.openstreetmap.org/copyright)。
D 展示 GeoJSON 或地图时须保留该署名，网络数据不因放进代码仓库而改变许可。

## 运行方式

已验证的本机解释器为 `.venv/bin/python`（Python 3.13.12），不是旧方案记录的 3.10。
团队 `cold-chain` Python 3.12 环境本机尚不存在，不声称已验证该环境。
建图额外依赖 `osmnx`（连带 `networkx` 等）；矩阵 loader、贪心和 GeoJSON 导出本身仅依赖标准库。
OR-Tools 求解需 `ortools`，测试需 `pytest`。

直接使用已提交的网络文件（无需下载地图）：

```bash
.venv/bin/python scripts/export_singapore_routes.py --time-limit 10
.venv/bin/python -m pytest -q
```

需要重新建图时，可使用已实跑成功的 OSM 文件方式：

```bash
.venv/bin/python -m pip install 'osmnx>=2.1,<3'
mkdir -p data/processed/singapore_cache
curl -fL --max-time 180 -o data/processed/singapore_cache/Singapore.osm.gz https://download.bbbike.org/osm/bbbike/Singapore/Singapore.osm.gz
.venv/bin/python scripts/build_singapore_network.py --osm-file data/processed/singapore_cache/Singapore.osm.gz
```

仅下载 OSM 文件及首次地理编码需要网络，之后可使用缓存。原始文件会定期更新，要精确复现请保留本次缓存与 SHA256。
不带 `--osm-file` 仍可走原有 Overpass 模式，但本次该服务限流，实际交付没有使用它。
本地 OSM 文件筛选两次流式扫描：只保留可驾车 way 及其引用节点，方向和简化仍由 OSMnx 处理；不新增虚构道路。

求解和导出不联网，无须在每个开发环境安装 OSMnx。导出目录：`data/processed/singapore/`，
包含 `greedy_routes` / `ortools_routes` 的 `.json` 排程和 `.geojson` 道路折线，均包含返仓段。
GeoJSON 使用 `[longitude, latitude]`，设施表使用 `lat` / `lon`，D 的 `loc.lng` 需在展示适配时映射。

## 验证

人工小矩阵仅用于测试方向、单位、等待、服务、返仓、非法输入及最快路径的一致性，不作为真实数据。
真实 network.json 不存在时仅真实数据集成测试跳过，其余测试必须通过。
每次共享算法变化需回归 6 个 Solomon 实例。真实示例的时间窗较宽，验收要求两算法均服务全部客户且零违规。

## 完成与验证记录（2026-09-10）

- **82 passed，0 skipped**，包括真实网络集成以及 6 个 Solomon 贪心实例回归。
- 可往返路网：23,815 个节点、45,557 条有向边；筛选前最大弱连通图为 24,270 节点、46,187 边。
- 15 个设施全部可达；匹配道路节点的偏移距离 45.0–295.1 米。矩阵全部有限，105 对设施的正反向距离均不同。
- 已实跑 `export_singapore_routes.py --time-limit 10`，生成两份道路 GeoJSON 与两份完整排程 JSON。

| 算法 | 车辆 | 服务客户 | 总距离 km | 合计路线时长 min | 违规/未服务 |
|---|---:|---:|---:|---:|---:|
| 贪心 | 2 | 10 | 142.6305 | 364.6972 | 0 / 0 |
| OR-Tools（10 秒） | 2 | 10 | 133.8073 | 357.5731 | 0 / 0 |

本次 OR-Tools 距离减少约 6.19%。合计路线时长是各车辆工作时长之和，不是整个车队完成配送的钟表耗时；限时搜索结果可能随运行环境变化。
PyPI / Nominatim 可用；已通过文件下载方式解决 Overpass 限流造成的缺口，无需再让用户手动补地图。
Vue 前端现已在右侧配送改派面板接入预计算路线，支持方案切换与站点排程查看。`/api/route` 仍未接入，温度和处置变化不重新求解路线。

## 前端演示数据

`frontend-vue/src/data/singaporeRoutes.json` 是由同一导出脚本生成的小型数据包，包含两方案的道路折线、排程与指标，不加载全岛原始图。
更新网络后运行一次：

```bash
.venv/bin/python scripts/export_singapore_routes.py --time-limit 10 --frontend-out frontend-vue/src/data/singaporeRoutes.json
```

Vue 右侧“配送重新规划”默认展示该算例，即使当前无需补发仍可浏览，并显示对应提示。
底图使用 OSM 公共瓦片；底图网络失败仍保留本地道路折线、设施点和排程。
旧 `frontend/` 静态页面保持原样，本次接线在推荐的 `frontend-vue/`。
