> **这是随包发布的通用模板**，不含任何部署方的私人内容。
> 你自己的完整版在私人文件夹（缺省 `%LOCALAPPDATA%\dsh-chat-digest\docs\`，即提示词里的 `{profile}\docs\`）——
> 部署方首装时它可能是空的，按 `INDEX.md` 的骨架自己长；包内这份只保证"换台机器也能跑起来"。

# 插件蓝图（通用模板）

- 包本体＝DSH profile bundle：`lib/plugin.js`（加载器）、`lib/host-body.txt`（宿主半边）、`lib/ui.js` + `lib/right.js`（浏览器半边）、`pipeline/`（可选取数管线）、`examples/`；
- 部署方配置写在 DSH profile 的 `cordis.patch.yml` 里那一行 `config`；
- **私人文件（提示词/配置/产物/知识库/面板状态）在插件自己的私人文件夹里**（缺省 `%LOCALAPPDATA%\dsh-chat-digest`），包内不写任何本机路径；
- 包内三个位置（`agent/output`、`agent/docs/knowledge`、`agent/docs/archive`）是**运行时联接**，指到私人文件夹；更新重建包目录后由挂载时自动重建。
