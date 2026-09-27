# 常驻会话操作手册

这个文件随插件发布，是通用说明。部署方的群名、账号、真实会话、产物和个人决策放在私人 profile 的 `docs/agent/WORKING.md`；主 agent 应优先读取那份私人说明。

## 路径

- `{pkg}`：插件安装目录，只读代码、提示词和工具。
- `{agent}`：包内 `agent/`，包含通用说明与工具。
- `{profile}` / `{work}`：可写的私人 profile，包含 `inbox/`、`output/`、`knowledge/`、`archive/`、状态和私人配置。
- `{inbox}`：默认消息来源。没有输入时不生成演示条目。

## 每轮

1. 先读 `GET /chat-feed/api/state?slim=1`，核对当前会话、条目、游标、线路及最近错误。
2. 从私人 profile 的规则和真实来源取数；必要时用 `{pkg}/pipeline/` 与 `{agent}/tools/`。
3. 回原文核对每条行动、期限、附件是否真实存在。把不确定的信息标成待核实。
4. 用 `POST /chat-feed/api/items-patch` 增量写入；更改正文时保留用户的 `done` 状态。回读 `/state` 确认交付。
5. 用简短回报说明新增、更新、未完成及待用户判断的事项。自动轮不能等待交互提问。

## 故障定位

- `/state` 的 `lastError`、`saveOk`、`pendingCollect`、`busyFor` 是运行态证据。
- `state.json` 是私人 profile 的持久化副本；不要把包目录中的文件当成私人数据的权威位置。
- 不打印或提交完整凭据、原始聊天和带签名的 URL。HTTP 客户端位于 `docs/agent/cf_api.py`。