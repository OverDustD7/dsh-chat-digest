// dsh-chat-digest · 常驻（静态）Host 插件入口
//
// 跑在**真实宿主进程**里（重启仍在、不需要审批）：
//   读权威函数体 → `new Function('CFG', text)(cfg)` 求值 → 调它的 apply(ctx, config)
// 权威源码＝**本包** `lib/host-body.txt`；这里不复制内容，避免两份漂移。
//
// 发布化（A15，2026-09-25）：
//   · Host 函数体在包内（`lib/host-body.txt`）⇒ `npm pack` 出来的包**自带**它需要的东西
//   · 本机路径（数据目录 / 主 agent 工作区 / 微信附件根 / DSH 家）由这里算好，通过 `CFG` 传给函数体；
//     profile 里这一行的 `config` 可以覆盖其中任何一个（也可覆盖 bodyPath）
//   · 函数体解析顺序：`config.bodyPath` > 环境变量 `DSH_CHAT_FEED_BODY` > 包内 `lib/host-body.txt`
//   详见 README「配置」一节与 docs/DATA-DEPENDENCIES.md。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))   // <pkg>/lib
const PKG_DIR = path.dirname(HERE)                          // <pkg>
//: 包内权威源码（与这个文件同目录）。**它是包的一部分**，所以换机器不必改任何绝对路径。
const BODY_IN_PKG = path.join(HERE, 'host-body.txt')

export const name = 'dsh-chat-digest'
export const inject = ['webServer', 'connection']

let cached = null

//: 按优先级给出候选路径 → 返回第一个存在的；一个都没有时返回 null（由调用方**响亮地**报错）。
export function resolveBodyPath(config) {
  const cands = []
  if (config && typeof config.bodyPath === 'string' && config.bodyPath) cands.push(config.bodyPath)
  if (process.env.DSH_CHAT_FEED_BODY) cands.push(process.env.DSH_CHAT_FEED_BODY)
  cands.push(BODY_IN_PKG)
  for (const c of cands) {
    try { if (fs.existsSync(c)) return c } catch (e) { /* 继续试下一个 */ }
  }
  return null
}

//: 部署方的私人内容目录（提示词等）。**发布包里没有它**：别人装完就没有 local/，用函数体内的通用缺省。
//: 解析顺序：`config.localDir` > 环境变量 `DSH_CHAT_FEED_LOCAL` > `<包>/local`。
//: 之所以支持 config/env：从 npm 装进来时包目录在 `~/.dsh/profiles/<p>/node_modules/` 下，
//: 私人内容不该放那儿（重装就没了）——指到一个自己固定的目录更稳。
function privateRoot(config) {
  //: **私人文件夹**（A36 定案）：插件自己的稳定数据目录 —— 提示词/配置/产物/知识库/归档/面板状态都在里面。
  //:   为什么不放包内：`dsh plugin add <包>@<版本>` 会**整体重建包目录**，放包里每次更新都被清掉。
  //:   解析顺序：config.localDir → $DSH_CHAT_FEED_LOCAL → <用户 AppData>\dsh-chat-digest → 包内 local/。
  const cands = []
  if (config && typeof config.localDir === 'string' && config.localDir) cands.push(config.localDir)
  if (process.env.DSH_CHAT_FEED_LOCAL) cands.push(process.env.DSH_CHAT_FEED_LOCAL)
  const appdata = process.env.LOCALAPPDATA
    || (process.env.USERPROFILE ? path.join(process.env.USERPROFILE, 'AppData', 'Local') : '')
  if (appdata) cands.push(path.join(appdata, 'dsh-chat-digest'))
  cands.push(path.join(PKG_DIR, 'local'))
  for (const c of cands) {
    try { if (c && fs.statSync(c).isDirectory()) return c } catch (e) { /* 试下一个 */ }
  }
  for (const c of cands) {
    try { fs.mkdirSync(c, { recursive: true }); return c } catch (e) { /* 试下一个 */ }
  }
  return null
}

//: 读 local/ 下的一份文本（没有就返回空串，由函数体退到通用缺省）。
function readLocal(dir, name) {
  if (!dir) return ''
  try { return fs.readFileSync(path.join(dir, name), 'utf8') } catch (e) { return '' }
}

//: A34（2026-09-27）：把**个人目录**里的几块挂进 agent 树，让工具的既有相对路径
//:   （`agent/output`、`agent/docs/knowledge`、`agent/docs/archive`）直接落到个人目录
//:   —— 65 个工具里那 300 多处路径**一个字都不用改**。
//:   为什么做成运行时创建而不是预置：联接指向的是某个人的数据，进仓库或 npm 包会把数据一起带上。
//:   失败不致命：那几处退化成包内普通目录（照样能跑，只是数据落在包里、重装会丢）。
//: A35（2026-09-27）：个人文件**就在插件目录里**（`<包>/local` 配置、`<包>/agent/{output,docs/knowledge,docs/archive}` 数据），
//:   所以不再需要把外面某个目录联进 agent 树 —— 插件目录之外一个文件都不碰。
//:   这里只保证 `<包>/local` 这个位置存在（不存在时 `{profile}` 会渲染成空串）。
function seedPrivate(root) {
  //: 私人文件夹里缺什么就从包里播种什么（包内的 examples/ 是**通用模板**，不含任何个人信息）
  const seeds = [
    [path.join(root, 'prompt.md'), path.join(PKG_DIR, 'examples', 'local', 'prompt.md')],
    [path.join(root, 'round.md'), path.join(PKG_DIR, 'examples', 'local', 'round.md')],
    [path.join(root, 'inbox', 'sample.txt'), path.join(PKG_DIR, 'examples', 'inbox', 'sample.txt')],
  ]
  for (const [dst, src] of seeds) {
    try {
      if (fs.existsSync(dst) || !fs.existsSync(src)) continue
      fs.mkdirSync(path.dirname(dst), { recursive: true })
      fs.copyFileSync(src, dst)
    } catch (e) { /* 只读安装：跳过 */ }
  }
}

//: 把私人文件夹里那三块**联接到包内的既有相对路径**上（`agent/output`、`docs/knowledge`、`docs/archive`），
//: 这样 65 个工具里那 300 多处相对路径一个字都不用改；联接目标在会话 cwd（＝私人文件夹）之内，
//: 所以主 agent 通过这些联接写入是**被允许的**（DSH 沙箱按 realpath 判定）。
function linkPrivateIntoAgent(root) {
  if (!root) return
  const pairs = [
    [path.join(PKG_DIR, 'local'), root],                                      // A38：插件目录下的 local/ ＝私人 profile
    [path.join(PKG_DIR, 'profile'), root],                                    //     别名，方便按名字找
    [path.join(PKG_DIR, 'agent', 'output'), path.join(root, 'output')],
    [path.join(PKG_DIR, 'agent', 'docs', 'knowledge'), path.join(root, 'knowledge')],
    [path.join(PKG_DIR, 'agent', 'docs', 'archive'), path.join(root, 'archive')],
  ]
  const norm = (x) => String(x || '').replace(/^\\\\\?\\/, '')
  try { root = fs.realpathSync(root) } catch (e) { /* 用原样 */ }
  for (const [link, target] of pairs) {
    try {
      fs.mkdirSync(target, { recursive: true })
      let st = null
      try { st = fs.lstatSync(link) } catch (e) { st = null }
      if (st) {
        if (st.isSymbolicLink()) {
          const cur = norm(fs.readlinkSync(link))
          if (path.resolve(cur) === path.resolve(target)) continue
          fs.unlinkSync(link)
        } else if (fs.readdirSync(link).length === 0) {
          fs.rmdirSync(link)
        } else {
          console.warn('[dsh-chat-digest] ' + link + ' 是包内真实目录且非空 —— 不删，跳过联接；数据请挪到 ' + target)
          continue
        }
      }
      fs.mkdirSync(path.dirname(link), { recursive: true })
      fs.symlinkSync(target, link, 'junction')
    } catch (e) {
      console.warn('[dsh-chat-digest] 建联接失败 ' + link + ' -> ' + target + '：' + ((e && e.message) || e))
    }
  }
}

//: 传给函数体的部署配置：包内位置 ＋ local/ 里的私人内容 ＋ profile 这一行的 config（**config 优先**）。
//: 只放"函数体自己算不出来"的东西；别把凭据放进来（这个对象会进函数体作用域）。
function buildConfig(config) {
  const fromRow = (config && typeof config === 'object' && !Array.isArray(config)) ? config : {}
  const realRoot = privateRoot(config)          // 物理真身（包外：npm/插件更新不动它）
  let local = realRoot
  if (realRoot) {
    seedPrivate(realRoot)
    linkPrivateIntoAgent(realRoot)
    // A38（2026-09-27）：对外一律用**插件目录下的 local/**（提示词里的 {profile}、会话 cwd、
    //   DSH_CHAT_FEED_LOCAL 都用它）—— 路径上"私人文件就在插件目录里"，真身在包外。
    const shown = path.join(PKG_DIR, 'local')
    try { if (fs.statSync(shown).isDirectory()) local = shown } catch (e) { /* 建不出来就退回真身 */ }
  }
  // A34（2026-09-27）：把解析到的**个人目录导出到进程环境**，让子进程与宿主用同一个 profile 目录。
  //   主 agent 跑的是 `pipeline/*.py` 和 `tools/*.py`（独立进程），它们只能靠环境变量找到个人目录
  //   —— `pipeline/pconf.py` 读的就是 `DSH_CHAT_FEED_LOCAL`。以前只有宿主自己知道 localDir，
  //   工具侧于是各自写死了工作区绝对路径（这就是"通用化只做了一半"的根因）。这里补上这条桥。
  try { if (local) process.env.DSH_CHAT_FEED_LOCAL = local } catch (e) { /* 环境只读也不该让挂载失败 */ }
  // A35：把插件配置里的 python 也导给子进程 —— 管线脚本 pconf.python_exe() 读它，缺省才回退到 PATH 里的 python
  try { const py = (fromRow && typeof fromRow.python === 'string') ? fromRow.python : ''; if (py) process.env.DSH_CHAT_FEED_PY = py } catch (e) { /* 同上 */ }
  const fromLocal = {
    localDir: local || '',
    //: A36：主 agent 的会话 cwd ＝ **私人文件夹**（它的工作区；可写边界就是这里）
    //:   包内 agent 树留给只读的说明书与工具箱；显式配 agentCwd 仍然优先（Object.assign 里 fromRow 在后）
    agentCwd: local || '',
    wakeText: readLocal(local, 'prompt.md'),
    roundText: readLocal(local, 'round.md'),
  }
  return Object.assign({ dir: HERE + path.sep, pkgDir: PKG_DIR }, fromLocal, fromRow)
}

function loadBody(config) {
  if (cached) return cached
  const file = resolveBodyPath(config)
  if (!file) {
    // **不要静默**：报出"应该配哪个路径"，而不是让调用方看到一个看不懂的 ENOENT。
    throw new Error('找不到 Host 函数体。请设 config.bodyPath 或环境变量 DSH_CHAT_FEED_BODY，'
      + '包内默认位置是 ' + BODY_IN_PKG)
  }
  const text = fs.readFileSync(file, 'utf8')
  const plugin = new Function('CFG', text)(buildConfig(config))
  cached = { file, text, plugin }
  return cached
}

export function apply(ctx, config) {
  try {
    const { file, text, plugin } = loadBody(config)
    if (!plugin || typeof plugin.apply !== 'function') throw new Error('求值结果不是插件（缺 apply）')
    console.log('[dsh-chat-digest] 常驻加载：%s（函数体 %d 字符）', file, text.length)
    plugin.apply(ctx, config)
    console.log('[dsh-chat-digest] 常驻挂载完成')
  } catch (e) {
    console.error('[dsh-chat-digest] 常驻加载失败：', e)
  }
}
