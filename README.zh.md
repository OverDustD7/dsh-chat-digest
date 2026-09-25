# dsh-chat-digest · 聊天摘要

[English](README.md) ｜ DeepSeek Harness 插件（profile bundle）

[![npm](https://img.shields.io/npm/v/dsh-chat-digest)](https://www.npmjs.com/package/dsh-chat-digest)
[![ci](https://github.com/OverDustD7/dsh-chat-digest/actions/workflows/ci.yml/badge.svg)](https://github.com/OverDustD7/dsh-chat-digest/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![node](https://img.shields.io/badge/node-%3E%3D22.5-informational)](https://nodejs.org)

**该做的事埋在群聊里。这个插件替你留一块面板，派一条常驻会话去读。**

它管三样东西：一块面板、一条常驻主 agent 会话、以及两者之间的 HTTP 契约。按定时——或者你点一下侧栏的
**「获取」**——那条会话就去读你的聊天记录，挑出「必须做的」「可以报名的」「值得知道的」，重写面板条目；
每条都能直接链到原始文件或图片。**本包不带取数管线**：把条目用 HTTP 喂进来，面板就会长出来，
所以你用现成的采集器也行，什么都不接也行。

## 装完三步走（全新安装）

**不需要取数管线** —— 插件有一个**默认数据约定**：把聊天导出丢进主 agent 工作区下的 `inbox\`，常驻会话会去读它。

1. 装上并重启（见下面「安装」），点一次**「获取」**。常驻会话会被建出来，轮次提示词会让它去读 inbox。
2. 把聊天导出丢进 inbox —— 纯文本 / Markdown / JSON 都行（默认 `stateDir` 下就是
   `%LOCALAPPDATA%\dsh-chat-digest\workspace\inbox\`；确切路径看 `GET /chat-feed/api/state` 的 `inbox` 字段）。
   `examples/inbox/sample.txt` 是一份可以直接复制进去的小样例。
3. 再点一次**「获取」**。面板上就长出条目，每条都链回它来自哪个文件。

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
- 盘上：`%LOCALAPPDATA%\dsh-chat-digest\state.json`（条目、游标、线路槽）与 `panel.json`。

新装完是空的，直到你喂进条目或跑一轮为止 —— 这是预期的：管线是你的。

## 配置

每个键都可选，写在那一行的 `config` 里 —— 可以写在包自己的 `cordis.patch.yml`，但更好是写在
**你自己 profile 的 patch 层**（`$DSH_HOME/profiles/<name>/cordis.patch.yml`，它会赢）：

```yaml
- id: dsh-chat-digest
  config:
    agentCwd: 'C:\path\to\your\agent-workspace'      # 常驻会话的 cwd ＝ 它的工作区
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
| `stateDir` | `%LOCALAPPDATA%\dsh-chat-digest` | `state.json` 与 `panel.json` 的位置 |
| `agentCwd` | `<stateDir>\workspace` | 常驻会话的 cwd —— 指到你的取数管线 |
| `dshHome` | `$DSH_HOME`，否则 `%USERPROFILE%\.dsh` | 读会话标题用 |
| `agentPreset` | 空 | 建会话时带的 agent preset |
| `routes` | 一条通用线路 | `[{ id, label, provider?, model?, effort?, probeUrl?, ctxRatio?, default?, hint? }]`。两条线是设计形态；不配则只有一条不指定 provider/model 的线路，会话继承宿主默认 |
| `localDir` | `<包>/local` | **你的私人内容目录**（见下）。从 npm 装进来时包在 `node_modules/` 下，所以指到你自己一个固定目录 |
| `inboxDir` | `<agentCwd>\inbox` | 内置提示词让 agent 去读的**默认数据来源**；`local/round.md` 里的 `{inbox}` 就是它，且它默认在 `fileRoots` 里 |
| `wxRoot` | **无缺省** | 微信附件根 —— 只有当附件在 inbox 与 `<agentCwd>\output` 之外才需要 |
| `fileRoots` | `[wxRoot, <agentCwd>\output]` | 允许取字节 / 用默认应用打开的根（拒绝 `..`、根外绝对路径、UNC） |

### 你自己的提示词

唤醒提示词与每轮指令是**文件**、不是代码，而且放在仓库之外：

| 放哪 | 放什么 | 没有它会怎样 |
|---|---|---|
| `localDir/prompt.md` | 唤醒主 agent 的提示词 | 一段短短的通用提示词，说明本插件只管面板与常驻会话 |
| `localDir/round.md` | 每轮的指令（`{date}`、`{mode}` 会被替换） | 一段通用的轮次指令 |

`localDir` 的解析顺序：`config.localDir` → `$DSH_CHAT_FEED_LOCAL` → `<包>/local`。这个目录已被
`.gitignore` 忽略、也不在发布的 `files` 白名单里 —— 私人提示词与路径**永远不会**进仓库或 npm 包。

## 它写什么、花什么

- **只写状态**，都在 `stateDir` 下：`state.json`（原子写 + 一份 `.bak`；解析失败时把坏件隔离成
  `.corrupt-<ts>`）与 `panel.json`。不往 `node_modules` 里写，也不改你任何文件；坏件**从不删**。
- 旧位置（`%LOCALAPPDATA%\chat-feed\`、`%TEMP%\chat-feed\`、`%TEMP%\dsh-chat-digest\`）只作为
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

- **不带取数管线。** 微信解密、消息提取、图片分诊、附件索引都属于你自己的一个工作区，由常驻 agent 驱动。
  本包管的是面板、会话与两者之间的契约。为什么这么分见 源码仓库里的 `docs/` 目录。
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
