# 插件结构

`lib/plugin.js` 加载 `lib/host-body.txt`，挂载宿主接口；`lib/ui.js` 与 `lib/right.js` 提供面板。`prompt/`、`agent/docs/`、`agent/tools/` 和 `pipeline/` 是随包发布的通用件。`{profile}` 是包外的私人目录，保存提示词覆盖、配置、知识库、状态和产物。运行时联接使包内工具的旧相对路径落到私人目录。

插件核心只依赖 DSH 与 Node 标准库。`pipeline/` 是可选的微信/QQ 取数实现，使用它时需按 `pipeline/requirements.txt` 安装 Python 包，并自行提供消息数据库与可选第三方工具。不接取数管线时，可把导出的文本放进私人 `inbox/`。

状态与面板接口见 README。部署、升级前检查打包文件清单和隐私门禁；不要把 `local/`、`profile/` 或其联接目标打进包。