// dsh-chat-digest · 侧栏那一行（lib/client.js）的契约检查
//
// 背景（2026-09-29 两次返工）：dsh 升到 0.1.7-rc.2 后侧栏「全局面板」改成槽位驱动，
// 脚本自己往侧栏塞的行样式对不上（用户：「没有融入啊，样式都不一样」）；但**面板本身仍旧走旧路径**
// （宿主注入 ui.js，ui.js 自己抢 centerCol）—— 那一版能用，不能被这次改动碰到。
// 所以本文件钉住两件事：①侧栏行**只**由槽位注册、并且点了走旧面板；②ui.js 在壳给了行时不再自己插行。
//
// 本机没有可用的浏览器 provider（browser_open 报 "no usable browser provider is registered"），
// 真机量不了 ⇒ 这份检查就是可重复的数值依据。零依赖，不引 jsdom。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const PKG = path.dirname(HERE)
const results = []
function rec(name, ok, detail) { results.push({ name, ok: !!ok, detail: detail || '' }) }

// ── 桩件 ───────────────────────────────────────────────────────────────────────
let loaded = null
const effects = []
const staleNode = { parentNode: { removeChild() { staleNode.removed = true } } }
staleNode.removed = false
const React = {
  createElement(type, props, ...children) { return { type, props: props || {}, children: children.length > 1 ? children : children[0] } },
  useRef(init) { return { current: init === undefined ? null : init } },
  useEffect(fn) { effects.push(fn) },
}
const win = { __ModuleLoader__: { load(spec) { loaded = spec } }, addEventListener() {}, removeEventListener() {} }
const doc = {
  readyState: 'complete',
  head: { appendChild() {} },
  createElement(tag) { return { tag } },
  querySelectorAll() { return [staleNode] },
  querySelector() { return null },
  documentElement: { hasAttribute() { return false } },
  addEventListener() {},
  body: {},
}
globalThis.window = win
globalThis.document = doc

const src = fs.readFileSync(path.join(PKG, 'lib', 'client.js'), 'utf8')
new Function('window', 'document', 'require', src)(win, doc, (id) => {
  if (id === 'react') return React
  throw new Error('未声明的运行时依赖：' + id)
})

rec('C01_client_registers_loader_entry', loaded !== null && loaded.id === 'dsh-chat-digest',
  loaded ? 'id=' + loaded.id : '没调用 __ModuleLoader__.load')
const mod = loaded ? loaded.factory((id) => (id === 'react' ? React : null)) : null
rec('C02_factory_returns_inject_and_apply', !!mod && Array.isArray(mod.inject) && typeof mod.apply === 'function',
  mod ? 'inject=' + JSON.stringify(mod.inject) : '工厂没返回 {inject, apply}')
rec('C03_inject_covers_slots_and_layout',
  !!mod && mod.inject.indexOf('slots') >= 0 && mod.inject.indexOf('layout') >= 0, '')

// ── apply()：注册、置标志、清旧行 ───────────────────────────────────────────────
const regs = []
// 桥用的假服务（形状照壳：`sessions.list.getSnapshot()` 有 ids/byId，行上有 retainedBy.mainView）。
const openedSessions = []
const sessionsSnap = {
  phase: 'ready',
  ids: ['s-other', 's-user', 's-archived'],
  byId: {
    's-other': { id: 's-other', retainedBy: {} },
    's-user': { id: 's-user', retainedBy: { mainView: 1 } },
    's-archived': { id: 's-archived', retainedBy: {} },
  },
}
const ctx = {
  slots: { inject(seat, cb) { cb(); return () => {} }, register(options, component) { regs.push({ options, component }); return () => {} } },
  layout: { selectPanel() {} },
  effect(fn) { fn(); return () => {} },
  // 服务只在**调用时**取（写进 inject 会让 apply pending ⇒ 侧栏那一行消失，这是 2026-09-29 踩过的坑）。
  get(name) {
    if (name === 'sessions') return { list: { getSnapshot: () => sessionsSnap } }
    if (name === 'workspaces') return { list: { getSnapshot: () => ({ archivedSessionIds: ['s-archived'] }) } }
    if (name === 'uiWorkspace') return { openSession(id) { openedSessions.push(id) } }
    return undefined
  },
}
if (mod) mod.apply(ctx)
const row = regs.find((r) => r.options && r.options.name === 'sidebar.panellist')
const page = regs.find((r) => r.options && r.options.name === 'main')
rec('C04_registers_one_panellist_row_with_label',
  !!row && row.options.id === 'chat-digest' && typeof row.options.order === 'number'
  && typeof row.options.label === 'function' && row.options.label() === '聊天摘要',
  row ? 'id=' + row.options.id + ' order=' + row.options.order : '没注册 sidebar.panellist')
rec('C05_registers_main_with_same_key_so_select_is_legal',
  !!row && !!page && page.options.key === row.options.id, page ? 'key=' + page.options.key : '没注册 main')
rec('C06_apply_flags_ui_to_skip_its_own_row', win.__cfwSidebarRow === true, 'window.__cfwSidebarRow=' + win.__cfwSidebarRow)
rec('C07_apply_removes_stale_injected_row', staleNode.removed === true, '旧行是否被摘掉=' + staleNode.removed)

// ── 图标点击：阻止冒泡（别让壳 selectPanel）+ 走旧面板 ────────────────────────────
let stopped = 0, prevented = 0, opened = 0
win.__cfwUi = { openPanel() { opened++ } }
const glyph = row.component({ size: 16 })
glyph.props.onClick({ preventDefault() { prevented++ }, stopPropagation() { stopped++ } })
rec('C08_glyph_click_uses_legacy_panel_and_stops_bubble',
  stopped === 1 && prevented === 1 && opened === 1,
  'stopPropagation=' + stopped + ' preventDefault=' + prevented + ' openPanel=' + opened)

// ── 会话导航桥（#95）：ui.js 的「返回」在"目标那一行没渲染"时靠它按 id 回去 ──────────
const nav = win.__cfwNav
rec('C20_nav_bridge_reads_current_session_and_refuses_dead_ids',
  !!nav && nav.current() === 's-user'
  && nav.ok('s-user') === true && nav.ok('s-archived') === false && nav.ok('nope') === false && nav.ok('') === false,
  nav ? 'current=' + nav.current() + ' ok(s-user)=' + nav.ok('s-user') + ' ok(已归档)=' + nav.ok('s-archived') : '没有 window.__cfwNav')
rec('C21_nav_bridge_opens_by_id_and_stays_out_of_inject',
  !!nav && mod.inject.indexOf('sessions') < 0 && mod.inject.indexOf('uiWorkspace') < 0
  && src.includes('ctx.get(name)')
  && nav.open('s-user') === true && openedSessions.join(',') === 's-user' && nav.open('') === false,
  (nav ? 'openSession=' + JSON.stringify(openedSessions) : '没有 window.__cfwNav') + ' inject=' + JSON.stringify(mod.inject))

// ── 静态面：ui.js 的口子与"壳给了行就别自己插" ────────────────────────────────
const ui = fs.readFileSync(path.join(PKG, 'lib', 'ui.js'), 'utf8')
rec('C09_ui_exposes_open_panel_hook',
  ui.includes('window.__cfwUi = {') && ui.includes('openPanel: openPanel'), '')
rec('C10_ui_skips_own_row_when_shell_provides_one',
  /window\.__cfwSidebarRow === true\) \{ ensureShellRowMore\(\); return \}/.test(ui),
  '壳给了行：不再自己插行，只补 ⋯')
// 壳的行是 React 渲染的，⋯ 是外来的；被冲掉要能补回来，且补的时候必须幂等（观察器会反复调）。
rec('C12_ui_restores_the_more_button_idempotently',
  ui.includes('function ensureShellRowMore()')
  && ui.includes("row.querySelector('.cfw-more2') !== null")
  && ui.includes('querySelector(\'[data-dsh-panel-entry="chat-digest"]\')'),
  '⋯ 幂等补回（拿我们图标上的标记反查壳的行）')
rec('C13_cleanup_only_removes_our_own_row',
  /entryRow\.getAttribute\(ENT_ATTR\) !== null\) entryRow\.parentNode\.removeChild/.test(ui),
  'cleanup 不会删掉壳渲染的那一行')
// 壳的面板列表是带 gap 的 flex 列：折叠区那个 0 高度的盒子也白占一个 gap（用户报「巨大缝隙」）；
// 展开时父列的 row-gap 会在它上下各留一次 ⇒ 还要用负 margin 抵掉，才能贴住入口行。
rec('C14_collapsed_expander_leaves_no_flex_gap_in_shell_mode',
  ui.includes('function syncAccDisplay()')
  && ui.includes("accEl.style.display = 'none'")
  && ui.includes("if (!shellMode()) { accEl.style.display = ''; accEl.style.marginTop = ''; accEl.style.marginBottom = ''; return }"),
  '折叠时摘出布局；非壳模式一字未改')
rec('C16_expander_compensates_parent_row_gap',
  ui.includes('function parentRowGap()') && ui.includes('accEl.style.marginTop = neg')
  && ui.includes('accEl.style.marginBottom = neg'), '用父列 row-gap 的负 margin 贴住入口行')
// 2026-09-29 真机实测：折叠区从 display:none 展开时自身宽度是变的（252→256）⇒ **不能量它自己**；
// 必须用两个稳定盒子（父列的可用宽度 vs 行的宽度）算差，否则当场量到 0 差、左右各多出 2px。
rec('C17_expander_aligns_by_parent_row_boxes_not_its_own_rect',
  ui.includes('var baseL = parR.left + (parseFloat(pcs.paddingLeft) || 0)')
  && ui.includes('var baseR = parR.right - (parseFloat(pcs.paddingRight) || 0)')
  && ui.includes('var dl = +(rowR.left - baseL).toFixed(1)')
  && !ui.includes('__cfwAccDbg'),
  '按父列/行算；且没有留下临时调试')
// 返回（2026-09-29 用户报「返回的逻辑怎么又坏了」）：首页那行「新会话」**也会**被标 aria-selected=true，
// 必须排除；否则返回时满侧栏找一个叫"新会话"的 sessionRow，找不到就放弃，人被丢在常驻会话里。
// 真机实测两个场景：会话→面板→返回 = 回那个会话；首页→面板→返回 = 回首页。
// 2026-09-29 二改（用户："返回的逻辑怎么又坏了…你什么测试得到的会回原会话的结论"）：`goHome()` 点的是壳的
// 「新会话」按钮，**点下去会新建一个会话**，所以只有"确证进来前是首页"才允许调它；"会话行没渲染出来"
// （工作区折叠着）看起来也像"没有选中会话"，但它**不是首页** —— 两个信号必须分开，且其余一律保持 6 次重试。
rec('C18_back_from_home_returns_home_not_stuck_in_agent_session',
  ui.includes('var prevWasHome = false')
  && ui.includes('newSessionLabel.indexOf(t1) === 0 || t1.indexOf(newSessionLabel) === 0')
  && ui.includes('prevWasHome = true')
  && ui.includes('if (prevWasHome) { goHome(); return }')
  && ui.includes("if (!prevSessionTitle || prevSessionTitle.indexOf('主 Agent') >= 0) return")
  && ui.includes('var maxTries = 6')
  && ui.includes('function goHome()')
  && !ui.includes('__cfwBk') && !ui.includes('__cfwSb'),
  '确证是首页才回首页、其余绝不点「新会话」、保持 6 次重试；无埋点')
// A101（2026-10-01 用户报「图片显示不出来」）：`.cfw-img` 只有 `max-width:100%; height:auto`，
// 未加载时盒子高度 0 ⇒ 带 `loading="lazy"` 就"离视口太远"永不加载、高度仍是 0（自锁）。
// 实测：面板里那个 img 永远 naturalWidth=0 / complete=false，而同一 URL 新建一个 img 立刻 1080×1920。
// 钉住：内嵌图**不许再带 lazy**，且仍走 `/api/file`（要字节）。
const rightJs = fs.readFileSync(path.join(PKG, 'lib', 'right.js'), 'utf8')
rec('C23_embedded_image_is_not_lazy_loaded',
  rightJs.includes('class="cfw-img"') && !/class="cfw-img"[^>]*loading="lazy"/.test(rightJs)
  && rightJs.includes("'/chat-feed/api/file?p=' + encodeURIComponent(t)"),
  '内嵌图不带 lazy（懒加载 + 零高度会自锁）、且仍走 /api/file')
// #95（2026-09-29 用户报"返回的逻辑怎么又坏了"的真凶）：还原原来**只**按侧栏标题找那一行，而
// **工作区收起时 DSH 不渲染它的会话行** ⇒ 找满 6 次也找不到，人被丢在聊天摘要的常驻会话里。
// 现在 ui.js 优先用壳的 id 导航（不看 DOM），桥由 lib/client.js 提供；取不到就退回标题匹配。
// ⚠ 首页（新会话）**也**走 id 这条路：真机实测面板开着时点壳的「新会话」按钮**不生效**
//   （onDocClick 先按 keepNav 把面板关掉，主区仍停在聊天摘要会话里）⇒ 那颗按钮只能当兜底。
rec('C19_back_uses_session_id_before_title_matching',
  ui.includes("var prevSessionId = ''")
  && ui.includes('prevSessionId = navCurrentId()')
  && ui.includes('if (prevSessionId && navIdOk(prevSessionId) && navOpenId(prevSessionId))')
  && ui.includes('else restoreByTitle()')
  && ui.includes('function restoreByTitle()')
  && ui.indexOf('navIdOk(prevSessionId)') < ui.indexOf('function restoreByTitle()')
  && ui.indexOf('navIdOk(prevSessionId)') < ui.indexOf('if (prevWasHome) { goHome(); return }')
  && ui.includes("prevSessionTitle = ''; prevSessionId = ''")
  && ui.includes('prevSessionId === ownId'),
  'id 那条路排在标题匹配与 goHome 之前（首页同样先走 id）；keepNav/已在常驻会话时不还原')
rec('C15_close_keeps_the_transition_then_drops_the_box',
  ui.includes('accCloseTimer')
  && /setTimeout\(function \(\) \{ accCloseTimer = null; syncAccDisplay\(\) \}, 320\)/.test(ui),
  '收起先跑完过渡，320ms 后再摘盒子')
const body = fs.readFileSync(path.join(PKG, 'lib', 'host-body.txt'), 'utf8')
rec('C11_host_still_injects_ui_js',
  /indexOf\(SCRIPT_UI\)\s*<\s*0/.test(body), '面板路径没被动过')

// 埋点不许留：不只查具体的几个名字，而是把两半里所有 `__cfw*` 全局**逐一列出来对白名单**。
// 2026-09-29 教训：我复现「返回回不去」时埋了 `__cfwSb` / `__cfwDbg`，删的时候靠人眼找 ——
// 改成"新名字不登记就红"，谁再埋点谁负责登记或删掉。
const CFW_OK = {
  'lib/ui.js': ['__cfwFetchChat', '__cfwNav', '__cfwOpenSession', '__cfwRight', '__cfwSidebarRow', '__cfwUi', '__cfwWired'],
  'lib/client.js': ['__cfwNav', '__cfwSidebarRow', '__cfwUi'],
}
const stray = []
for (const [rel, allowed] of Object.entries(CFW_OK)) {
  const text = fs.readFileSync(path.join(PKG, rel), 'utf8')
  for (const name of new Set(text.match(/__cfw[A-Za-z0-9_]+/g) || [])) {
    if (allowed.indexOf(name) < 0) stray.push(rel + ':' + name)
  }
}
rec('C22_no_unregistered_debug_globals', stray.length === 0,
  stray.length ? '未登记的埋点：' + stray.join(', ') : '两半里的 __cfw* 全在白名单内')

let bad = 0
for (const r of results) { if (!r.ok) bad++; console.log('%s %-52s %s', r.ok ? 'ok  ' : 'FAIL', r.name, r.detail) }
console.log('\n%d/%d 通过 ｜ FAILS: %d', results.length - bad, results.length, bad)
process.exit(bad ? 1 : 0)
