# dsh-chat-digest

[中文](README.zh.md) ｜ DeepSeek Harness plugin (profile bundle)

[![npm](https://img.shields.io/npm/v/dsh-chat-digest)](https://www.npmjs.com/package/dsh-chat-digest)
[![ci](https://github.com/OverDustD7/dsh-chat-digest/actions/workflows/ci.yml/badge.svg)](https://github.com/OverDustD7/dsh-chat-digest/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![node](https://img.shields.io/badge/node-%3E%3D22.5-informational)](https://nodejs.org)

**What you have to do is buried in group chats. This plugin keeps a panel of it, and an agent reads the chats for you.**

It owns a panel, one resident main-agent session, and the HTTP contract between them. On a schedule — or
when you click **Fetch** — the session reads your chat logs, picks out what you must do, what you can apply
for, and what is worth knowing, and rewrites the panel items. Each item can link straight to the original
file or image. The package ships **no chat-collection pipeline**: feed items over HTTP and the panel grows,
so it works with whatever collector you already have — or with none at all.

## Quick start (a fresh install)

Three steps, no pipeline required — the plugin has a **default data contract**: put chat exports in
`inbox\` under the agent workspace and the resident session reads them.

1. Install and restart (see *Install* below), then click **Fetch** once. The resident session is created
   and the round prompt tells it to read the inbox.
2. Drop your chat exports into the inbox — plain text, Markdown or JSON (`%LOCALAPPDATA%\dsh-chat-digest\
   workspace\inbox\` with the default `stateDir`; the exact path is `state.inbox` in
   `GET /chat-feed/api/state`). `examples/inbox/sample.txt` is a tiny sample you can copy in.
3. Click **Fetch** again. Items appear in the panel, each linking to the file it came from.

Want your own wording or your own collector? Copy `examples/local/` into a directory of your own, point
`config.localDir` at it, and edit the "where the data comes from" section.

## What it looks like

One item as the panel renders it (illustrative):

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

Two resident sessions stand behind the panel, one per configured route. Clicking **Fetch** opens a small
menu of those routes; picking one probes its gateway **before** running — if it does not answer, the round
is not triggered and the collection cursor does not move.

## How it works

```
schedule (a set time each day) or the Fetch button
  → pick a route; probe its gateway                       (before spending a model step)
  → wake / reuse the resident main-agent session for that route
  → the session runs the pipeline *you* gave it and reads your chats
  → it posts the items back:  /chat-feed/api/items
  → the panel is rebuilt; attachments become file: / img: links
  → a turn/end counter closes the round; the collection cursor advances
```

The plugin never parses your chats itself, and it never picks a model outside the routes you configure.
What it does own: the panel, the resident session, the round bookkeeping (busy accounting, one automatic
retry when a turn ends abnormally), context rotation at a per-route threshold, and the file endpoints.

## Requirements

| Need | Why | Without it |
|---|---|---|
| DSH `>= 0.1.5-rc.1` | host | — |
| Node `>= 22.5` | the loader and the browser half | — |
| **Windows** | files are opened through `cmd /c start`; paths are joined with `\` | the panel and the API still work; `file:` links fall back to download |
| A model route configured in DSH | the resident session runs on it | the panel and manual write-back work; no round can run |
| `wxRoot` — your WeChat attachment root | resolving `file:` / `img:` links | only `<agentCwd>\output` is allowed |
| An ingestion pipeline of your own | reading and distilling the chats | the panel is usable but nothing fills it by itself |

## Install

```sh
dsh plugin --profile web add dsh-chat-digest
```

`web` is the profile behind the DSH web UI — substitute your own profile name if you renamed it. Installing
already adds the package to the profile's `dsh.profile.bundles`; **do not add it by hand as well**, or the
loader fails with `duplicate loader entry id`. Then **restart `dsh web`**.

A local checkout works the same way:

```sh
dsh plugin --profile web add link:/path/to/dsh-chat-digest
```

> Why the restart: the host half is evaluated once, at mount time. `lib/ui.js` and `lib/right.js` are served
> over HTTP by the package itself (`Cache-Control: no-store`), so a **page refresh** is enough for those.

## Verify it works

- `GET /chat-feed/api/state` — one JSON with every self-reporting field: the items, the panel source, the
  route slots, the collection cursor, the context window and limit, the last error.
- `POST /chat-feed/api/collect` with `{"dry": true}` — builds the round prompt and returns it **without
  running anything**, so you can read exactly what the agent will be told.
- Click **Fetch**: the button goes `探测中…` → `采集中…` and the panel opens. If the gateway does not answer
  it flashes red, and neither the cursor nor the collection time changes.
- On disk: `%LOCALAPPDATA%\dsh-chat-digest\state.json` (items, cursor, route slots) and `panel.json`.

A fresh install stays empty until you feed items in or run a round. That is expected: the pipeline is yours.

## Configuration

Everything is optional and lives in the row's `config` — either in the package's `cordis.patch.yml` or,
better, in your own profile patch (`$DSH_HOME/profiles/<name>/cordis.patch.yml`), which wins:

```yaml
- id: dsh-chat-digest
  config:
    agentCwd: 'C:\path\to\your\agent-workspace'      # the resident session's cwd = its workspace
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

| Key | Default | Meaning |
|---|---|---|
| `bodyPath` | `<package>/lib/host-body.txt` | the authoritative host body; `DSH_CHAT_FEED_BODY` overrides it |
| `stateDir` | `%LOCALAPPDATA%\dsh-chat-digest` | where `state.json` and `panel.json` live |
| `agentCwd` | `<stateDir>\workspace` | the resident session's cwd — point it at your pipeline |
| `dshHome` | `$DSH_HOME`, else `%USERPROFILE%\.dsh` | used to read session titles |
| `agentPreset` | empty | agent preset to create the sessions with |
| `routes` | one generic route | `[{ id, label, provider?, model?, effort?, probeUrl?, ctxRatio?, default?, hint? }]`. Two routes is the intended shape; with none configured there is a single route that pins no provider or model, so the session inherits the host default |
| `localDir` | `<package>/local` | **your private content directory** — see below. When installed from npm the package sits under `node_modules/`, so point this at a directory of your own |
| `inboxDir` | `<agentCwd>\inbox` | the default data source the built-in prompts tell the agent to read. `{inbox}` in a `local/round.md` expands to it, and it is in `fileRoots` by default |
| `wxRoot` | **none — set it** | WeChat attachment root — only needed for attachments outside the inbox and `<agentCwd>\output` |
| `fileRoots` | `[wxRoot, <agentCwd>\output]` | roots allowed for byte serving and "open in the default app" (rejects `..`, absolute paths outside the roots, and UNC) |

### Your own prompts

The wake prompt and the per-round instruction are files, not code, and they live outside the repository:

| Where | What | Without it |
|---|---|---|
| `localDir/prompt.md` | the prompt that wakes the main agent | a short generic prompt saying this plugin owns only the panel and the resident session |
| `localDir/round.md` | the per-round instruction (`{date}` and `{mode}` are substituted) | a generic round instruction |

`localDir` resolves in this order: `config.localDir` → `$DSH_CHAT_FEED_LOCAL` → `<package>/local`. The
directory is `.gitignore`d and excluded from the published `files` whitelist, so private prompts and paths
never reach the repository or the npm tarball.

## What it writes, and what it costs

- State only, under `stateDir`: `state.json` (atomic write, a `.bak` copy, and a `.corrupt-<ts>` quarantine
  when a file fails to parse) and `panel.json`. Nothing is written inside `node_modules`, and no file of
  yours is modified. A bad state file is never deleted.
- Legacy state locations (`%LOCALAPPDATA%\chat-feed\`, `%TEMP%\chat-feed\`, `%TEMP%\dsh-chat-digest\`) are
  read once as migration sources, then left in place.
- A round costs that route's tokens: it reads your chats and rewrites the panel. There is no other cost, and
  no telemetry.
- Rotation is per route — `ctxRatio` of the session's window. The author's two routes use `0.75` (a 200k
  route) and `0.5` (a 1M route).
- The plugin stores **no credentials**: model routes and API keys come from DSH's model configuration.

## Uninstall

```sh
dsh plugin --profile web remove dsh-chat-digest
```

Then restart. Delete `%LOCALAPPDATA%\dsh-chat-digest\` if you also want the panel data gone — deliberately a
manual step, since it is the only copy.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| The panel stays empty | nothing has fed it. POST items to `/chat-feed/api/items`, or set `localDir` + a pipeline and run a round |
| `Fetch` flashes red | the picked route's `probeUrl` did not answer. The cursor and the collection time are untouched by design |
| A round never finishes | the resident session is still working, or a turn ended abnormally — the plugin retries once and says so in `state.note` |
| The panel fell back to the built-in three sections | `panel.json` is missing or invalid; `GET /chat-feed/api/panel` reports which. Nothing is overwritten |
| Items point at files that will not open | the path is outside `fileRoots`. Add the root, or set `wxRoot` |
| Items are missing after an upgrade | the state migration reads the old locations; `state.note` records the source path it used |

## What it does not do

- **It does not ship an ingestion pipeline.** WeChat decryption, message extraction, image triage and
  attachment indexing belong to a workspace of your own, driven by the resident agent. This package owns the
  panel, the session and the contract between them. See the `docs/` directory of the source repository.
- **It does not ship model credentials**, and it does not choose models outside your `routes`.
- **It does not do off-site backup.** Copy `stateDir` yourself if you want one.
- It has only been verified on Windows.

## Development

Layout:

| Path | What is in it |
|---|---|
| `lib/plugin.js` | the loader: reads the body, evaluates it as `new Function('CFG', text)(cfg)`, calls `apply` |
| `lib/host-body.txt` | the authoritative host half: routes, session slots, panel, scheduled rounds, rotation |
| `lib/ui.js` | the browser half: sidebar entry, the Fetch dropdown, the panel shell |
| `lib/right.js` | the panel's item list and rich text (`file:` / `img:` links) |
| `docs/` | `INDEX.md`, `STATUS.md` (change history — grep it), `COLD-START-ENGINEERING.md`, `ARCHITECTURE.md`, `audit-2026-09-20/` |
| `test/` | 23 host probes + 6 pipeline probes |
| `tools/` | `check_host_body.py` (self-check) plus one-off diagnostics |

```sh
npm run check                            # syntax check the three runtime JS files
npm run check:body                       # host body self-check (must print FAILS: 0)
npm run test:host                        # 23 host probes
npm run test:pipeline                    # 6 pipeline probes
```

Two rules this repository holds itself to:

1. After editing `lib/host-body.txt` you **must restart `dsh web`**, and **add the new fragment to
   `tools/check_host_body.py`'s list**.
2. Probes **must not modify the repository they check**: the pipeline probe runs its fixtures in a temp
   directory, and the self-check writes its scratch copy to the system temp dir. Before asserting "the repo
   is clean", look at *who wrote* the changes in `git status --porcelain`.

`prepack` runs `check` and `test:host`, so a package that fails either cannot be published. CI runs the same
two commands on Ubuntu and Windows with Node 24. The Python probes are local-only on purpose: they are the
author's own instruments, not a release gate.

## Links

- DeepSeek Harness — the host this plugin runs in
- [awesome-dsh-plugin](https://awesome-dsh-plugin.com) — the curated list behind the DSH marketplace;
  GitHub topic `dsh-plugin`

## License

MIT
