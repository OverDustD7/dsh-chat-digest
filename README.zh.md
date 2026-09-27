# dsh-chat-digest · 聊天摘要

[English](README.md) ｜ DeepSeek Harness 插件（profile bundle）

[![npm](https://img.shields.io/npm/v/dsh-chat-digest)](https://www.npmjs.com/package/dsh-chat-digest)
[![ci](https://github.com/OverDustD7/dsh-chat-digest/actions/workflows/ci.yml/badge.svg)](https://github.com/OverDustD7/dsh-chat-digest/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![node](https://img.shields.io/badge/node-%3E%3D22.5-informational)](https://nodejs.org)

**该做的事埋在群聊里。这个插件替你留一块面板，派一条常驻会话去读。**

它管三样东西：一块面板、一条常驻主 agent 会话、以及两者之间的 HTTP 契约。按定时——或者你点一下侧栏的
**「获取」**——那条会话就去读你的聊天记录，挑出「必须做的」「可以报名的」「值得知道的」，重写面板条目；
每条都能直接链到原始文件或图片。插件核心无需取数依赖；包内另附可选的微信/QQ 管线。
也可以把聊天导出放进私人 `inbox/`，或通过 HTTP 喂入条目。

## 装完三步走（全新安装）

**不需要取数管线** —— 插件有一个**默认数据约定**：把聊天导出丢进主 agent 工作区下的 `inbox\`，常驻会话会去读它。

1. 装上并重启（见下面「安装」）。把聊天导出丢进 inbox —— 纯文本 / Markdown / JSON 都行（默认
   `%USERPROFILE%\.dsh\dsh-chat-digest\inbox\`；确切路径看 `GET /chat-feed/api/state` 的 `inbox` 字段）。
   `examples/inbox/sample.txt` 是一份可以直接复制进去的小样例。
2. 点一次**「获取」**。常驻会话会创建并读取 inbox，面板上出现条目，每条都链回来源文件。

想换成你自己的说法或自己的采集器？把 `examples/local/` 复制到你自己的一个目录，用 `config.localDir` 指过去，
改「数据从哪来」那一节就行。

## 长什么样

面板里一条条目（示意）：

```
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

面板背后是**两条常驻会话，一条线路一条**。点「获取」会弹出你配置的那几条线路；选一条，先**探它的网关**，
通了才开始跑 —— 不通就不触发，采集指针也不动。

## 怎么工作

```
定时（每天一个固定时刻）或点「获取」
  → 选一条线路，先探它的网关                     （花模型步数之前）
  → 唤醒 / 复用那条线路的常驻主 agent 会话
  → 会话跑**你自己的**取数管线，去读你的聊天记录
  → 它把条目 POST 回来：  /chat-feed/api/items
  → 面板重建；附件变成 file: / img: 链接
  → 用 turn/end 计数收尾；采集指针前进
```

插件自己**不解析你的聊天记录**，也**不会选你没配置的线路之外的模型**。它负责的是：面板、常驻会话、
轮次记账（busy 记账、轮次异常结束时自动重试一次）、按线路阈值做上下文轮换、以及文件与附件端点。

## 要求

| 需要 | 为什么 | 没有它会怎样 |
|---|---|---|
| DSH `>= 0.1.5-rc.1` | 宿主 | — |
| Node `>= 22.5` | 加载器与浏览器半边 | — |
| **Windows** | 文件用 `cmd /c start` 打开，路径按 `\` 拼 | 面板与接口照常；`file:` 链接回落成下载 |
| 一条你在 DSH 里配好的模型线路 | 常驻会话跑在它上面 | 面板与手工回写照常；跑不了一轮 |
| `wxRoot` —— 你的微信附件根 | 解析 `file:` / `img:` 链接 | 只允许 `<agentCwd>\output` 之内 |
| 一条你自己的取数管线 | 读聊天、提炼条目 | 面板能用，但不会自己长东西 |

## 安装

```sh
dsh plugin --profile web add dsh-chat-digest
```

`web` 是 DSH 网页界面背后的那个 profile —— 你要改过名就换成自己的。**安装本身已经把它写进 profile 的
`dsh.profile.bundles`**，别再手工加一遍，否则加载器会报 `duplicate loader entry id`。然后**重启 `dsh web`**。

本地 checkout 一样：

```sh
dsh plugin --profile web add link:/path/to/dsh-chat-digest
```

> 为什么要重启：宿主半边只在挂载时求值一次。`lib/ui.js` 与 `lib/right.js` 由本包自己用 HTTP 发出去
> （`Cache-Control: no-store`），改完**刷新页面**即可。

## 怎么确认它在工作

- `GET /chat-feed/api/state` —— 一份 JSON，含全部自证字段：条目、面板来源、线路槽、采集游标、
  上下文窗口与阈值、最后一次错误。
- `POST /chat-feed/api/collect` 带 `{"dry": true}` —— 只组装这一轮的提示词并返回，**什么都不跑**，
  所以你能读到主 agent 究竟会被告知什么。
- 点侧栏**「获取」**：按钮走 `探测中…` → `采集中…`，面板自动打开；网关不通就闪红，
  采集指针与采集时间都不变。
- 盘上：私人 profile 内的 `state.json`（条目、游标、线路槽）与 `panel.json`。

新装完是空的，直到你喂进条目或跑一轮为止 —— 这是预期的：管线是你的。

## 配置

每个键都可选，写在那一行的 `config` 里 —— 可以写在包自己的 `cordis.patch.yml`，但更好是写在
**你自己 profile 的 patch 层**（`$DSH_HOME/profiles/<name>/cordis.patch.yml`，它会赢）：

```yaml
- id: dsh-chat-digest
  config:
    localDir: 'C:\path\to\your\private-profile'       # 私人数据与常驻会话的工作区
    wxRoot: 'C:\path\to\wechat\attachments'
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
| `bodyPath` | `<包>/lib/host-body.txt` | 权威 Host 函数体；可用 `DSH_CHAT_FEED_BODY` 覆盖 |
| `stateDir` | `localDir`（＝私人 profile） | `state.json` 与 `panel.json` 的位置 |
| `agentCwd` | `localDir`（＝私人 profile） | 必须与 `localDir` 指向同一物理目录；通常无需配置 |
| `dshHome` | `$DSH_HOME`，否则 `%USERPROFILE%\.dsh` | 读会话标题用 |
| `agentPreset` | 空 | 建会话时带的 agent preset |
| `routes` | 一条通用线路 | `[{ id, label, provider?, model?, effort?, probeUrl?, ctxRatio?, default?, hint? }]`。两条线是设计形态；不配则只有一条不指定 provider/model 的线路，会话继承宿主默认 |
| `localDir` | `<DSH_HOME>/dsh-chat-digest` | **你的私人 profile 的物理目录**；见下 |
| `inboxDir` | `<agentCwd>\inbox` | 内置提示词让 agent 去读的**默认数据来源**；`local/round.md` 里的 `{inbox}` 就是它，且它默认在 `fileRoots` 里 |
| `wxRoot` | **无缺省** | 微信附件根 —— 只有当附件在 inbox 与 `<agentCwd>\output` 之外才需要 |
| `fileRoots` | `[wxRoot, <agentCwd>\output]` | 允许取字节 / 用默认应用打开的根（拒绝 `..`、根外绝对路径、UNC） |

### 私人 profile（本地、不上传、更新不丢）

你的私人东西（提示词覆盖、私有配置、产物、知识库、归档、面板状态）住在**插件自己的 profile 目录**：

```
<DSH_HOME>/dsh-chat-digest/           缺省 = %USERPROFILE%\.dsh\dsh-chat-digest
    pipeline.yaml  pipeline.json      wxid / 数据库密钥 / 群名 / 各路径
    output/  knowledge/  archive/     产物 / 知识库 / 归档
    docs/  state.json  panel.json  profile.md
```

- `<包>/local`、`<包>/profile`、`agent/output` 和 `agent/docs/{knowledge,archive}` 是兼容旧路径的运行时联接。
  会话 cwd 与所有新代码的写入路径均使用**私人目录的物理路径**，不经这些联接写入。
- **为什么不直接放包里**：`dsh plugin add <包>@<版本>` 会**整体重建包目录**，放里面的私人文件每次更新都没。
- **为什么不放别处**：放 `~/.dsh` 下（本页默认位置）由 `~/.dsh/.gitignore` 的 `*` 规则忽略，
  仓库 `.gitignore` 与包的 `files` 白名单也排掉 `local`/`profile`/`output`/`knowledge`/`archive`/`state`
  —— 三处都挡住，**不会上传**。
- **新机器可直接安装**：挂载时创建空的私人目录及兼容联接；示例聊天不会自动放进 inbox。

### 你自己的提示词

唤醒提示词与每轮指令的**本体在包里**（通用件，随包发布、全文）：

| 放哪 | 放什么 |
|---|---|
| `<包>/prompt/prompt.md` | 唤醒主 agent 的提示词 |
| `<包>/prompt/round.md` | 每轮的指令（`{date}`/`{mode}`/`{since}`/`{agent}`/`{pkg}`/`{profile}`/`{py}`/`{work}` 会被替换） |

想改成你自己的说法：在**私人 profile** 放一份同名的 `prompt.md` / `round.md` 即覆盖。
加载顺序 = **私人 profile → `<包>/prompt/` → 内置通用**；三份都不在时退回内置的短提示词。

`localDir` 的解析顺序：`config.localDir` → `$DSH_CHAT_FEED_LOCAL` → `<DSH_HOME>/dsh-chat-digest`
（若无 DSH_HOME，则用用户目录下的 `.dsh`）。私人 profile 已被 `~/.dsh/.gitignore`、仓库 `.gitignore` 与包的 `files` 白名单三处排掉
—— 私人提示词与路径**永远不会**进仓库或 npm 包。

## 它写什么、花什么

- **状态**写在 `stateDir`（缺省＝私人 profile）下：`state.json`（原子写 + 一份 `.bak`；解析失败时
  把坏件隔离成 `.corrupt-<ts>`）与 `panel.json`。可选管线的产物写在私人 profile 的 `output/`；坏件**从不删**。
- 旧位置（`%LOCALAPPDATA%\chat-feed\`、`<旧临时目录>\`、`%TEMP%\dsh-chat-digest\`）只作为
  **一次性迁移来源**读一次，读完原样留着。
- 一轮的花费就是那条线路的 token：它读你的聊天、重写面板。除此之外没有别的开销，也没有遥测。
- 轮换**按线路**算 —— 会话窗口的 `ctxRatio`。作者这两条线用 `0.75`（200k 那条）与 `0.5`（1M 那条）。
- 本插件**不存任何凭据**：模型线路与密钥来自 DSH 自己的模型配置。

## 卸载

```sh
dsh plugin --profile web remove dsh-chat-digest
```

然后重启。想连面板数据一起清掉，就删 `%LOCALAPPDATA%\dsh-chat-digest\` —— 这步刻意留成手工的，
因为那是唯一一份。

## 出问题时

| 现象 | 多半是 |
|---|---|
| 面板一直空的 | 没人喂它。把条目 POST 到 `/chat-feed/api/items`，或者配好 `localDir` + 管线跑一轮 |
| 「获取」闪红 | 选中那条线的 `probeUrl` 没应答。采集指针与采集时间按设计就是不动 |
| 一轮结束不了 | 常驻会话还在干活，或某一轮异常结束 —— 插件会自动重试一次，并在 `state.note` 里写明 |
| 面板回落到内置三段 | `panel.json` 丢了或非法；`GET /chat-feed/api/panel` 会说明是哪一种。不会覆盖任何东西 |
| 条目指向的文件打不开 | 路径在 `fileRoots` 之外。把根加进去，或设 `wxRoot` |
| 升级后条目不见了 | 状态迁移会去读旧位置；`state.note` 里记着它用的是哪个来源 |

## 它**不**做什么

- **可选管线需要额外环境。** 包内 `pipeline/` 含微信/QQ 脚本；使用时需在私人 `pipeline.yaml`
  设置 `python`（已安装 `pipeline/requirements.txt` 的解释器）及 `external_dir`（微信解密器与 QQ 导出工具所在目录），
  并提供本机消息数据库。迁移到新电脑时需要重新配置这些本机路径。不用管线时，插件核心没有 npm 依赖。
- **不带模型凭据**，也不会选你 `routes` 之外的模型。
- **不做异地备份。** 想要就自己拷 `stateDir`。
- 只在 Windows 上验证过。

## 开发

布局：

| 路径 | 里面是什么 |
|---|---|
| `lib/plugin.js` | 加载器：读函数体、按 `new Function('CFG', text)(cfg)` 求值、调 `apply` |
| `lib/host-body.txt` | 权威宿主半边：线路、会话槽、面板、定时轮次、上下文轮换 |
| `lib/ui.js` | 浏览器半边：侧栏入口、「获取」下拉、面板外壳 |
| `lib/right.js` | 面板的条目列表与富文本（`file:` / `img:` 链接） |
| `docs/` | `INDEX.md`、`STATUS.md`（改动史 —— 用 grep 定位）、`COLD-START-ENGINEERING.md`、`ARCHITECTURE.md`、`audit-2026-09-20/` |
| `test/` | 23 条宿主探针 + 6 条管线探针 |
| `tools/` | `check_host_body.py`（自检）与一次性诊断脚本 |

```sh
npm run check                            # 三个运行时 JS 的语法检查
npm run check:body                       # Host 函数体自检（必须打出 FAILS: 0）
npm run test:host                        # 23 条宿主探针
npm run test:pipeline                    # 6 条管线探针
```

本仓库对自己有两条纪律：

1. 改完 `lib/host-body.txt` **必须重启 `dsh web`**，并把**新片段加进 `tools/check_host_body.py` 的清单**。
2. 探针**不许改被它检查的仓库**：管线探针在临时目录里跑 fixtures，自检的副本写到系统临时目录。
   断言"仓库是干净的"之前，先看 `git status --porcelain` 里的改动**是谁写的**。

`prepack` 跑 `check` 与 `test:host`，所以过不了这两关的包**发不出去**。CI 在 Ubuntu 与 Windows 上、
Node 24 下跑同样两条命令。两个 Python 探针**刻意只在本地跑**：它们是作者自己的量具，不是发布门禁。

## 相关

- DeepSeek Harness —— 本插件运行在其中的宿主
- [awesome-dsh-plugin](https://awesome-dsh-plugin.com) —— DSH 插件市场背后的清单站；GitHub 话题 `dsh-plugin`

## 许可

MIT
