# 本地装配运行时 manifest

npm 包默认使用 `pythonRuntime: legacy`。配置外置解释器及工具见 [README](../README.zh.md)。
这个例子供已有自有运行时和工具、需要在私有副本使用 `pythonRuntime: bundled` 的维护者参考。

将 [示例](runtime-manifest.example.json) 按实际平台和架构调整，保存为本地副本的
`runtime/{{PLATFORM}}-{{ARCH}}/manifest.json`。schemaVersion 为整数 1，
`platform`、`arch` 必须与目录匹配。`python` 和可选 `tools` 里的入口使用相对该运行时根的
正斜杠路径。它们必须是普通文件，解析后仍在运行时目录内。

`node lib/runtime-check.mjs` 检查结构和边界。`found` 表示清单自洽，运行依赖和导入仍需另外核验。
显式选择 `bundled` 时，管线只从本地装配的运行时目录读取工具。把兼容的 QQ 原始密钥适配器和
导出工具分别放到示例的两个 QQ 入口。分发前单独核对每项资产的许可；npm 候选排除本地装配目录。
