# PharmaColdOps

**🌏 Language / 语言:** [English](README.md) · **中文**

面向药品冷链温度偏移的**可解释决策支持原型**。当发生温度偏移时，PharmaColdOps 给出**可追溯的处置建议**（放行 / 隔离 / 复检 / 报废），并判断是否需要启动独立的补发改派流程；建议依据 WHO / EU GDP / ICH 原则与逐产品的稳定性假设。

---

## 🚀 只想看它跑起来？

**前置条件**：Docker Desktop 处于 **Linux 容器模式**、8080 端口空闲，以及一个 Python 3.12 环境。
若还没有虚拟环境，先执行下面这段（再跑后面的两条命令）：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-eval.lock.txt
```

```bash
.venv/bin/python scripts/configure_demo.py
docker compose --env-file deploy/demo.env -f deploy/compose.demo.yml up -d --build --wait --wait-timeout 180
```

**然后打开 → http://127.0.0.1:8080/?lang=zh**　（首次启动要 1–2 分钟，系统正在给图谱灌数据）

> **Windows 用户**把 `.venv/bin/python` 换成 `.venv\Scripts\python.exe`。
> 关闭时用同一条 `compose … down` 命令——**千万不要加 `-v`**，那会删掉数据卷。

### 60 秒演示路径

1. **🎲 生成今日批次（按日期）** → **确认发车** —— 建立当天的主线配送作业。
2. 在左侧列表选一个案例（如 `R01`，**与批次同产品**）→ **结案并查看处置方案** —— 得到带**规则路径与法规依据**的处置建议，以及几种改派方案的横向对比。
3. **⛶ 展开地图** —— 大图上**灰虚线＝改道前**、**红实线＝改道后**，并显示逐站送达进度。
4. **采用此方案** —— 提交你选定的方案；在你点它之前，不占用库存、不改派车辆。
5. 问知识图谱 *"这个案例为什么判报废？"* —— 答案带 WHO / EU GDP / ICH 出处；没有证据时会明确说没有。

**📖 完整说明（启动、每个面板、故障排查、适用边界）：[`docs/用户手册.md`](docs/用户手册.md)（中文用户手册）。**

**需求文件、提交件与演讲材料在 [`proposal/`](proposal/)。**

---

## 📄 交付物

| 交付物 | 位置 |
|---|---|
| **用户手册** | 中文：[`docs/用户手册.md`](docs/用户手册.md) · English: [`docs/user-manual-EN.md`](docs/user-manual-EN.md) |
| 报告 | *准备中* —— 现有证据与局限见 [`PROGRESS.md`](PROGRESS.md) |
| 演示视频（2 × 5 分钟） | *准备中* |
| 提案（2026-09-13 已提交） | [PharmaColdOps-Proposal-Group 41.pdf](proposal/PharmaColdOps-Proposal-Group%2041.pdf) |
| 提案源稿 | [英文](proposal/PharmaColdOps-Proposal-EN.md) · [中文](proposal/PharmaColdOps-Proposal-ZH.md) |
| 演示文稿 | [`proposal/PharmaColdOps .pptx`](proposal/PharmaColdOps%20.pptx) |
| 架构说明 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 进度与实测数字 | [`PROGRESS.md`](PROGRESS.md) |

> **范围声明**：使用模拟数据、仅绑定本机、无用户认证，**不是生产或合规系统**；规则阈值是工程假设。
> 详见[「这个系统不做什么」](docs/用户手册.md#7-这个系统不做什么重要)。

---

## 开发者文档

> 全部英文的开发者文档在 **[`README.md`](README.md)**（Modules 表、前后端与 `?api=` 双模式、数据布局、Quickstart、ML 实验、规则引擎口径、新加坡路网、测试基线）。下面只列中文侧常查的文档。

| 想知道 | 看 |
|---|---|
| 架构与技术分组 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 部署、备份、恢复与复现 | [复现与本机部署](docs/复现与本机部署.md) |
| 端到端验收与演示配方 | [完整演示与端到端验收](docs/完整演示与端到端验收.md) |
| 接口契约（跨成员字段） | [接口契约](docs/接口契约.md) |
| 前后端技术栈与连接 | [前后端技术栈与连接说明](docs/前后端技术栈与连接说明.md) |
| 配送模块（C） | [C_配送模块](docs/C_配送模块.md) |
| 前端与提案一致性核查 | [前端与提案一致性核查](docs/前端与提案一致性核查.md) |
| 常见测试与演示口径问题 | [PROGRESS.md](PROGRESS.md) 顶部各条 |

### 开发模式启动（不用 Docker）

```bash
# 后端（仓库根目录）
# macOS / Linux
.venv/bin/python -m uvicorn --app-dir src api.main:app --port 8000
# Windows PowerShell
.venv\Scripts\python.exe -m uvicorn --app-dir src api.main:app --port 8000

# 前端（另开终端）
cd frontend-vue
pnpm install --frozen-lockfile
pnpm dev
# 后端模式：http://localhost:5173/?api=http://127.0.0.1:8000&lang=zh
```

### ⚠️ 在本机 Windows 上跑测试的提醒

本机**中文 Windows** 上跑全量 `pytest` 会看到大量失败，**那不是代码坏了**：
`src/optimisation/case_action_guard.py` 使用 Unix 专有的 `fcntl` 文件锁，并**有意在非 Unix 平台 fail closed**。
团队的完整测试基线（见 [`PROGRESS.md`](PROGRESS.md)）是在 **Linux 容器**内取得的。
判断代码是否健康请用 Docker 的 Linux 环境。

---

## 团队

4 人小组（Project Group 41）。角色与分工见提案 §10；Git 提交身份对照见 [`PROGRESS.md`](PROGRESS.md) 分工表。
