> **这是随包发布的通用模板**，不含任何部署方的私人内容。
> 你自己的完整版在私人文件夹（缺省 `%LOCALAPPDATA%\dsh-chat-digest\docs\`，即提示词里的 `{profile}\docs\`）——
> 部署方首装时它可能是空的，按 `INDEX.md` 的骨架自己长；包内这份只保证"换台机器也能跑起来"。

# 主 Agent 操作手册（通用模板）

> 部署方自己的完整手册在私人文件夹：`{profile}\docs\agent\WORKING.md`（这份模板只保证新机器能跑起来）。

## 一、你手上的东西
- 工作区：你的 cwd ＝ **私人文件夹**（提示词里的 `{work}`）；里面是配置、产物、知识库、面板状态；
- 只读骨架：包内 `{agent}`（说明书模板 + 工具箱 + 代码）——要改手册或工具，去仓库改，别在包里改；
- 工具：工具箱在 `{agent}\tools\`，管线在 `{pkg}\pipeline\`；
- 写边界：沙箱是 workspace-write，**只有你的工作区可写**，包外一律只读。

## 二、每轮先做的事
1. 跑自检：`python {agent}\tools\boot_check.py`（读面板状态、产物断档、写权限）；
2. 读面板现状与采集游标，再决定这一轮干什么；
3. 一轮里只做这一轮该做的事；看不到来源就如实说，不要编。

## 三、判活
- `GET /chat-feed/api/state` 会带 `collectDay` / `lastCollectAt` / `items` / `autoWhy`；
- 命令行直接打这个接口会 401（宿主自己的鉴权），要看运行态就读私人文件夹里的 `state.json`/`panel.json`。
