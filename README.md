# dsh-chat-digest

English | [简体中文](README.zh.md)

[![npm version](https://img.shields.io/npm/v/dsh-chat-digest?style=flat)](https://www.npmjs.com/package/dsh-chat-digest)
[![CI](https://github.com/OverDustD7/dsh-chat-digest/actions/workflows/ci.yml/badge.svg?style=flat)](https://github.com/OverDustD7/dsh-chat-digest/actions/workflows/ci.yml)
[![Node](https://img.shields.io/badge/node-%3E%3D22.5-informational?style=flat)](#requirements)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat)](LICENSE)

Turns your chat exports into a panel of what you have to do, what you can apply for and what is worth
knowing, and keeps one resident DSH agent session reading the chats and rewriting that panel.

## Status and support

- Status: maintained.
- Supported: the DSH web UI on Windows x64, DSH `>= 0.1.5-rc.1`, Node `>= 22.5`.
- Other platforms: CI is configured for core probes on Windows and Linux; live Linux and macOS host workflows are unverified. No standalone hosted service or mobile client is provided.
- This release is **1.5.4**.

The panel, one resident main-agent session (switching route switches the model on that same session), and
belong to the plugin. On a schedule, or when you click **Fetch**, the session reads your chats, picks out
the items, and posts them back; each item can link straight to the original file or image. The core needs
no collector: an optional WeChat/QQ ingestion pipeline ships with the package, and you can feed the panel
from a private inbox or over HTTP instead.

## Requirements

| Need | Why | Without it |
|---|---|---|
| DSH `>= 0.1.5-rc.1` | the host | — |
| Node `>= 22.5` | the loader and the browser half | — |
| A working `pnpm` | the `dsh plugin` command installs a profile bundle through pnpm | adding the bundle fails before it is written |
| **Windows** | files are opened through `cmd /c start`; paths are joined with `\` | the panel and the API still work; `file:` links fall back to a download |
| A model route configured in DSH | the resident session runs on it | the panel and manual write-back work; no round can run |
| `wxRoot` — your WeChat attachment root | resolving `file:` / `img:` links | only `{{AGENT_CWD}}\output` is allowed |
| Optional WeChat/QQ collector | automatic ingestion from local chat databases | direct inbox exports and manual HTTP input work without it |

## Installation

```sh
dsh plugin --profile web add dsh-chat-digest@1.5.4
```

`web` is the profile behind the DSH web UI — substitute your own profile name if you renamed it. Installing
already adds the package to the profile's `dsh.profile.bundles`; do not add it by hand as well, or the loader
fails with `duplicate loader entry id`. Then **restart `dsh web`**.

A local checkout works the same way:

```sh
dsh plugin --profile web add link:{{CHECKOUT_DIR}}
```

Success signal: `GET /chat-feed/api/state` answers with JSON, and the sidebar shows a **聊天摘要** entry.

> Why the restart: the host half is evaluated once, at mount time. `lib/ui.js` and `lib/right.js` are served
> over HTTP by the package itself (`Cache-Control: no-store`), so a **page refresh** is enough for those.

## Quick start

Three steps, no pipeline required — the plugin has a **default data contract**: put chat exports in the
inbox under the agent workspace and the resident session reads them.

1. Put your chat exports into the inbox — plain text, Markdown or JSON (`%USERPROFILE%\.dsh\dsh-chat-digest\inbox\`
   by default; the exact path is the `inbox` field of `GET /chat-feed/api/state`).
   `examples/inbox/sample.txt` is a small sample you can copy in.
2. Click **Fetch** once. The session reads the inbox and adds items to the panel, each linking to its source file.
3. Check that it worked: the button goes `探测中…` → `采集中…`, the panel opens, and the items appear. If the
   gateway does not answer, the button flashes red and neither the collection cursor nor the collection time
   changes.

What one item looks like once rendered (illustrative):

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

Two checks that do not start a collection round:

- `GET /chat-feed/api/state` — one JSON with the items, the panel source, the route slots, the collection
  cursor, the context window and limit, and the last error. Reading it can create or repair the per-route
  resident session slots when they are missing or out of date, so it is a status read that may initialise a
  session; it is not a passive endpoint.
- `POST /chat-feed/api/collect` with `{"dry": true}` — returns the prompt that a manual round would inject,
  plus its character count and the cursor it was built from. This branch neither probes a route nor starts a
  round; the same endpoint with a `route` value does both, so use the dry body when you only want to read the
  prompt.

A fresh install stays empty until you feed items in or run a round. That is expected: the pipeline is yours.
Want your own wording or your own collector? Copy `examples/local/` into a directory of your own, point
`config.localDir` at it, and edit the "where the data comes from" section.

## Configuration, data and permissions

Data and permission summary:

- Data read: the chat exports you put in the inbox (or wherever your own collector writes), the attachment
  and image files under `fileRoots` when an item links to them, and DSH session titles used to label the
  resident session. The plugin does not parse WeChat or QQ databases itself; the optional pipeline does, with
  the third-party tools you install.
- Stored at: `{{DSH_HOME}}/dsh-chat-digest/` — the private profile, outside the package. It holds
  `state.json`, `panel.json`, `output/`, `knowledge/`, `archive/`, and your pipeline configuration. Nothing
  the plugin writes lands inside the package directory.
- Sent out: the text the resident session reads is sent to the model route you configured in DSH, because
  that session is the reader. The plugin's own outbound request is the gateway probe you configure
  (`probeUrl`); it sends no telemetry. Panel items reference attachments by path, and what the resident
  session then does with those references is up to the prompt and the tools you give it: a configured
  optional tool (a vision step, for example) can read a file and send its content to the model route it
  uses. The core does not upload attachment files on its own.
- Permissions: read access inside `fileRoots`, permission to launch the system default application for
  `file:` links (Windows `cmd /c start`), and the HTTP endpoints served through the DSH host, whose
  authentication applies. No administrator rights, no registry writes, no listening port of its own.

Configuration is optional and lives in that row's `config` — either in the package's `cordis.patch.yml` or,
better, in your own profile patch (`$DSH_HOME/profiles/{{PROFILE}}/cordis.patch.yml`), which wins:

```yaml
- id: dsh-chat-digest
  config:
    localDir: '{{PRIVATE_PROFILE_DIR}}'               # private data and resident session workspace
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

| Key | Default | Meaning |
|---|---|---|
| `bodyPath` | `{{PACKAGE_DIR}}/lib/host-body.txt` | the authoritative host body; `DSH_CHAT_FEED_BODY` overrides it |
| `stateDir` | `localDir` (the private profile) | where `state.json` and `panel.json` live |
| `agentCwd` | `localDir` (the private profile) | must resolve to the same physical directory as `localDir`; normally omit it |
| `dshHome` | `$DSH_HOME`, else `%USERPROFILE%\.dsh` | used to read session titles |
| `agentPreset` | empty | agent preset to create the sessions with |
| `routes` | one generic route | `[{ id, label, provider?, model?, effort?, probeUrl?, ctxRatio?, default?, hint? }]`. Two routes is the intended shape; with none configured there is a single route that pins no provider or model, so the session inherits the host default |
| `localDir` | `{{DSH_HOME}}/dsh-chat-digest` | the physical private profile directory — see below |
| `inboxDir` | `{{AGENT_CWD}}\inbox` | the default data source the built-in prompts tell the agent to read. `{inbox}` in a `local/round.md` expands to it, and it is in `fileRoots` by default |
| `wxRoot` | none — set it | WeChat attachment root — only needed for attachments outside the inbox and `{{AGENT_CWD}}\output` |
| `fileRoots` | configured wxRoot, private output and inbox (unless overridden) | roots allowed for byte serving and "open in the default app" (rejects `..`, absolute paths outside the roots, and UNC) A nonempty list replaces the defaults; an empty list keeps them. |
| `pythonRuntime` | `legacy` | `legacy` uses an external Python. Set `bundled` only for a separately assembled local copy with a runtime manifest. That mode validates the manifest before creating the private directory and stops if it is missing or invalid. |
| `python` | none | Set this to the external interpreter you want the host to use for pipeline commands. |

### The private profile

Your private things — prompt overrides, private configuration, products, knowledge base, archive, panel
state — live in the plugin's own profile directory:

```text
{{DSH_HOME}}/dsh-chat-digest/           default = %USERPROFILE%\.dsh\dsh-chat-digest
    pipeline.yaml  pipeline.json      wxid / database keys / group names / paths
    output/  knowledge/  archive/     products / knowledge base / archive
    docs/  state.json  panel.json  profile.md
```

- `{{PACKAGE_DIR}}/local`, `{{PACKAGE_DIR}}/profile`, `agent/output` and `agent/docs/{knowledge,archive}` are
  compatibility junctions. The session cwd and all new writes use the physical private directory.
- Why not inside the package: `dsh plugin add {{PACKAGE_DIR}}@{{VERSION}}` rebuilds the whole package directory, so
  private files kept there are lost on every update.
- Why not somewhere else: under `~/.dsh` the `*` rule in `~/.dsh/.gitignore` ignores it, and the repository
  `.gitignore` plus the package `files` list exclude `local`/`profile`/`output`/`knowledge`/`archive`/
  `state` — three layers, so the private profile is not uploaded.
- Fresh installs work: mount creates an empty private directory and the compatibility junctions; it never
  copies the sample chat into the inbox automatically.

### Your own prompts

The wake prompt and the per-round instruction ship inside the package:

| Where | What |
|---|---|
| `{{PACKAGE_DIR}}/prompt/prompt.md` | the prompt that wakes the main agent |
| `{{PACKAGE_DIR}}/prompt/round.md` | the per-round instruction (`{date}`, `{mode}`, `{since}`, `{agent}`, `{pkg}`, `{profile}`, `{py}`, `{work}` are substituted) |

To use your own wording, drop a `prompt.md` / `round.md` of the same name into your private profile; it wins.
Lookup order = private profile → `{{PACKAGE_DIR}}/prompt/` → built-in generic.

`localDir` resolves in this order: `config.localDir` → `$DSH_CHAT_FEED_LOCAL` → `{{DSH_HOME}}/dsh-chat-digest`.

## Upgrade and uninstall

Upgrade:

```sh
dsh plugin --profile web add dsh-chat-digest
```

Then restart `dsh web`. The private profile is never part of the package, so `state.json`, `panel.json`,
your prompts and your pipeline configuration survive an upgrade. Upgrading from a version that kept state in
the old locations (`%LOCALAPPDATA%\chat-feed\`, an older temp directory, `%TEMP%\dsh-chat-digest\`) reads
those once as migration sources and leaves them in place; `state.note` records which one was used.

If you are upgrading a locally assembled 1.5.2 build, keep a private backup of the original package,
profile configuration and data. Before restarting on this release, set `pythonRuntime: legacy` in the plugin
configuration, or remove the mode override. If you use chat import, configure the external tools below
before updating. Keep `localDir` and `stateDir` pointed at the same private locations as before.

For rollback, reinstall the exact previous package and restore the matching plugin and pipeline
configuration. Use `dsh plugin --profile {{PROFILE}} add dsh-chat-digest@{{PREVIOUS_VERSION}}` for a
registry version. For a previously assembled local package, use its saved copy with
`dsh plugin --profile {{PROFILE}} add link:{{PREVIOUS_PACKAGE_DIR}}`. After restarting, check
`/chat-feed/api/panel` and a known item before resuming collection.

Uninstall:

```sh
dsh plugin --profile web remove dsh-chat-digest
```

Then restart. Remove `{{DSH_HOME}}\dsh-chat-digest\` as a separate manual step if you also want the panel data
gone — it is deliberately not automatic, because that directory is the only copy.

## Limitations and troubleshooting

After a host restart, if a state write is denied and the saved resident session is unloaded, the
plugin checks the session's identity and can restore it once to retry the write under its existing
DSH policy. If the write is still denied, automatic collection stays paused. Automatic collection
keeps the model currently selected in DSH. Explicitly choosing a named route or model can change
that selection.


The panel, the items API and the inbox workflow run with the host's Node.js. For the optional
WeChat/QQ pipeline, set up an external Python environment and install the dependencies listed in
[`pipeline/requirements.txt`](pipeline/requirements.txt). Set the plugin's `python` and the private
`pipeline.yaml`'s `python` to the same interpreter. Set `external_dir` in that YAML to the absolute
path of a directory outside the plugin. The plugin does not fetch or install these tools.

| Import step | File relative to `external_dir` |
|---|---|
| WeChat database decryption | `WeChatDataAnalysis/src/wechat_decrypt_tool/wechat_decrypt.py`, with its companion modules |
| QQ raw-key decryption | `nt_msg_db_util/qq_decrypt_hex.py`, a separately obtained compatible local adapter |
| QQ structured export | `nt_msg_db_util/3.export.py`, with its `msgdb` package |

Use trusted copies you have permission to use. For an existing private 1.5.2 installation, the local
QQ adapter is its original `pipeline/qq_decrypt_hex.py`. Preserve the source and notices in your private
copy. The adapter accepts `<key_hex> <source.db> <plain.db>`; upstream `1.decrypt.py` does not provide
that raw-key interface. Move the tools to the paths in the table before replacing the old package.
On another machine, keep your private profile and reconfigure the interpreter and tool paths.

If the WeChat tool is missing, the WeChat import reports a required dependency error. If the QQ
configuration or tools are missing, the QQ steps report a degraded or skipped result and keep prior
exports available. The panel and inbox remain available independently of these steps.

- The plugin ships no model credentials and does not choose models outside your `routes`.
- It does no off-site backup. Copy `stateDir` yourself if you want one.
- It has only been verified on Windows.

| Symptom | Likely cause |
|---|---|
| The panel stays empty | nothing has fed it. POST items to `/chat-feed/api/items`, or set `localDir` + a pipeline and run a round |
| `Fetch` flashes red | the picked route's `probeUrl` did not answer. The cursor and the collection time are untouched by design |
| A round never finishes | the resident session is still working, or a turn ended abnormally — the plugin retries once and says so in `state.note`. If the session state cannot be read at all, the plugin resets the round after repeated failed probes or after three hours, so the panel cannot stay stuck on "collecting" |
| The panel fell back to the built-in three sections | `panel.json` is missing or invalid; `GET /chat-feed/api/panel` reports which. Nothing is overwritten |
| Items point at files that will not open | the path is outside `fileRoots`. Add the root, or set `wxRoot` |
| Items are missing after an upgrade | the state migration reads the old locations; `state.note` records the source path it used |

Core state lives under `stateDir`: `state.json` (atomic write, a `.bak` copy, and a `.corrupt-{{TIMESTAMP}}`
quarantine when parsing fails) and `panel.json`. A bad state file is never deleted.

## Development

| Path | What is in it |
|---|---|
| `lib/plugin.js` | the loader: reads the body, evaluates it as `new Function('CFG', text)(cfg)`, calls `apply` |
| `lib/host-body.txt` | the authoritative host half: routes, session slots, panel, scheduled rounds, rotation |
| `lib/ui.js` | the browser half: sidebar entry, the panel shell, and the Fetch/Auto buttons in the panel's top bar |
| `lib/right.js` | the panel's item list and rich text (`file:` / `img:` links) |
| `docs/` | internal engineering notes kept locally; they are not tracked in this public repository |
| `test/` | host probes and pipeline probes |
| `tools/` | `check_host_body.py` (self-check) plus one-off diagnostics |

```sh
npm run check                            # syntax check the runtime JS files
npm run check:body                       # host body self-check (must print FAILS: 0)
npm run test:host                        # host probes
npm run test:pipeline                    # pipeline probes (local only)
```

How a round runs:

```text
schedule (a set time each day) or the Fetch button
  → pick a route; probe its gateway                       (before spending a model step)
  → wake / reuse the resident main-agent session for that route
  → the session runs the pipeline you gave it and reads your chats
  → it posts the items back:  /chat-feed/api/items
  → the panel is rebuilt; attachments become file: / img: links
  → a turn/end counter closes the round; the collection cursor advances
```

The plugin never parses your chats itself, and it never picks a model outside the routes you configure.
What it does own: the panel, the resident session, the round bookkeeping (busy accounting, one automatic
retry when a turn ends abnormally), context rotation at a per-route threshold, and the file endpoints.

Two rules this repository holds itself to:

1. After editing `lib/host-body.txt`, add the new fragment to `tools/check_host_body.py`'s list and re-run
   the self-check. A running host only picks such a change up when it reloads the plugin; that reload is an
   explicit operation and is not part of editing the source.
2. Probes must not modify the repository they check: the pipeline probe runs its fixtures in a temp
   directory, and the self-check writes its scratch copy to the system temp dir. Before asserting "the repo
   is clean", look at who wrote the changes in `git status --porcelain`.

`prepack` runs `check`, `test:host`, `test:portability` and `test:ui`, when lifecycle scripts are enabled. A candidate built with scripts disabled still needs the applicable checks before release. CI runs `check`, `test:host` and `test:portability` on Ubuntu and Windows with Node 24.
The two Python probes are local-only on purpose: they are the author's own instruments, not a release gate.

## Feedback and security

- Issues: <https://github.com/OverDustD7/dsh-chat-digest/issues>
- Security: this project offers no private security channel. Do not post chat content, credentials,
  attachment paths or other sensitive details in a public issue; describe the class of problem and how to
  reproduce it without the data.

## License and third-party notices

License: MIT for this project's own code, see [LICENSE](LICENSE).

The npm candidate ships the plugin and import integration. Install the Python interpreter, packages
and import tools separately.

| External tool | Source used to verify the interface | Upstream terms |
|---|---|---|
| WeChat decryptor | [LifeArchiveProject/WeChatDataAnalysis at 36d1e54](https://github.com/LifeArchiveProject/WeChatDataAnalysis/tree/36d1e548172e9fb87f26d729403a058d13d92bca) | The checked revision has third-party notices, with no project licence covering the decryptor established |
| QQ export and upstream basis for the raw-key adapter | [QQBackup/nt_msg_db_util at 317024c](https://github.com/QQBackup/nt_msg_db_util/tree/317024ce2c5e3482fdf9f310a5a7159ab4927e34) | GPLv3; keep upstream notices and follow the applicable terms for your local copy or any distribution |
