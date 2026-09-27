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

//: 私人内容始终放在包外稳定目录，重装插件不会覆盖。
//: 解析顺序：`config.localDir` > `DSH_CHAT_FEED_LOCAL` > `DSH_HOME/dsh-chat-digest` > AppData。
function privateRoot(config) {
  //: **私人文件夹**（A36 定案）：插件自己的稳定数据目录 —— 提示词/配置/产物/知识库/归档/面板状态都在里面。
  //:   为什么不放包内：`dsh plugin add <包>@<版本>` 会**整体重建包目录**，放包里每次更新都被清掉。
  //:   解析顺序：config.localDir → $DSH_CHAT_FEED_LOCAL → $DSH_HOME/dsh-chat-digest → AppData。
  const home = process.env.DSH_HOME
    || (process.env.USERPROFILE ? path.join(process.env.USERPROFILE, '.dsh') : '')
  const appdata = process.env.LOCALAPPDATA
    || (process.env.USERPROFILE ? path.join(process.env.USERPROFILE, 'AppData', 'Local') : '')
  const selected = (config && typeof config.localDir === 'string' && config.localDir)
    || process.env.DSH_CHAT_FEED_LOCAL
    || (home && path.join(home, 'dsh-chat-digest'))
    || (appdata && path.join(appdata, 'dsh-chat-digest'))
  if (!selected || !path.isAbsolute(selected)) {
    throw new Error('私人 profile 需要稳定的绝对路径：请设置 config.localDir 或 DSH_HOME')
  }
  fs.mkdirSync(selected, { recursive: true })
  const real = fs.realpathSync(selected)
  const rel = path.relative(PKG_DIR, real)
  if (!rel || (!rel.startsWith('..' + path.sep) && rel !== '..' && !path.isAbsolute(rel))) {
    throw new Error('私人 profile 不能放在插件包内：' + selected)
  }
  return real
}

//: 读 local/ 下的一份文本（没有就返回空串，由函数体退到通用缺省）。
function readLocal(dir, name) {
  if (!dir) return ''
  try { return fs.readFileSync(path.join(dir, name), 'utf8') } catch (e) { return '' }
}

//: A66：包内规程 + 私人补充（**追加**，不是替换）。两边都可能为空。
function appendLocal(base, extra) {
  const b = String(base || '').trim()
  const e = String(extra || '').trim()
  if (!e) return b
  if (!b) return e
  return b + '\n\n<!-- 以下为本机补充（私人 profile，不随包发布） -->\n' + e
}

//: 包内联接只供旧路径兼容；所有写入代码使用私人目录的物理路径。
//: 联接失败时立即报错，避免私人数据意外写进包内。
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
          throw new Error(link + ' 是非空真实目录；请先迁移其中的数据到 ' + target)
        }
      }
      fs.mkdirSync(path.dirname(link), { recursive: true })
      fs.symlinkSync(target, link, 'junction')
    } catch (e) {
      throw new Error('建私人目录联接失败 ' + link + ' -> ' + target + '：' + ((e && e.message) || e), { cause: e })
    }
  }
}

//: 传给函数体的部署配置：包内位置 ＋ local/ 里的私人内容 ＋ profile 这一行的 config（**config 优先**）。
//: 只放"函数体自己算不出来"的东西；别把凭据放进来（这个对象会进函数体作用域）。
function buildConfig(config) {
  const fromRow = (config && typeof config === 'object' && !Array.isArray(config)) ? config : {}
  const realRoot = privateRoot(config)          // 物理真身（包外：npm/插件更新不动它）
  if (realRoot) {
    linkPrivateIntoAgent(realRoot)
  }
  // A34（2026-09-27）：把解析到的**个人目录导出到进程环境**，让子进程与宿主用同一个 profile 目录。
  //   主 agent 跑的是 `pipeline/*.py` 和 `tools/*.py`（独立进程），它们只能靠环境变量找到个人目录
  //   —— `pipeline/pconf.py` 读的就是 `DSH_CHAT_FEED_LOCAL`。以前只有宿主自己知道 localDir，
  //   工具侧于是各自写死了工作区绝对路径（这就是"通用化只做了一半"的根因）。这里补上这条桥。
  process.env.DSH_CHAT_FEED_LOCAL = realRoot
  // A35：把插件配置里的 python 也导给子进程 —— 管线脚本 pconf.python_exe() 读它，缺省才回退到 PATH 里的 python
  try { const py = (fromRow && typeof fromRow.python === 'string') ? fromRow.python : ''; if (py) process.env.DSH_CHAT_FEED_PY = py } catch (e) { /* 同上 */ }
  const fromLocal = {
    localDir: realRoot,
    //: A36：主 agent 的会话 cwd ＝ **私人文件夹**（它的工作区；可写边界就是这里）
    //:   包内 agent 树留给只读的说明书与工具箱；显式配 agentCwd 仍然优先（Object.assign 里 fromRow 在后）
    agentCwd: realRoot,
    // A66（2026-09-27）：**通用规程在包内，私人夹只放"本机差异"，两者是"追加"关系不是"覆盖"关系。**
    //   为什么要改（用户当场戳破）：原来私人夹同名文件会**整份替换**包内那份 ⇒ 想给本机加一行身份/
    //   偏好，就得把整套规程抄一遍；结果 140 行 + 23 行的**产品本体**住进了私人夹，陌生人下载到的
    //   只剩 11 行/10 行的空壳 —— "别人下载后能用"当场不成立。
    //   现在：包内 `prompt/` 是规程本体（随包发、走门禁），私人夹那份是**本机补充**，追加在后面。
    //   判据（切"通用/私人"的界线）＝**对任何人都成立**（规程、判据、口径）vs 只有这台机器成立
    //   （身份、偏好、私人名单、本机路径）。要整份替换就不能走这条路（那等于把产品搬回私人夹）。
    wakeText: appendLocal(readLocal(path.join(PKG_DIR, 'prompt'), 'prompt.md'), readLocal(realRoot, 'prompt.md')),
    roundText: appendLocal(readLocal(path.join(PKG_DIR, 'prompt'), 'round.md'), readLocal(realRoot, 'round.md')),
  }
  const cfg = Object.assign({ dir: HERE + path.sep, pkgDir: PKG_DIR }, fromLocal, fromRow)
  cfg.localDir = realRoot
  cfg.agentCwd = fs.realpathSync(cfg.agentCwd)
  if (cfg.agentCwd !== realRoot) {
    throw new Error('agentCwd 必须与 localDir 指向同一私人目录；请只配置 localDir')
  }
  return cfg
}

function loadBody(config) {
  const file = resolveBodyPath(config)
  if (!file) {
    // **不要静默**：报出"应该配哪个路径"，而不是让调用方看到一个看不懂的 ENOENT。
    throw new Error('找不到 Host 函数体。请设 config.bodyPath 或环境变量 DSH_CHAT_FEED_BODY，'
      + '包内默认位置是 ' + BODY_IN_PKG)
  }
  const text = fs.readFileSync(file, 'utf8')
  const plugin = new Function('CFG', text)(buildConfig(config))
  return { file, text, plugin }
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
    throw e
  }
}
