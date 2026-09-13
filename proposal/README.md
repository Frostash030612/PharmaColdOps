# Proposal 版本说明

本目录当前内容基准为 **2026-09-13 修订的中英文 Markdown、英文 SVG 配图和中文 Word 提案**，状态为待团队终审，尚未确认提交。

| 文件 | 状态 |
|---|---|
| [中文提案](PharmaColdOps-Proposal-ZH.md) | 已更新项目范围、实现状态、数据、实验、标注结果及计划 |
| [英文提案](PharmaColdOps-Proposal-EN.md) | 与中文内容同步 |
| [英文配图目录](figures/en/) | 7 张 SVG 已与正文同步；两张演示截图于 2026-09-13 在 Vue 前端（API 模式）重新截取，原图见 `figures/raw/` |
| [正式 Word（中）](PharmaColdOps_正式Proposal_4人版.docx) | 已按本次中文 Markdown 重新生成；组名、成员姓名及学号已填入；仍需人工终审 |
| [正式 Word（英）](PharmaColdOps-Proposal-EN.docx) | 按英文 Markdown 生成，内容与中文版对应；供人工修改 |
| [提案 PPT](PharmaColdOps-Proposal-Presentation.pptx) | 旧版演示文稿，提交前需要同步范围、指标和未完成项 |
| [调整版 PPT](PharmaColdOps_tune.pptx) | 保留原文件，提交前需确认是否继续使用 |

本轮修订提案源稿、SVG 配图和中文 Word 提案，不改变程序行为、规则阈值、rubric 或 gold 标签。本次修订把 9/12 之后落地的实现同步进正文与配图：`/api/route` 与 `/api/qa` 已是真实端点（不再标 501），订单驱动的补发求解与调度运行状态持久化已实现并通过测试，前端对已归档补发案例会实时取路线与图谱回答；仍缺的是前端调度界面与候选目的地池扩充。风险模型 §8.2 三行数字于 2026-09-13 用 `scripts/train_risk_full.py` 在 `requirements.txt` 记录的环境（seed 42）复跑得到，其中 LightGBM/XGBoost 的阈值与指标与原记录不同；原因实验（Top-1/Top-3/macro-F1）与新加坡路线结果仍为已有记录，本次未重跑。39/57 的引擎与 gold 一致计数已直接运行当前引擎复核。更早的 ground-truth 设计文档保留为历史设计，已完成的标注结果以正文 §8.3 和其链接的统计材料为准。

正式提交前仍需同步并检查 PPT、完成团队终审和提交记录。正文与两个 PPT 均以 A/B/C/D 表示职责，对照表见提案 §10.1（A Xu Wenzhe · B Zhu Jianyu · C Wang Lepeng · D Shen Ziyi），`PROGRESS.md` 分工表已同步姓名及 Git 提交身份。Word 已做结构检查和首页预览检查；当前环境缺少 LibreOffice/pdf2image，未完成全页 PNG 渲染检查。
