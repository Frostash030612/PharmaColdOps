# v2只读shadow接口与演示输入入口

2026-10-04。接续[时序v2实验](事件时序模型v2评估.md)，完成独立运行契约、公开样本打包与前端登记／历史入口。
**代码与隔离验收已完成；当前8080演示服务没有重建、切换或启用v2。**
上述为本轮接口交付时状态；后续用户授权的 [受控更新](v2演示受控更新.md) 已实际完成，当前8080已启用独立shadow。
默认关闭，必须管理员显式开启；无论候选筛选通过、拒判、未配置或损坏，都不能自动放行、报废、补发或执行配送。
模型仍只学习未标定仿真机制，分数未校准，可能漏掉其他故障，不是因果／临床授权。

## 1. 独立契约与开关

`src/ml/event_v2_runtime.py`只读取管理员本地可信bundle，要求：

- `EVENT_V2_SHADOW_ENABLED=1`，并设置 `EVENT_V2_SHADOW_DIR`；只有目录、0／true／yes均不启用。
- bundle版本 `event-v2-shadow-bundle-v1`，特征版本 `event-temporal-study-v2`，111项精确输入／11标签顺序。
- model、policy、演示样本SHA核对，sklearn版本、模型实际输入／类别匹配；缓存按内容哈希，不靠mtime掩盖变更。
- `shadow_only=true`、`review_required=true`、`automatic_actions_allowed=false`，证据／语义守卫维持原规范。

哈希不是签名／管理员身份认证，不能装载用户上传的pickle。HTTP不接受model_path、features、scores、label或开关指令。
不存在API启用接口；查询参数不能启用模型。不替换 `ML_MODEL_DIR` 或v1的 `EVENT_GATE_DIR`，失败不回退另一版本猜分数。

| 接口 | 行为 |
|---|---|
| GET `/api/ml/event/v2/info` | disabled／unavailable／shadow_ready及版本／哈希／111项契约；不登记、不训练 |
| GET `/api/ml/event/v2/samples` | 已评估批次的公开观测，仅sample_id／role／observation；禁用／不可用503，无假样本 |
| POST `/api/ml/event/v2/assess` | `{observation:...}`，服务器提取111项并推理，返回候选／拒判／版本以及同源M2序列与分析；只读 |

输入仍用v1的14个公开观测通道，不能携带隐藏计划／机理或未来区间；校验有限数值、1440条以内、计划／前缀与采样节奏。
NaN／Inf、隐藏字段、产品／温度错配返回安全422，不回显整段异常输入导致500。

## 2. 冻结研究产物打包，不重新训练

```bash
LOKY_MAX_CPU_COUNT=1 .venv/bin/python scripts/package_event_v2_shadow.py \
  --study data/processed/event-v2-20261004 \
  --output data/processed/event-v2-shadow-new
```

必须新目录、不能放进原study；核对complete report、冻结选择／协议、数据manifest和选中mixed_temporal模型SHA，
只有原验证策略qualified且enabled才打包，不能放宽门槛或重选算法来让包“可用”。
三文件：model.joblib、metadata.json、demo_samples.json；约4.45MB，生成物不入Git。
五个测试角色按文件原顺序，**每产品取首个公开观测**，共20样本；不读labels.private、不按预测是否正确／支持挑样本。
样本已经被上一轮评估过，本轮重放是功能展示，不能报成新的未见准确率或此订单的实车读数。
实际包 `data/processed/event-v2-shadow-20261004/`：

- 模型ID：`event-temporal-v2-1b4fdd70474f`，模型SHA与原研究完全一致 `1b4fdd70474f604f0c88345cd5584365c960ce4c20ab94b342f8da1358c9eb42`。
- 策略SHA：`8e7d79052d5934b0a732938989dd4e7c25af3cae409474f667ee7771472d0ab9`。
- 原研究选择SHA：`61149d489520e23da0951c183b493ad22ad9efef90feec3e29ff8acfdd807d33`。
- 公开样本SHA：`0f2855d1acf4afcfb5bfc5f5de3309448a6fbcb0856fa839471e3b6af7ab8552`。

## 3. 前端入口与不可绕过的审核

更新后的API模式页面，在“+”新异常登记里显示 **事件模型v2 · 只读shadow**：

1. 检查开关并加载公开演示样本，按当前案例产品筛选；也可编辑公开JSON。
2. 只读预览服务器模型，显示候选／拒判、中文或英文机理名称、未校准分数、模型ID和哈希。
3. 编辑JSON／切产品／API地址／离线状态会使旧结果失效，异步旧回复不能覆盖新输入；登记在推理中受阻。
4. 显式点“采用完整观测并转人工登记”，同时绑定完整M2温度证据和 `event_v2_context`，标量温度／时长／MKT为null，不造假。
5. 切订单会解除已附加的v2证据；编辑M2证据若与v2不一致也解除v2绑定，需要重新预览／采用。
6. 归档后展示首次快照，没有重新推理按钮；旧记录没有v2结果，不自动补写。离线模式无模型控件／请求／假分数。

登记请求仍是 `/api/case_close`，新增可选 `event_v2_context={observation:...}`，必须与案例产品、完整温度证据、来源／EA一致。
v1 `event_context` 与v2不能同时提供；没有v2字段时旧指纹保持不变。
登记摘要包含全部公开观测：即使只改辅助通道，也不能冒用旧registration_id；重试返回首次登记快照，不因模型更新重算。
保存 `event_v2_context` 与 `event_v2_assessment`（含模型／策略／来源／观测／特征哈希），完整审计JSON保留来源，HTML摘要不重复原通道日志。

**候选通过也必须审核**：服务器强制pending投影、effective_disposition=null，既有送达／提速／补发／处理／结案守卫照常阻断。
只有人工结论写入独立审核历史后才成为有效处置依据；原始模型／规则／输入不变，执行后锁定规则不变。
人工身份仍为演示自报姓名，不是认证签名、真实药品处置授权或自动训练gold。
观测与案例的相等校验仅证明一致性，不认证传感器、实体订单来源或业务数据真实性。

## 4. 受控本机试用方式（本轮未部署到现有8080）

现有 `deploy/compose.demo.yml` 没有自动挂载v2实验文件或传递启用开关，本轮不编辑demo.env、不重建运行镜像。
管理员后续授权时，须在独立实例或明确安排的演示更新中配置可信**只读bundle**和开关；不要整包暴露私有标签／实验数据。
本机源码方式可按以下结构，先准备**专属新空图谱**并仅在该库初始化静态数据（见[复现规范](复现与本机部署.md)）：

```bash
pnpm --dir frontend-vue build
# NEO4J_*必须指向专属测试图谱，切勿使用原案例／演示图谱做验收。
NEO4J_URI=bolt://127.0.0.1:17687 NEO4J_USER=neo4j NEO4J_PASSWORD=pharmacoldops \
KG_SYNC_ENABLED=0 LOKY_MAX_CPU_COUNT=1 \
EVENT_V2_SHADOW_ENABLED=1 EVENT_V2_SHADOW_DIR="$(pwd)/data/processed/event-v2-shadow-20261004" \
DATABASE_URL="$(pwd)/data/processed/v2-preview-new/cases.sqlite3" \
CASE_RUNS_FILE="$(pwd)/data/processed/v2-preview-new/runs.jsonl" \
FRONTEND_DIST="$(pwd)/frontend-vue/dist" \
.venv/bin/python -m uvicorn --app-dir src api.main:app --host 127.0.0.1 --port 18080
```

浏览 `http://127.0.0.1:18080/?lang=zh&api=http%3A%2F%2F127.0.0.1%3A18080`。
普通静态构建默认不连接API；同源部署可通过原 `VITE_API_BASE=same-origin` 构建约定，显式 `?api=`仍可转离线。
上述口令只是一次性测试图谱例子，不是部署密码；数据目录须新建／隔离，不要复用原audit数据库。

## 5. 本轮验收

新增21项后端专项通过；独占临时图谱完整回归 **867 passed／0 skipped／6 warnings**（既有SWIG／SHAP提示）。
Node五组检查通过：v2采用／完整温度绑定／不可变载荷／缓存身份／双语，加既有M2、M4、登记恢复、审核守卫。
Vite生产构建通过，保留既有大chunk>500kB提示，未掩盖或靠阈值配置消警告。

按Playwright技能用CLI在独立18080服务／新SQL与新图谱真实操作，两分支均passed：

- `test_nominal-0002` 拒判；编辑后结果失效，完整观测登记待审，人工放行生效。
- `test_scenario-0005` 候选筛选通过；同样待审，不给自动处置／配送授权。
- 两者重载后保存模型／观测快照未变，历史无重推理按钮，离线请求0、组件pageerror0。
- 初次脚本因审核按钮名称不匹配超时，读取真实DOM后修正并重跑；不是产品审核失败。

只读重放20公开样本中1个candidate_only、19个abstained，未拿它们改模型／门槛，不用比例冒充性能评价。
截图位于 `output/playwright/event-v2-shadow-20261004/`（忽略产物）；实际面板视觉检查通过。
浏览器控制台仍有测试环境缺失的本地地图瓦片404和未建配送作业 `/api/dispatch/active` 的预期404；
地图有既有备用底图，模型／登记路径无组件异常。这些日志不写成“控制台0错误”。
隔离18080进程和专属浏览器会话已停止，临时图谱／临时卷已清理（不保留该测试图谱；可重新生成）。
测试SQL／JSONL与截图保留为忽略的本地验收产物，不混入业务库或Git。
原案例图谱保持停止，当前8080双服务healthy、health=ok；原SQL／JSONL与两个线上模型／元数据SHA前后不变。
代码／测试／说明按约定本地commit，不push，实验包／案例／截图不入Git。

下一步是明确安排现有本机演示的受控更新／shadow开关配置；这需要独立决定是否重建重启及挂载新包。
模型多故障遗漏、热缓冲和极端压力问题仍在，演示接入不等于性能问题已经解决。
