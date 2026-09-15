# M5 新加坡路网与前端交付记录

工作完成：2026-09-10；文档整理：2026-09-12。本文记录本次路由与前端工作，不涵盖团队后续的标注、知识图谱等改动。

## 已完成内容

- 整理并提交原有未提交的路线模型、贪心及 OR-Tools 基线代码，完成必要修正和回归。
- 为两种求解器接入独立的距离/时间回调，支持有向、不对称道路矩阵；保留 Solomon 默认欧氏距离行为。排程包含等待、服务及返仓。
- 完成新加坡网络构建、严格数据加载、离线求解及道路 GeoJSON 导出。距离、时间、折线来自同一条最快道路路径，保留单行道约束。
- Overpass 限流后，改用 BBBike 发布的真实 OSM 文件并核对校验值，已完成实际建图，原方案中“等待用户手动下载”的阻塞已解除。
- 将预计算结果接入 Vue 右侧“配送重新规划”：按车辆着色、切换贪心/OR-Tools、显示距离与站序、点击站点查看到达及服务时间；支持中英文。

## 数据与实测结果

输入为 1 个仓库（10 Pioneer Crescent）和 14 个接收点（11 个公立医院站点 + 3 家私立医院；2026-09-15 由 10 个扩至 14）。可往返道路核心包含 **23,825 个节点、45,586 条有向边**；交付文件包含 **15×15 距离/时间矩阵、210 条有向设施间道路折线**。这是全岛道路数据支持的固定配送算例，不是把新加坡所有道路逐条加载到前端。

道路及设施位置来自真实数据；业务参数为模拟：最多 3 辆车、每车容量 200 配送单位、每站需求 30、服务 15 分钟，客户窗口 09:00–17:00、仓库窗口 08:00–18:00。

| 2026-09-10 导出结果 | 贪心 | OR-Tools（10 秒） |
|---|---:|---:|
| 总距离（km） | 142.6305 | 133.8073 |
| 各车路线时长之和（min） | 364.6972 | 357.5731 |
| 使用车辆 | 2 | 2 |
| 服务站点 | 10/10 | 10/10 |
| 违规 / 未服务 | 0 / 0 | 0 / 0 |

本次距离减少 **6.19%**。时长是各车工作时长之和，不是车队完成任务的钟表耗时。OR-Tools 使用 Routing Solver + Guided Local Search，不是 CP-SAT；限时结果不保证全局最优，重跑可能不同。

## 交付文件索引

以下路径均相对仓库根目录。

| 路径 | 用途 |
|---|---|
| `data/optimisation/singapore/facilities.json` | 设施、来源与模拟业务配置 |
| `data/optimisation/singapore/network.json` | 已生成的道路矩阵、折线与来源记录，可离线使用 |
| `src/optimisation/` | 路线模型、两种求解器、网络加载及导出逻辑 |
| `scripts/build_singapore_network.py` | 在线或本地 OSM 文件建图入口 |
| `scripts/export_singapore_routes.py` | 求解并导出排程、GeoJSON 和可选前端数据 |
| `frontend-vue/src/data/singaporeRoutes.json` | 已提交的前端预计算数据 |
| `frontend-vue/src/components/ReroutePanel.vue`、`LeafletMap.vue` | 配送面板与真实道路地图 |
| `data/processed/singapore/` | 再生的两份排程 JSON、两份 GeoJSON；不纳入 Git |

原始 OSM、图及 HTTP 缓存位于 `data/processed/singapore_cache/`，不纳入 Git。来源、校验值、道路筛选和重建步骤见仓库内 `docs/singapore_network_assumptions.md`；原始设计保留于 `docs/M5_singapore_network_plan.md`，实际完成状态以本记录和运行说明为准。

## 复用方法

在仓库根目录、已有 Python 依赖的环境中更新路线与前端数据（无需重新下载地图）：

```bash
.venv/bin/python scripts/export_singapore_routes.py --time-limit 10 --frontend-out frontend-vue/src/data/singaporeRoutes.json
```

启动前端（已安装 Node.js 与 pnpm）：

```bash
cd frontend-vue
pnpm install --frozen-lockfile
pnpm dev
```

访问终端显示的本地地址，添加 `?lang=zh` 使用中文，在右侧配送面板查看。发布构建使用 `pnpm build`。本次没有部署公共网站。

## 已做验证与边界

- 9 月 10 日网络阶段：**82 passed、0 skipped**，包含真实网络集成和 6 个 Solomon 贪心实例回归；不代表所有大型 Solomon 实例都已由 OR-Tools 求解。
- 前端阶段：`pnpm build` 通过；浏览器检查了真实底图和道路、两方案切换、站点排程及中英文。本文整理未重跑测试，上述数字为当次记录，不是当前全仓库测试数。
- 当次实际 Python 为 `.venv` **3.13.12**；团队约定的 conda `cold-chain` Python 3.12 当次未验证。
- 前端展示固定预计算算例；温度、处置或补发数量变化不会重新求解。`/api/route` 仍返回 501，实时订单联动不在本次完成范围。旧 `frontend/` 未改造。
- 时间基于道路自由流速度估计，无实时拥堵；设施匹配道路偏移约 61.9–295.1 米，尚非核验后的装卸入口。未覆盖全部私有道路及货车专属限制。
- 离线可读取路线和排程；OSM 底图瓦片需联网，失败时保留本地路线。保留 OpenStreetMap 署名及 ODbL 要求。

## 提交追溯

| 提交 | 内容 |
|---|---|
| `2744544`、`3aa37d1` | 整理原有路线模型与求解基线 |
| `e64c85e` | 有向道路矩阵与离线导出 |
| `57fa807` | 初期环境及下载阻塞记录（阻塞后来已解决） |
| `565b3fd` | 真实 OSM 网络、实际结果与验证 |
| `1a262e7` | Vue 道路路线与排程展示 |

2026-09-12 整理时，本地 `main` 与已缓存的 `origin/main` 均为 `856bdf7`，上述提交已包含其中；本次未重新联网核验远端，也未执行推送。
