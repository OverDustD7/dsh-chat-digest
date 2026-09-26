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
function resolveLocalDir(config) {
  const cands = []
  if (config && typeof config.localDir === 'string' && config.localDir) cands.push(config.localDir)
  if (process.env.DSH_CHAT_FEED_LOCAL) cands.push(process.env.DSH_CHAT_FEED_LOCAL)
  cands.push(path.join(PKG_DIR, 'local'))
  for (const c of cands) {
    try { if (c && fs.statSync(c).isDirectory()) return c } catch (e) { /* 继续试下一个 */ }
  }
  return null
}

//: 读 local/ 下的一份文本（没有就返回空串，由函数体退到通用缺省）。
function readLocal(dir, name) {
  if (!dir) return ''
  try { return fs.readFileSync(path.join(dir, name), 'utf8') } catch (e) { return '' }
}

//: 传给函数体的部署配置：包内位置 ＋ local/ 里的私人内容 ＋ profile 这一行的 config（**config 优先**）。
//: 只放"函数体自己算不出来"的东西；别把凭据放进来（这个对象会进函数体作用域）。
function buildConfig(config) {
  const fromRow = (config && typeof config === 'object' && !Array.isArray(config)) ? config : {}
  const local = resolveLocalDir(config)
  // A34（2026-09-27）：把解析到的**个人目录导出到进程环境**，让子进程与宿主用同一个 profile 目录。
  //   主 agent 跑的是 `pipeline/*.py` 和 `tools/*.py`（独立进程），它们只能靠环境变量找到个人目录
  //   —— `pipeline/pconf.py` 读的就是 `DSH_CHAT_FEED_LOCAL`。以前只有宿主自己知道 localDir，
  //   工具侧于是各自写死了工作区绝对路径（这就是"通用化只做了一半"的根因）。这里补上这条桥。
  try { if (local) process.env.DSH_CHAT_FEED_LOCAL = local } catch (e) { /* 环境只读也不该让挂载失败 */ }
  const fromLocal = {
    localDir: local || '',
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
