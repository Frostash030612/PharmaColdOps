# Documentation index

PharmaColdOps — NUS-ISS IRS Practice Module, Project Group 41.

The report is the primary deliverable; this folder keeps the evidence behind it.
Start with the report, then use the sections below for design detail, evaluation
records and delivery notes.

## Start here

| Document | What it covers |
|---|---|
| [FINAL_REPORT_EN.md](FINAL_REPORT_EN.md) | Final report source (rendered to `PharmaColdOps-Group-Report.pdf`) |
| [user-manual-EN.md](user-manual-EN.md) · [用户手册.md](用户手册.md) | Installation and operator manual (EN / ZH) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Modules M1–M7, data flow and IRS technique mapping |
| [复现与本机部署.md](复现与本机部署.md) | Clean-environment reproduction and local Docker deployment |
| [最终交付与验收.md](最终交付与验收.md) | Delivery checklist, packaging and remaining human inputs |
| [DAILY_PLAN.md](DAILY_PLAN.md) | Week-by-week plan, roles and milestone history |

## Design and contracts

| Document | What it covers |
|---|---|
| [接口契约.md](接口契约.md) | API contract for every endpoint |
| [前端接线契约.md](前端接线契约.md) | Frontend-to-API wiring contract |
| [KG_SCHEMA_v1.md](KG_SCHEMA_v1.md) | Knowledge-graph entities and relations |
| [路径规划总逻辑方案.md](路径规划总逻辑方案.md) | Routing model, constraints and execution logic |
| [模拟订单生成器.md](模拟订单生成器.md) | Simulated order batches, seeds and windows |
| [独立加急与仓库停车规则.md](独立加急与仓库停车规则.md) | Urgent orders and legal day-end parking |
| [人工审核与有效处置.md](人工审核与有效处置.md) | Human review and effective disposition |
| [案例审计报告导出.md](案例审计报告导出.md) | Audit snapshot and content hash |
| [异常登记与离线沙箱.md](异常登记与离线沙箱.md) | Registration flow and read-only offline mode |
| [知识图谱可靠性与恢复.md](知识图谱可靠性与恢复.md) | Outbox, replay and graph recovery |
| [前后端技术栈与连接说明.md](前后端技术栈与连接说明.md) | Stack, connections and local ports |
| [前端地图底图说明.md](前端地图底图说明.md) | Map tiles, caching and offline limits |
| [singapore_network_assumptions.md](singapore_network_assumptions.md) | Singapore facilities, road data and assumptions |
| [供货点选址分析.md](供货点选址分析.md) | Supply-point selection analysis |
| [C_配送模块.md](C_配送模块.md) · [C_实现目标与交接.md](C_实现目标与交接.md) | Dispatch module handover notes |

## Evaluation

| Document | What it covers |
|---|---|
| [M2温度序列与MKT.md](M2温度序列与MKT.md) | Temperature intervals, MKT and missing data |
| [M3正式评估.md](M3正式评估.md) | Rule-engine evaluation (54/57, macro-F1, kappa) |
| [M4正式实验.md](M4正式实验.md) · [M4模型集成.md](M4模型集成.md) | Risk and cause models, calibration, SHAP |
| [M5正式评估.md](M5正式评估.md) · [M5_singapore_handover.md](M5_singapore_handover.md) · [M5_singapore_network_plan.md](M5_singapore_network_plan.md) | Routing benchmarks and Singapore instance |
| [M6独立评估.md](M6独立评估.md) · [M6评审收尾.md](M6评审收尾.md) · [M6协调人一键收尾.md](M6协调人一键收尾.md) | Human review protocol, closeout and coordinator workflow |
| [M6独立人工评估交接指南.md](M6独立人工评估交接指南.md) · [M6问答修复与新版本验收.md](M6问答修复与新版本验收.md) | Reviewer handoff and post-repair acceptance |
| [问答评测工具.md](问答评测工具.md) | QA evaluation tooling and safety |
| [阈值证据表_v1.md](阈值证据表_v1.md) | Threshold evidence and source audit |
| [annotation_rubric_v1.1.md](annotation_rubric_v1.1.md) · [annotation_rubric_v1.md](annotation_rubric_v1.md) · [annotation_findings_v1.md](annotation_findings_v1.md) · [annotation_split_v1.md](annotation_split_v1.md) | Annotation rubric, findings and split |
| [原因数据可学性审计.md](原因数据可学性审计.md) | Cause-data learnability audit |
| [事件级仿真数据.md](事件级仿真数据.md) · [事件时序模型v2评估.md](事件时序模型v2评估.md) · [事件级模型基线评估.md](事件级模型基线评估.md) · [事件模型拒判与审核门禁.md](事件模型拒判与审核门禁.md) | Event-level simulation and temporal models |
| [完整演示与端到端验收.md](完整演示与端到端验收.md) | End-to-end acceptance protocol |
| [前端与提案一致性核查.md](前端与提案一致性核查.md) | Frontend versus proposal consistency audit |

## Delivery and presentation

| Document | What it covers |
|---|---|
| [最终答辩问答.md](最终答辩问答.md) · [最终答辩分工与录制交接.md](最终答辩分工与录制交接.md) | Defence Q&A and recording handoff |
| [视频录制脚本与验收.md](视频录制脚本与验收.md) | Recording script and acceptance |
| [英文画面视频与真人配音交接.md](英文画面视频与真人配音交接.md) | Visual drafts and voice-over handoff |
| [宣传片-发布会风格版.md](宣传片-发布会风格版.md) · [宣传片-分镜与AI提示词.md](宣传片-分镜与AI提示词.md) | Promotion video design and shot prompts |
| [系统设计视频-发布会风格版.md](系统设计视频-发布会风格版.md) | System-design video design |
| [配音稿-两个视频.md](配音稿-两个视频.md) | Narration script and timing |
| [Cinematic-Concept-Film.md](Cinematic-Concept-Film.md) · [English-Code-Explainer.md](English-Code-Explainer.md) | Supplementary concept film and explainer |

## Deployment history

| Document | What it covers |
|---|---|
| [v2演示受控更新.md](v2演示受控更新.md) | Controlled v2 demonstration update |
| [v2只读shadow接口与演示入口.md](v2只读shadow接口与演示入口.md) | Read-only shadow API and UI entry |
| [实施交付记录_2026-09-12.md](实施交付记录_2026-09-12.md) | Delivery record for 12 September 2026 |

## Report evidence

| Document | What it covers |
|---|---|
| [report_case_study_20261023.md](report_case_study_20261023.md) | Case study used in the report |
| [figures/](figures/) | Report figures (architecture, UI, case flow, events) |
