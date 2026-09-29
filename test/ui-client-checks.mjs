// dsh-chat-digest · 浏览器半边（lib/client.js）的契约检查
//
// 为什么要有这个文件：2026-09-29 用户报「dsh 更新了，UI 需要更新」—— 0.1.7-rc.2 起侧栏的
// 「全局面板」改成槽位驱动（壳自己渲染行、点击走 layout.selectPanel），旧做法（宿主注入
// ui.js、脚本自己插行/抢主列）插不进那批行。改法是照官方模板走客户端插件 + 槽位注册。
//
// 本机**没有可用的浏览器 provider**（browser_open 报 "no usable browser provider is registered"），
// 真机 DOM 量不了 ⇒ 这份检查是「可重复的数值依据」：用最小桩件模拟壳的模块加载器、
// React 与槽位注册表，断言 lib/client.js 真的按契约注册、按契约挂载/卸载。
// 真机外观仍要人在页面上看一眼（本文件不替代那个）。
//
// 零依赖：不引 jsdom，自己搭需要的几个 DOM/React 面。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const PKG = path.dirname(HERE)
const results = []
function rec(name, ok, detail) { results.push({ name, ok: !!ok, detail: detail || '' }) }

// ── 1) 桩件：模块加载器 / React / DOM / 槽位注册表 ────────────────────────────────
let loaded = null
const effects = []
const React = {
  createElement(type, props, ...children) {
    return { type, props: props || {}, children: children.length > 1 ? children : children[0] }
  },
  useRef(init) { return { current: init === undefined ? null : init } },
  useEffect(fn) { effects.push(fn) },
}
const appended = []
const win = {
  __ModuleLoader__: { load(spec) { loaded = spec } },
  addEventListener() {}, removeEventListener() {},
}
const doc = {
  readyState: 'complete',
  head: { appendChild(node) { appended.push(node); if (node.onload) setTimeout(() => node.onload(), 0) } },
  createElement(tag) { return { tag, set src(v) { this._src = v }, get src() { return this._src } } },
  documentElement: { style: { setProperty() {} }, setAttribute() {}, removeAttribute() {}, hasAttribute() { return false } },
  querySelector() { return null },
  querySelectorAll() { return [] },
  addEventListener() {},
  body: { appendChild() {}, classList: { add() {}, remove() {} } },
}
globalThis.window = win
globalThis.document = doc
globalThis.setTimeout = setTimeout
globalThis.clearTimeout = clearTimeout
globalThis.setInterval = setInterval
globalThis.clearInterval = clearInterval
globalThis.localStorage = { getItem() { return null }, setItem() {} }

// ── 2) 载入 lib/client.js（它就是浏览器里被壳加载的那份）────────────────────────
const src = fs.readFileSync(path.join(PKG, 'lib', 'client.js'), 'utf8')
new Function('window', 'document', 'require', src)(win, doc, (id) => {
  if (id === 'react') return React
  throw new Error('未声明的运行时依赖：' + id)
})

rec('C01_client_registers_loader_entry', loaded !== null && loaded.id === 'dsh-chat-digest',
  loaded ? 'id=' + loaded.id : '没有调用 __ModuleLoader__.load')

const mod = loaded && typeof loaded.factory === 'function' ? loaded.factory((id) => (id === 'react' ? React : null)) : null
rec('C02_factory_returns_inject_and_apply', mod && Array.isArray(mod.inject) && typeof mod.apply === 'function',
  mod ? 'inject=' + JSON.stringify(mod.inject) : '工厂没有返回 {inject, apply}')
rec('C03_inject_covers_slots_and_layout',
  mod && mod.inject.indexOf('slots') >= 0 && mod.inject.indexOf('layout') >= 0,
  mod ? JSON.stringify(mod.inject) : '')

// ── 3) apply()：两个座位各注册一次，id/key 一致 ────────────────────────────────
const regs = []
const slots = {
  inject(seat, cb) { cb(); return () => {} },
  register(options, component) { regs.push({ options, component }); return () => {} },
}
const layoutCalls = []
const ctx = {
  slots,
  layout: { selectPanel: (id) => layoutCalls.push(id) },
  effect(fn) { const off = fn(); return off },
}
if (mod) mod.apply(ctx)

const row = regs.find((r) => r.options && r.options.name === 'sidebar.panellist')
const page = regs.find((r) => r.options && r.options.name === 'main')
rec('C04_registers_sidebar_panellist_row', !!row,
  row ? 'id=' + row.options.id + ' order=' + row.options.order : '没注册 sidebar.panellist')
rec('C05_registers_main_page_with_same_key',
  !!row && !!page && page.options.key === row.options.id,
  page ? 'key=' + page.options.key : '没注册 main')
rec('C06_row_label_and_glyph',
  !!row && typeof row.options.label === 'function' && row.options.label() === '聊天摘要'
  && typeof row.component === 'function' && !!row.component({ size: 16 }),
  row ? 'label=' + (typeof row.options.label === 'function' ? row.options.label() : row.options.label) : '')
rec('C07_page_id_matches_plugin_name', !!row && row.options.id === 'chat-digest', row ? row.options.id : '')

// ── 4) 页面挂载：取 ui.js → mountInto(容器, {selectPanel})；卸载调 unmount ────────
;(async () => {
  const mountCalls = []
  const unmountCalls = []
  win.__cfwUi = {
    mountInto: (el, api) => mountCalls.push({ el, api }),
    unmount: () => unmountCalls.push(1),
  }
  effects.length = 0
  const container = { tag: 'div', id: 'container' }
  const el = page.component({})
  el.props.ref.current = container
  effects.forEach((fn) => fn())
  await new Promise((r) => setTimeout(r, 20))
  rec('C08_page_mounts_ui_into_container', mountCalls.length === 1 && mountCalls[0].el === container,
    'mountInto 次数=' + mountCalls.length)
  rec('C09_mount_passes_selectPanel_back_to_shell',
    mountCalls.length === 1 && typeof mountCalls[0].api.selectPanel === 'function')
  if (mountCalls.length === 1) mountCalls[0].api.selectPanel(null)
  rec('C10_close_routes_through_shell_selectPanel', layoutCalls.length === 1 && layoutCalls[0] === null,
    'layout.selectPanel 调用=' + JSON.stringify(layoutCalls))

  // 卸载：React 卸载该页时应调 ui 的 unmount
  const cleanups = []
  effects.length = 0
  const el2 = page.component({})
  el2.props.ref.current = container
  effects.forEach((fn) => cleanups.push(fn()))
  cleanups.forEach((fn) => { try { fn() } catch (e) {} })
  rec('C11_page_unmount_releases_ui', unmountCalls.length >= 1, 'unmount 次数=' + unmountCalls.length)

  // ── 5) 静态面：ui.js 有承载模式；宿主不再注入 ui.js ──────────────────────────
  const ui = fs.readFileSync(path.join(PKG, 'lib', 'ui.js'), 'utf8')
  rec('C12_ui_has_hosted_mode',
    ui.includes('var HOST = null') && ui.includes('function hosted()')
    && /function ensureEntry\(\) \{\n\s*if \(hosted\(\)\) return/.test(ui),
    'HOST/hosted()/ensureEntry 提前返回')
  rec('C13_ui_exposes_mount_api',
    ui.includes('window.__cfwUi = {') && ui.includes('mountInto: function (container, api)')
    && ui.includes('unmount: function ()'), '')
  rec('C14_ui_does_not_take_over_when_hosted',
    ui.includes('if (!hosted()) {') && ui.includes("data-cfw-hosted"), 'VIEW_ATTR 与面板样式都分叉')
  const body = fs.readFileSync(path.join(PKG, 'lib', 'host-body.txt'), 'utf8')
  rec('C15_host_no_longer_injects_ui_js',
    !/indexOf\(SCRIPT_UI\)\s*<\s*0/.test(body) && /indexOf\(SCRIPT_RIGHT\)\s*<\s*0/.test(body),
    'ui.js 不再注入；right.js 照旧')

  // C16/C17：boot 竞态（2026-09-29 实测后果：侧栏两个「聊天摘要」、主区空白）
  //   ui.js 是"载入即 boot()"，而 HOST 要等 mountInto 才设 ⇒ 必须在**载入之前**告诉它"你被承载了"。
  const client = fs.readFileSync(path.join(PKG, 'lib', 'client.js'), 'utf8')
  const setHostedAt = client.indexOf('window.__cfwHosted = true')
  const appendAt = client.indexOf('document.head.appendChild(s)')
  rec('C16_client_flags_hosted_before_loading_ui',
    setHostedAt >= 0 && appendAt >= 0 && setHostedAt < appendAt,
    setHostedAt < 0 ? '没置 window.__cfwHosted' : '置位在 appendChild 之前')
  rec('C17_ui_honours_hosted_flag_and_null_host',
    ui.includes('window.__cfwHosted === true') && ui.includes('HOST ? HOST.container'),
    'hosted() 认标志位；ensurePanel 在 HOST 为空时不取属性')

  let bad = 0
  for (const r of results) {
    if (!r.ok) bad++
    console.log('%s %-44s %s', r.ok ? 'ok  ' : 'FAIL', r.name, r.detail)
  }
  console.log('\n%d/%d 通过 ｜ FAILS: %d', results.length - bad, results.length, bad)
  process.exit(bad ? 1 : 0)
})()
