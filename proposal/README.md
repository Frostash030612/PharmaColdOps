# Proposal 版本说明

本目录当前内容基准为 **2026-09-12 修订、2026-09-13 更新 §1 / §6.5 实现状态的中英文 Markdown、英文 SVG 配图和中文 Word 提案**，状态为待团队终审，尚未确认提交。

| 文件 | 状态 |
|---|---|
| [中文提案](PharmaColdOps-Proposal-ZH.md) | 已更新项目范围、实现状态、数据、实验、标注结果及计划；9/13 更新 §1 与 §6.5 的 KG/问答与事件触发路线集成状态 |
| [英文提案](PharmaColdOps-Proposal-EN.md) | 与中文内容同步（含 9/13 更新） |
| [英文配图目录](figures/en/) | 7 张 SVG 已与正文同步；原演示截图保留，图注已按 9/13 的端到端复核改写 |
| [正式 Word](PharmaColdOps_正式Proposal_4人版.docx) | 已于 2026-09-13 按中文 Markdown 重新生成（`scripts/build_proposal_docx.py`，零第三方依赖）；仍需团队补齐组号、成员信息并人工终审 |
| [提案 PPT](PharmaColdOps-Proposal-Presentation.pptx) | 旧版演示文稿，提交前需要同步范围、指标和未完成项 |
| [调整版 PPT](PharmaColdOps_tune.pptx) | 保留原文件，提交前需确认是否继续使用 |

本轮修订提案源稿、SVG 配图和中文 Word 提案，不改变程序行为、规则阈值、rubric 或 gold 标签。ML 和路线指标来自已有实验记录；39/57 的引擎与 gold 一致计数已直接运行当前引擎复核。更早的 ground-truth 设计文档保留为历史设计，已完成的标注结果以正文 §8.3 和其链接的统计材料为准。

正式提交前仍需补齐组号、成员姓名及学号或脱敏 ID，同步并检查 PPT，完成团队终审和提交记录。Word 已做结构检查和首页预览检查；当前环境缺少 LibreOffice/pdf2image，未完成全页 PNG 渲染检查。
