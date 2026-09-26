# agent 当前文档与工具索引

更新：2026-09-20。总入口：[CHAT-INTELLIGENCE.md](D:/Project/DSH/chat-feed/README.md)。
最新状态先看 [全量检查报告](D:/Project/DSH/chat-feed/docs/audit-2026-09-20/REPORT.md)，文件位置看 [结构说明](D:/Project/DSH/chat-feed/docs/audit-2026-09-20/FILE-STRUCTURE.md) / [逐文件登记](D:/Project/DSH/chat-feed/docs/audit-2026-09-20/FILE-REGISTRY.md)。

## 规范的用途

| 文件 | 用途 |
|---|---|
| [guidelines.md](docs/guidelines.md) | 用户原始要求及后续追加，25 条原则 |
| [output_format.md](docs/output_format.md) | 输出与验收口径；当前是持续列表，不是每天独立主稿 |
| [MAIN_AGENT_SPEC.md](docs/MAIN_AGENT_SPEC.md) | 主 agent 职责；数字与旧完成状态需核运行态 |
| [agent/WORKING.md](docs/agent/WORKING.md) | 操作手册与 HTTP 契约 |
| [WORKFLOW-AND-COST.md](docs/WORKFLOW-AND-COST.md) | 流程演进/历史成本；THU 0.9 等旧数值不作实时配置 |
| knowledge/ | 人物、群、风格、偏好、经验、公众号、收藏 |
| 信息列表.md | 面板镜像，不是独立主副本 |
| KNOWN_ISSUES / EVOLUTION / DEV_NOTES | 历史问题、决策与排障依据；不以单个状态符号判完成 |
| PLUGIN_BLUEPRINT / task_daily_template | 初始设计与历史流程背景；有用规则需对照后续变更 |

## 活的调用链与工具

日准备入口：[scripts/daily_prep.py](agent 根/scripts/daily_prep.py)，当前 21 步。
它调用 WX/QQ 解密、QQ 上游导出、extract_day、brief、公众号、timeline/articles/threads、units、官网文章、过筛、覆盖检查、收藏、作者、图片、视觉、会话元数据、URL 与容量扫描。

| 工作 | tools 下入口 |
|---|---|
| 初提与核对 | local_prepass.py、prepass_audit.py、anchor_read.py |
| 动作/机会兜漏 | hw_ledger_scan.py |
| 语料组织 | units_day.py、split_day.py、day_timeline.py、day_threads.py |
| 图片阅读 | vision_triage.py（已带 ctx 与 ocr_sure） |
| 面板编辑 | panel_append_items.py、panel_patch_text.py、panel_drop_items.py、panel_fmt.py |
| 交付与镜像 | export_day_items.py、export_list_mirror.py；前者仍有 A09 覆盖缺陷 |
| 知识库与收尾 | kb_append.py、mem_audit.py、round_finish.py |
| 诊断 | boot_check.py、wx_status.py、route_probe.py、check_corpus_coverage.py、check_step_count.py |

[docs/agent/cf_api.py](docs/agent/cf_api.py) 虽在 docs 下，却是活的 HTTP 客户端，不能当纯文档移动。
[scripts/find_attachments.py](agent 根/scripts/find_attachments.py) 有明确缺陷且未接 daily_prep；不能因文件存在声称附件线已通。

Python 使用 `D:\Project\DSH\agent\venv\Scripts\python.exe`。真实 output 数据、knowledge 和文档镜像本次都未移动；output 不在 git，需要独立备份策略。

## 历史与归档

本次归档 94 个历史补丁/备份/临时文件到 `agent/archive/2026-09-20/`。旧 scripts/archive、docs/archive 保留。根目录历史交接和 output/logs 中的排障脚本也保留；不自动把“未进 git”当作无用。

原版 INDEX：[历史副本](D:/Project/DSH/chat-feed/docs/audit-2026-09-20/previous-docs/agent-INDEX.md)。新需求、代码和验收结果请用检查报告 A01–A18 编号对齐，避免继续只堆“已修”的时间线。
