# Changelog

All notable changes to this package. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.0] — 2026-09-27

**私人文件不再放包里；通用件全在包里**

- **私人 profile（本地、不上传、更新不丢）**：提示词覆盖、私有配置、产物、知识库、归档、面板状态
  全部住在 `<DSH_HOME>/dsh-chat-digest`（缺省 `%USERPROFILE%\.dsh\dsh-chat-digest`）。
  插件目录里的 `<包>/local`（别名 `profile`）与 `agent/output`、`agent/docs/{knowledge,archive}`
  是**运行时联接**，挂载时自动重建 ⇒ 路径上"私人文件就在插件目录里"，而 `dsh plugin add` 重建包目录
  时数据不会丢。`~/.dsh/.gitignore` 的 `*` 规则、仓库 `.gitignore`、包的 `files` 白名单三处都排掉它们。
- **提示词本体进包**：`<包>/prompt/prompt.md`、`<包>/prompt/round.md`（通用件）。加载顺序
  **私人 profile → 包内 `prompt/` → 内置通用**；要改就自己在私人 profile 放同名文件。
  修掉一个真 bug：过去挂载会往私人目录播一份 1.2 KB 示例，把包里 19 KB 的完整提示词顶掉。
- **随包代码一律包内解析**：`agent_root()`＝`<包>/agent`、`scripts_dir()`＝`<包>/pipeline`、
  `work_dir()`/`out_dir()` 缺省＝私人 profile 及其 `output/`、`python_exe()` 缺省＝当前解释器、
  包外第三方工具走 `external_dir`（缺省找 `<包>/vendor/`）。删掉 22 个管线脚本、3 个 `.mjs`、
  10 个工具里指向包外的路径与 5 处字面占位符（`r"WORK_DIR"` 等）。
- **round 提示词走 TPL**：`{agent}`/`{pkg}`/`{profile}`/`{py}`/`{work}` 与 `{date}`/`{mode}` 一起渲染
  （过去 round 那条链只换 date/mode/inbox，17 个占位符会原样发给主 agent）。
- **说明书的私人值摘成占位符**：真名/校名书院/师生姓名/群名与群 ID/校内短号/课程号/本机路径/
  聊天昵称/图片 md5/消息 svrid 全部换成占位；本体（10 份全文说明书 + 65 个工具）照旧随包发布。
- **包内不得出现私人值**：`package.json.files` 增加否定项（`local`、`profile`、`agent/output`、
  `agent/docs/{knowledge,archive}`、`**/__pycache__`、`**/*.pyc`），门禁加固定检查。

## [1.4.2] — 2026-09-27

- 随包工具里剩下的本机路径通用化（`make_handoff` / `probe_boundary` / `read_session` / `kb_append`
  的说明与示例）。
- `pipeline/pipeline.example.yaml` 写清可选键：`work_dir` / `output_dir` / `python` / `external_dir`。
- 新增 `tools/private-backup.ps1`：重装前备份、装完恢复私人 profile（只复制不删除）。

## [1.4.1] — 2026-09-27

- `agent/docs/agent/cf_api.py` 随包发布（1.4.0 漏了它）；`pipeline/requirements.txt` 补
  `openpyxl` / `pypdf`（`read_attachment` 用）。

## [1.4.0] — 2026-09-27

### Added

- **The resident agent's manual and toolbox now ship with the package** (`agent/docs/`, `agent/tools/`).
  Until now the package carried the plugin plus a copy of the collection pipeline, but everything the
  agent actually works from — its operating manual and the scripts that write the panel — lived in the
  author's own checkout, so a fresh install could not run a full round. `agentCwd` now defaults to the
  package's `agent/` directory, so an install needs no directory outside the package.

### Changed

- The resolved personal directory is exported to child processes as `DSH_CHAT_FEED_LOCAL` (the loader
  already resolved it; the pipeline and the tools only read the environment), and `pipeline/pconf.py`
  gained `profile()` / `p()` so every tool locates the personal profile directory the same way.
- Deployment-specific values that were still hard-coded inside the toolbox moved out: the route gateway,
  model names and key-variable name now come from the environment (`线路1_*` / `PARATERA_*`), the
  credentials path is resolved from the home directory, and several usage examples no longer name a
  particular deployment's groups or links.

## [1.3.4] — 2026-09-27

### Fixed

- **Ticking an item took about 0.7 s.** Every click on the panel (`toggle` / `delete` / `clear-done`)
  awaited `saveState()`, which made two `fs` service calls plus a read-back of the previous state file
  and a JSON parse of it. Measured: a real toggle's `POST /item` took **669 ms**, while the same route
  with a non-existent id (returns early, writes nothing) took **1–2 ms** — and doing the same read and
  two writes directly on disk takes **1.6 ms**. So the cost is the number of `fs` service calls, not the
  disk. Those three actions now update memory and return immediately, handing the write to a
  single-flight, coalescing background save; and `saveState()` no longer reads the previous file back
  from disk (it keeps the last written text in memory).
- **The wake prompt could be injected into the session more than once.** The once-per-session guard was
  a module variable, so every page reload or plugin re-mount could send the whole wake prompt — which is
  the *entire* instruction text — into the conversation again, making the resident agent run another
  turn for nothing. The guard now lives in `localStorage` and is keyed by session id.

### Changed

- Clicking no longer waits for the state file to be written. A process kill inside that few-hundred-
  millisecond window can lose the last change; a page refresh cannot (the in-memory state is served).

## [1.3.3] — 2026-09-27

### Fixed

- **The panel rebuilt its whole list every 15 seconds, so a click could land on a node that had just
  been replaced** — pressing a checkbox and releasing over a re-created row fires no `click` at all,
  which reads as "clicking does nothing / the panel hangs". The panel now compares a data signature
  and only rebuilds the list when something actually changed; an unchanged refresh just updates the
  "last collected" line. Measured before: 64 DOM node changes per 16 s, a full list rebuild twice per
  cycle. After: the list node is left untouched.
- **`right.js` could keep drawing into a detached list node.** `renderPanel()` guarded mounting with a
  one-shot `mounted` flag, so if the panel node was ever re-created (which `ensurePanel()` does when
  the panel is missing or detached), the right column silently went blank or unclickable. Mounting is
  now re-done whenever the list node changes.

## [1.3.2] — 2026-09-27

### Fixed

- **The right column was not created on a freshly loaded page.** `ensurePanel()` runs during boot, but
  the host shell has not rendered its center column yet at that point, so it returned early — and the
  retry path only covered "the panel exists but got detached from the DOM", never "the panel was never
  created". A freshly loaded page therefore had an empty right column until you clicked the sidebar
  entry once. Measured: 0 items before the click, 30 after. The sidebar entry row had the same silent
  failure. Both are now retried, with a bounded counter that resets as soon as both are in place.

## [1.3.1] — 2026-09-27

### Fixed

- **An open panel could stop refreshing.** `openPanel()` used to render only the state it already
  held in memory, and the 15-second refresh timer was registered at the very end of `boot()` with no
  error handling — so a throw earlier in boot (or a stale instance whose timer had been cleared) left
  the panel mounted, populated, and **permanently stale, with nothing shown to the user**. Measured:
  the server held 30 items while a long-lived tab issued zero requests. Opening the panel now fetches
  fresh state, the timer is registered before anything else in `boot()`, and the rest of boot is
  guarded so a failure surfaces on the panel instead of dying silently.

## [1.3.0] — 2026-09-25

### Fixed

- Removed deployment-specific values that had leaked into the shipped package
  (database keys, a QQ number, a personal note, school-flavoured defaults). They now
  come from `local/pipeline.yaml` / `local/pipeline.json`.

## [1.2.0] — 2026-09-25

The pipeline ships with the plugin.

### Added

- **`pipeline/` — the collection pipeline itself** (24 scripts: WeChat/QQ decryption, window and day
  extraction, attachment finding, URL/article fetching, image handling, per-day preparation). A fresh
  install no longer depends on any local checkout: the scripts come with the package, and only *your*
  data has to be supplied.
- **`pipeline/pconf.py`** — the single place the scripts read deployment-specific values from
  (`<localDir>/pipeline.yaml`). No group name, path or account is hardcoded anywhere in `pipeline/`
  (the set of values is deployment-specific and lives in your `localDir`; before publishing a fork, re-check with your own list). A missing key prints which key, which file to fill, and exits 2.
- `pipeline/pipeline.example.yaml` — the template to copy into your `localDir`.
- `pipeline/requirements.txt` — the third-party Python packages the pipeline needs. The plugin itself
  stays zero-dependency; this is the collection step, which cannot avoid them.

### Notes

- `pipeline/wx_decrypt3.py` uses the decryptor from **WeChatDataAnalysis**;
  `pipeline/qq_decrypt_hex.py` is adapted from **QQBackup/nt_msg_db_util**. Both now carry their
  provenance in a header comment — check those projects' licences and your local law before use.
- Historical one-off scripts (dated diagnostics etc.) are deliberately **not** shipped.

## [1.1.0] — 2026-09-25

Usable out of the box.

### Added

- **A default data contract.** The built-in prompts now tell the resident session to read `inbox\` under
  the agent workspace (recursively: `*.txt`, `*.md`, `*.json`) — so a fresh install works end to end with
  no ingestion pipeline at all: drop chat exports into the inbox and click Fetch. `config.inboxDir`
  overrides the location, and `{inbox}` in a `local/round.md` expands to it.
- `examples/inbox/sample.txt` and `examples/local/{prompt.md,round.md}` — a copy-paste starting point.
- The inbox is part of the default `fileRoots`, so `file:` and `img:` links to inbox files resolve.

### Fixed

- **Fetch no longer fails when a route has no `probeUrl`.** The gateway probe used to call
  `fetch(undefined)`, report a failure, and leave the button red without ever running a round for any
  deployment that had not configured a probe endpoint. With no endpoint to probe, the probe is now
  skipped and the round proceeds.

## [1.0.1] — 2026-09-25

Documentation and tooling only; no runtime change.

### Changed

- README rewritten in the project's standard layout. English and Chinese are mirrored: badge block,
  a worked panel sample, a how-it-works flow, three-column requirement tables, and a troubleshooting
  table.

### Added

- `README.i18n.yaml` — bilingual-pair consistency record (the git blob hash of each side).
- `.github/workflows/ci.yml` — syntax check plus the 23 host probes on Ubuntu and Windows, Node 24.
- `prepack` — `check` and `test:host` run before any pack or publish, so a package that fails either
  cannot ship.

## [1.0.0] — 2026-09-25

First public release.

### Added

- **Panel + resident session + HTTP contract.** The package owns the panel, one resident main-agent
  session, scheduled collection, and context rotation. It ships **no ingestion pipeline** — items are
  fed in over `POST /chat-feed/api/items`, so it is usable with or without one.
- **Config-driven everything.** `stateDir`, `agentCwd`, `agentPreset`, `wxRoot`, `fileRoots`, `localDir`
  and `routes` are all configuration; the source pins no machine path, no provider, no model and no
  probe endpoint. With no `routes` configured there is a single generic route that claims no provider.
- **Private content in exactly one folder.** A deployment's own wake prompt (`prompt.md`) and per-round
  instruction (`round.md`) live in `localDir` (`<package>/local` by default) — `.gitignore`d and outside
  the published `files` whitelist. Without them, generic built-in defaults are used.
- **One-time state migration that never deletes.** `state.json` and `panel.json` live under
  `%LOCALAPPDATA%\dsh-chat-digest\`; legacy locations are read once and left in place.
- **Self-checking and probes.** `tools/check_host_body.py` asserts named fragments of the authoritative
  host body (23 host probes + 6 pipeline probes). Probes never write into the repository they check.
- **Corruption quarantine.** A bad `state.json` is saved aside as `.corrupt-<timestamp>` rather than
  silently resetting the panel.

### Fixed

- A state-directory rename used to strand existing data: the migration source list now includes the
  pre-rename locations, so an upgrade recovers the panel items, the collection cursor and the custom
  panel structure instead of starting empty.
- Slot claiming now accepts the session titles used before the rename, so an upgrade reuses the
  existing slot sessions instead of silently creating duplicates.

### Known limitations

- Verified on **Windows only**.
- The HTTP prefix `/chat-feed/api/` does not match the package name; it is kept deliberately as a
  stable path contract for scripts already built against it.
- The slot state keys (`sessThu` / `sessParatera`) are historical field names meaning "slot of route
  1 / 2". Renaming them would require a state-schema migration.
