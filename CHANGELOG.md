# Changelog

All notable changes to this package. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
