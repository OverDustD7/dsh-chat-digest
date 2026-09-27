> **这是随包发布的通用模板**，不含任何部署方的私人内容。
> 你自己的完整版在私人文件夹（缺省 `%LOCALAPPDATA%\dsh-chat-digest\docs\`，即提示词里的 `{profile}\docs\`）——
> 部署方首装时它可能是空的，按 `INDEX.md` 的骨架自己长；包内这份只保证"换台机器也能跑起来"。

# 说明书索引（通用模板）

包内骨架（只读）：`lib/`（插件本体）、`pipeline/`（取数管线）、`agent/docs/`（本目录）、`agent/tools/`（工具箱）。

| 文件 | 讲什么 |
|---|---|
| `MAIN_AGENT_SPEC.md` | 主 agent 的职责与判断口径（成功标准、只做什么、三问口径） |
| `output_format.md` | 产出形态：一份持续增长的列表，不是每天一份文档 |
| `task_daily_template.md` | 派子代理的两轮任务书模板 |
| `guidelines.md` | 取数与提炼的经验、反例 |
| `WORKFLOW-AND-COST.md` | 一轮怎么走、成本怎么量 |
| `PLUGIN_BLUEPRINT.md` | 插件的结构与接口（给改代码的人看） |
| `agent/WORKING.md` | 操作手册模板（HTTP 契约、沙箱边界、每轮自检） |
| `agent/cf_api.py` | 读插件运行态的小工具（走本机 HTTP，不打印密钥） |

部署方自己的内容（用户画像、真实样本、历史笔记、知识库）**都放私人文件夹**，不要写进这个包。
