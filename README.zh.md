# dsh-chat-digest

[English](README.md) | 简体中文

[![npm 版本](https://img.shields.io/npm/v/dsh-chat-digest?style=flat)](https://www.npmjs.com/package/dsh-chat-digest)
[![CI](https://github.com/OverDustD7/dsh-chat-digest/actions/workflows/ci.yml/badge.svg?style=flat)](https://github.com/OverDustD7/dsh-chat-digest/actions/workflows/ci.yml)
[![Node](https://img.shields.io/badge/node-%3E%3D22.5-informational?style=flat)](#环境要求)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat)](LICENSE)

把聊天导出整理成一块面板：该做的、可以报名的、值得知道的，由一条常驻的 DSH 主 agent 会话读聊天、改写面板。

## 发布与维护状态

- 状态：维护中。
- 支持：Windows x64 上的 DSH 网页界面，DSH `>= 0.1.5-rc.1`，Node `>= 22.5`。
- 其他平台：CI 配置了 Windows 与 Linux 的核心探针；Linux、macOS 的实际宿主流程尚未验证。不提供独立托管服务或手机客户端。
- 本版为 **1.5.4**。

面板、一条常驻主 agent 会话（切换线路＝在同一个会话上换模型）、以及两者之间的 HTTP 契约，都由这个插件管。按定时，或者你点一下
面板顶部横条上的**「获取」**，那条会话就去读你的聊天，把条目挑出来发回来；每条都能直接链到原始文件或图片。核心不需要
取数管线：包内另附可选的微信/QQ 管线，也可以把聊天导出放进私人 inbox，或者通过 HTTP 喂条目。

## 环境要求

| 需要 | 为什么 | 没有它会怎样 |
|---|---|---|
| DSH `>= 0.1.5-rc.1` | 宿主 | — |
| Node `>= 22.5` | 加载器与浏览器半边 | — |
| 可用的 `pnpm` | `dsh plugin` 通过 pnpm 往 profile 里装 bundle | 装不进去，写不出 profile |
| **Windows** | 文件用 `cmd /c start` 打开，路径按 `\` 拼 | 面板与接口照常；`file:` 链接回落成下载 |
| 一条你在 DSH 里配好的模型线路 | 常驻会话跑在它上面 | 面板与手工回写照常；跑不了一轮 |
| `wxRoot` —— 你的微信附件根 | 解析 `file:` / `img:` 链接 | 默认允许 inbox 与 output；其他附件目录需通过 `fileRoots` 配置 |
| 可选的微信/QQ 采集器 | 自动读取本机聊天数据库 | 不配置也可以直接使用 inbox 导出与 HTTP 输入 |

## 安装

```sh
dsh plugin --profile {{PROFILE}} add dsh-chat-digest@1.5.4
```

`{{PROFILE}}` 是 DSH 网页界面背后的那个 profile（常见为 `web`）。安装本身已经把它写进 profile 的
`dsh.profile.bundles`，别再手工加一遍，否则加载器会报 `duplicate loader entry id`。然后重启 `dsh web`。

本地 checkout 一样：

```sh
dsh plugin --profile {{PROFILE}} add link:{{CHECKOUT_DIR}}
```

成功信号：`GET /chat-feed/api/state` 能返回 JSON，侧栏出现**聊天摘要**入口。

> 为什么要重启：宿主半边只在挂载时求值一次。`lib/ui.js` 与 `lib/right.js` 由本包自己用 HTTP 发出去
> （`Cache-Control: no-store`），改完**刷新页面**即可。

## 快速使用

不需要取数管线 —— 插件有一个**默认数据约定**：把聊天导出丢进主 agent 工作区下的 inbox，常驻会话会去读它。

1. 把聊天导出丢进 inbox —— 纯文本 / Markdown / JSON 都行（默认 `%USERPROFILE%\.dsh\dsh-chat-digest\inbox\`；
   确切路径看 `GET /chat-feed/api/state` 的 `inbox` 字段）。`examples/inbox/sample.txt` 是一份可以直接
   复制进去的小样例。
2. 点一次**「获取」**。常驻会话读取 inbox，面板上出现条目，每条都链回来源文件。
3. 怎么知道成了：按钮走 `探测中…` → `采集中…`，面板打开，条目出现。网关不通就闪红，采集指针与采集时间
   都不变。

面板里一条条目（示意）：

```text
一、待办
  · 10/08 前提交报名表 · 创新实践项目
      这是什么：面向大一的项目制课程，秋季学期开课
      怎么做：填表 → 导师签字 → 交教务
      注意：20 个名额，先到先得
      → 附件  报名表.docx          （点一下用系统默认应用打开）

二、机会与招募
  · 9/30 截止：校园开放数据挑战赛（可自由报名）
三、有用信息
  · 图书馆研讨间预约 9/28 开放（官方）
```

两个不启动采集轮的检查：

- `GET /chat-feed/api/state` —— 一份 JSON，含条目、面板来源、线路槽、采集游标、上下文窗口与阈值、
  最后一次错误。读它时如果线路会话槽缺失或版本落后，会**顺带创建/修复这些常驻会话槽**，
  所以它是一个可能初始化会话的状态读取，不是纯被动接口。
- `POST /chat-feed/api/collect` 带 `{"dry": true}` —— 返回手动轮**将要注入的那段提示词**、字数与所用游标。
  这个分支既不探线路也不触发轮次；同一接口带上 `route` 才会探测并触发，所以只想看提示词时用 dry 这个 body。

新装完是空的，直到你喂进条目或跑一轮为止 —— 这是预期的：管线是你的。想换成你自己的说法或自己的采集器？
把 `examples/local/` 复制到你自己的一个目录，用 `config.localDir` 指过去，改「数据从哪来」那一节。

## 配置、数据与权限

数据与权限摘要：

- 读取什么：你放进 inbox（或你自己的采集器写到的地方）的聊天导出；条目链到附件与图片时，`fileRoots`
  之下的那些文件；以及用于标注常驻会话名的 DSH 会话标题。插件自己**不解析**微信或 QQ 数据库，那一步由
  可选管线配合运行时里带的工具或你自己配置的外部工具完成。
- 存在哪里：`{{DSH_HOME}}/dsh-chat-digest/`，即包外的私人 profile。里面有 `state.json`、`panel.json`、
  `output/`、`knowledge/`、`archive/` 与你的管线配置。插件写的东西不落在包目录里。
- 发给谁：常驻会话读到的文本会发给**你在 DSH 里配置的那条模型线路**，因为就是那条会话在读。插件自己的
  出站请求只有你配置的网关探测地址（`probeUrl`），不发遥测。面板条目按**路径**引用附件；这些引用之后
  被怎么处理，取决于你给的提示词和工具 —— 你配置的可选工具（例如视觉那一步）可能读取文件内容并发给它
  所用的模型线路。插件核心自己不上传附件文件。
- 需要什么权限：`fileRoots` 之内的读权限；为 `file:` 链接打开系统默认应用（Windows 上 `cmd /c start`）；
  以及经由 DSH 宿主提供的 HTTP 端点（认证用的是宿主那套）。不需要管理员权限，不写注册表，
  自己不听端口。

每个配置键都可选，写在那一行的 `config` 里 —— 可以写在包自己的 `cordis.patch.yml`，但更好是写在
**你自己 profile 的 patch 层**（`$DSH_HOME/profiles/{{PROFILE}}/cordis.patch.yml`，它会赢）：

```yaml
- id: dsh-chat-digest
  config:
    localDir: '{{PRIVATE_PROFILE_DIR}}'               # 私人数据与常驻会话的工作区
    wxRoot: '{{WECHAT_ATTACHMENT_ROOT}}'
    routes:
      - id: 'free'
        label: 'Free'
        provider: 'your-provider'
        model: 'your-model'
        probeUrl: 'https://your-gateway/v1/models'
        ctxRatio: 0.75
      - id: 'paid'
        label: 'Paid'
        provider: 'your-other-provider'
        model: 'your-other-model'
        default: true
```

| 键 | 缺省 | 说明 |
|---|---|---|
| `bodyPath` | `{{PACKAGE_DIR}}/lib/host-body.txt` | 权威 Host 函数体；可用 `DSH_CHAT_FEED_BODY` 覆盖 |
| `stateDir` | `localDir`（＝私人 profile） | `state.json` 与 `panel.json` 的位置 |
| `agentCwd` | `localDir`（＝私人 profile） | 必须与 `localDir` 指向同一物理目录；通常无需配置 |
| `dshHome` | `$DSH_HOME`，否则 `%USERPROFILE%\.dsh` | 读会话标题用 |
| `agentPreset` | 空 | 建会话时带的 agent preset |
| `routes` | 一条通用线路 | `[{ id, label, provider?, model?, effort?, probeUrl?, ctxRatio?, default?, hint? }]`。两条线是设计形态；不配则只有一条不指定 provider/model 的线路，会话继承宿主默认 |
| `localDir` | `{{DSH_HOME}}/dsh-chat-digest` | **你的私人 profile 的物理目录**；见下 |
| `inboxDir` | `{{AGENT_CWD}}\inbox` | 内置提示词让 agent 去读的**默认数据来源**；`local/round.md` 里的 `{inbox}` 就是它，且它默认在 `fileRoots` 里 |
| `wxRoot` | **无缺省** | 微信附件根 —— 只有当附件在 inbox 与 `{{AGENT_CWD}}\output` 之外才需要 |
| `fileRoots` | 已配置的 wxRoot、私人 output 与 inbox（可覆盖） | 允许取字节 / 用默认应用打开的根（拒绝 `..`、根外绝对路径、UNC） 非空数组替换默认根；空数组沿用默认根。 |
| `pythonRuntime` | `legacy` | `legacy` 使用外置 Python。`bundled` 仅适用于自行装配好运行时的本地副本。该模式先校验 manifest，再初始化私人目录。运行时缺失或无效时挂载失败。 |
| `python` | 无 | 填写供宿主生成管线命令时使用的外置 Python 解释器。 |

### 私人 profile

你的私人东西 —— 提示词覆盖、私有配置、产物、知识库、归档、面板状态 —— 住在**插件自己的 profile 目录**：

```text
{{DSH_HOME}}/dsh-chat-digest/           缺省 = %USERPROFILE%\.dsh\dsh-chat-digest
    pipeline.yaml  pipeline.json      wxid / 数据库密钥 / 群名 / 各路径
    output/  knowledge/  archive/     产物 / 知识库 / 归档
    docs/  state.json  panel.json  profile.md
```

- `{{PACKAGE_DIR}}/local`、`{{PACKAGE_DIR}}/profile`、`agent/output` 和 `agent/docs/{knowledge,archive}` 是兼容旧路径的运行时
  联接。会话 cwd 与所有新写入都走私人目录的物理路径。
- 为什么不直接放包里：`dsh plugin add {{PACKAGE_DIR}}@{{VERSION}}` 会整体重建包目录，放里面的私人文件每次更新都没。
- 为什么不放别处：放 `~/.dsh` 下由 `~/.dsh/.gitignore` 的 `*` 规则忽略，仓库 `.gitignore` 与包的
  `files` 白名单也排掉 `local`/`profile`/`output`/`knowledge`/`archive`/`state` —— 三处都挡住，
  私人 profile 不会被上传。
- 新机器可直接安装：挂载时创建空的私人目录与兼容联接；示例聊天不会自动放进 inbox。

### 你自己的提示词

唤醒提示词与每轮指令的**本体在包里**：

| 放哪 | 放什么 |
|---|---|
| `{{PACKAGE_DIR}}/prompt/prompt.md` | 唤醒主 agent 的提示词 |
| `{{PACKAGE_DIR}}/prompt/round.md` | 每轮的指令（`{date}`/`{mode}`/`{since}`/`{agent}`/`{pkg}`/`{profile}`/`{py}`/`{work}` 会被替换） |

想改成你自己的说法：在**私人 profile** 放一份同名的 `prompt.md` / `round.md` 即覆盖。
加载顺序 = **私人 profile → `{{PACKAGE_DIR}}/prompt/` → 内置通用**。

`localDir` 的解析顺序：`config.localDir` → `$DSH_CHAT_FEED_LOCAL` → `{{DSH_HOME}}/dsh-chat-digest`。

## 升级与卸载

升级：

```sh
dsh plugin --profile {{PROFILE}} add dsh-chat-digest
```

然后重启 `dsh web`。私人 profile 从来不属于包，所以 `state.json`、`panel.json`、你的提示词与管线配置
都会在升级后留下。从把状态放在旧位置（`%LOCALAPPDATA%\chat-feed\`、更早的临时目录、
`%TEMP%\dsh-chat-digest\`）的版本升级上来时，这些位置只作为一次性迁移来源被读一次，读完原样留着；
`state.note` 里记着用的是哪一个。

从本地装配的 1.5.2 升级前，私下备份原插件包、profile 配置和数据。启用本版前，把插件配置的
`pythonRuntime` 改为 `legacy` 或删掉这项。用微信或 QQ 导入的，先按下节迁移外置工具。
`localDir` 和 `stateDir` 继续指向原来的私人目录。

回滚时重装上一个确切版本，并恢复与它配套的插件配置和管线配置。npm 版本用
`dsh plugin --profile {{PROFILE}} add dsh-chat-digest@{{PREVIOUS_VERSION}}`。
本地装配版用备份副本，执行 `dsh plugin --profile {{PROFILE}} add link:{{PREVIOUS_PACKAGE_DIR}}`。
重启后先检查 `/chat-feed/api/panel` 和一条已有条目，再恢复采集。

卸载：

```sh
dsh plugin --profile {{PROFILE}} remove dsh-chat-digest
```

然后重启。想连面板数据一起清掉，再手工删 `{{DSH_HOME}}\dsh-chat-digest\` —— 这一步刻意不自动做，
因为那目录是唯一一份。

## 已知限制与排错

宿主重启后，如果状态写入被拒且原常驻会话尚未加载，插件会核实会话身份，恢复它后按现有 DSH 策略重试一次。
写入仍被拒时，自动采集继续暂停。自动采集沿用 DSH 当前选中的模型，明确选择指定线路或模型时可以切换。


面板、条目 API 和 inbox 流程使用宿主的 Node.js。需要微信或 QQ 取数时，另外准备 Python 环境并安装
[`pipeline/requirements.txt`](pipeline/requirements.txt) 中的依赖。把插件配置和私人 `pipeline.yaml`
中的 `python` 指向同一个解释器，再把私人 YAML 的 `external_dir` 设为包外工具目录的绝对路径。
插件不会下载或安装这些工具。

| 导入步骤 | 相对 `external_dir` 的文件 |
|---|---|
| 微信数据库解密 | `WeChatDataAnalysis/src/wechat_decrypt_tool/wechat_decrypt.py` 及配套模块 |
| QQ 原始密钥解密 | `nt_msg_db_util/qq_decrypt_hex.py`，需另行准备兼容的本地适配器 |
| QQ 结构化导出 | `nt_msg_db_util/3.export.py` 及 `msgdb` 包 |

只使用来源可信、你有权使用的副本。已有私人 1.5.2 装配版的，可以把原包中的
`pipeline/qq_decrypt_hex.py` 移出作为本地适配器，保留源码和声明。适配器接收
`<key_hex> <source.db> <plain.db>`，上游 `1.decrypt.py` 不提供这个原始密钥接口。
替换旧包前先按表布置工具。换机时保留私人 profile，并重新设置本机解释器和工具路径。

微信工具缺失时，微信导入报告前置依赖错误。QQ 配置或工具缺失时，QQ 步骤标记降级或跳过，已有导出可继续读取。
面板和 inbox 可独立使用。

- 不带模型凭据，也不会选你 `routes` 之外的模型。
- 不做异地备份。想要就自己拷 `stateDir`。
- 只在 Windows 上验证过。

| 现象 | 多半是 |
|---|---|
| 面板一直空的 | 没人喂它。把条目 POST 到 `/chat-feed/api/items`，或者配好 `localDir` + 管线跑一轮 |
| 「获取」闪红 | 选中那条线的 `probeUrl` 没应答。采集指针与采集时间按设计就是不动 |
| 一轮结束不了 | 常驻会话还在干活，或某一轮异常结束 —— 插件会自动重试一次，并在 `state.note` 里写明。如果连会话状态都读不出来，连续探测失败或超过三小时后插件会自己复位，不会让面板一直挂在「采集中」 |
| 面板回落到内置三段 | `panel.json` 丢了或非法；`GET /chat-feed/api/panel` 会说明是哪一种。不会覆盖任何东西 |
| 条目指向的文件打不开 | 路径在 `fileRoots` 之外。把根加进去，或设 `wxRoot` |
| 升级后条目不见了 | 状态迁移会去读旧位置；`state.note` 里记着它用的是哪个来源 |

**状态**写在 `stateDir` 下：`state.json`（原子写 + 一份 `.bak`；解析失败时把坏件隔离成 `.corrupt-{{TIMESTAMP}}`）
与 `panel.json`。坏件从不删。

## 开发

| 路径 | 里面是什么 |
|---|---|
| `lib/plugin.js` | 加载器：读函数体、按 `new Function('CFG', text)(cfg)` 求值、调 `apply` |
| `lib/host-body.txt` | 权威宿主半边：线路、会话槽、面板、定时轮次、上下文轮换 |
| `lib/ui.js` | 浏览器半边：侧栏入口、面板外壳，以及面板顶部横条里的「获取 / 自动」 |
| `lib/right.js` | 面板的条目列表与富文本（`file:` / `img:` 链接） |
| `docs/` | 本机保留的工程笔记，不随公开仓库跟踪 |
| `test/` | 宿主探针与管线探针 |
| `tools/` | `check_host_body.py`（自检）与一次性诊断脚本 |

```sh
npm run check                            # 运行时 JS 的语法检查
npm run check:body                       # Host 函数体自检（必须打出 FAILS: 0）
npm run test:host                        # 宿主探针
npm run test:pipeline                    # 管线探针（只在本地跑）
```

一轮是怎么跑的：

```text
定时（每天一个固定时刻）或点「获取」
  → 选一条线路，先探它的网关                     （花模型步数之前）
  → 唤醒 / 复用那条线路的常驻主 agent 会话
  → 会话跑你自己的取数管线，去读你的聊天记录
  → 它把条目 POST 回来：  /chat-feed/api/items
  → 面板重建；附件变成 file: / img: 链接
  → 用 turn/end 计数收尾；采集指针前进
```

插件自己不解析你的聊天记录，也不会选你没配置的线路之外的模型。它负责的是：面板、常驻会话、轮次记账
（busy 记账、轮次异常结束时自动重试一次）、按线路阈值做上下文轮换、以及文件与附件端点。

本仓库对自己有两条纪律：

1. 改完 `lib/host-body.txt` 要把**新片段加进 `tools/check_host_body.py` 的清单**并重跑自检。运行中的宿主
   只在重新加载插件时才看到这类改动；重新加载是显式操作，不属于改源码这一步。
2. 探针**不许改被它检查的仓库**：管线探针在临时目录里跑 fixtures，自检的副本写到系统临时目录。
   断言"仓库是干净的"之前，先看 `git status --porcelain` 里的改动**是谁写的**。

`prepack` 依次跑 `check`、`test:host`、`test:portability` 与 `test:ui`，这些步骤依赖生命周期脚本启用；禁用脚本生成的候选仍须补齐适用检查后才可发布。
CI 在 Ubuntu 与 Windows 上、Node 24 下跑 `check`、`test:host` 与 `test:portability`。两个 Python 探针
**刻意只在本地跑**：它们是作者自己的量具，不是发布门禁。

## 反馈与安全报告

- 提问与问题：<https://github.com/OverDustD7/dsh-chat-digest/issues>
- 安全：本项目不提供私密报告渠道。别在公开 issue 里贴聊天内容、凭据、附件路径或其它敏感信息；
  说清问题类别与不含数据的复现方式即可。

## 许可证与第三方说明

本项目自有代码采用 MIT 许可，见 [LICENSE](LICENSE)。

npm 候选包提供插件和导入接口。Python 解释器、依赖包及导入工具需单独准备。

| 包外工具 | 用于核对接口的来源 | 上游许可 |
|---|---|---|
| 微信解密工具 | [LifeArchiveProject/WeChatDataAnalysis 的 36d1e54](https://github.com/LifeArchiveProject/WeChatDataAnalysis/tree/36d1e548172e9fb87f26d729403a058d13d92bca) | 所查版本有第三方声明，尚未找到覆盖解密器的项目许可 |
| QQ 导出工具及原始密钥适配器的上游 | [QQBackup/nt_msg_db_util 的 317024c](https://github.com/QQBackup/nt_msg_db_util/tree/317024ce2c5e3482fdf9f310a5a7159ab4927e34) | GPLv3，保留上游声明并遵守使用或分发副本时适用的条款 |
