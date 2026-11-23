import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../lib/plugin.js')
const base = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-chat-digest-portability-'))
const pkg = path.join(base, 'package')
const profile = path.join(base, 'private-profile')
const other = path.join(base, 'other-profile')
const oldEnv = process.env.DSH_CHAT_FEED_LOCAL
const envPyBefore = process.env.DSH_CHAT_FEED_PY

try {
  fs.mkdirSync(path.join(pkg, 'lib'), { recursive: true })
  fs.mkdirSync(path.join(pkg, 'prompt'), { recursive: true })
  fs.writeFileSync(path.join(pkg, 'package.json'), '{"type":"module"}')
  fs.copyFileSync(source, path.join(pkg, 'lib', 'plugin.js'))
  // plugin.js 现在 import './runtime.js'，mini 包必须带上它，否则加载就失败
  fs.copyFileSync(path.join(path.dirname(source), 'runtime.js'), path.join(pkg, 'lib', 'runtime.js'))
  fs.writeFileSync(path.join(pkg, 'lib', 'host-body.txt'),
    'return { apply() { globalThis.__digestTestConfig = CFG } };')
  fs.writeFileSync(path.join(pkg, 'prompt', 'prompt.md'), 'public prompt')
  fs.writeFileSync(path.join(pkg, 'prompt', 'round.md'), 'public round')
  fs.mkdirSync(profile)
  fs.writeFileSync(path.join(profile, 'prompt.md'), 'private prompt')

  const plugin = await import(pathToFileURL(path.join(pkg, 'lib', 'plugin.js')).href)
  // 私人目录、联接与追加语义。
  plugin.apply({}, { localDir: profile, pythonRuntime: 'legacy' })
  // A66：私人夹那份是**追加**（"本机补充"），不是整份替换 —— 包内规程必须仍在
  assert.match(globalThis.__digestTestConfig.wakeText, /public prompt/)
  assert.match(globalThis.__digestTestConfig.wakeText, /private prompt/)
  assert.equal(globalThis.__digestTestConfig.agentCwd, fs.realpathSync(profile))
  assert.equal(process.env.DSH_CHAT_FEED_LOCAL, fs.realpathSync(profile))
  assert.equal(fs.realpathSync(path.join(pkg, 'local')), fs.realpathSync(profile))
  assert.equal(fs.realpathSync(path.join(pkg, 'agent', 'output')),
    fs.realpathSync(path.join(profile, 'output')))
  assert.equal(fs.existsSync(path.join(profile, 'inbox', 'sample.txt')), false)
  // 2026-10-26：配置里撤掉 python 时，env 里不许留下上一次注入的解释器（重载同进程，env 不会自己复位）
  plugin.apply({}, { localDir: profile, pythonRuntime: 'legacy', python: 'X:/fake/python.exe' })
  assert.equal(process.env.DSH_CHAT_FEED_PY, 'X:/fake/python.exe')
  plugin.apply({}, { localDir: other, pythonRuntime: 'legacy' })
  assert.equal(process.env.DSH_CHAT_FEED_PY, envPyBefore)
  if (envPyBefore === undefined) assert.equal('DSH_CHAT_FEED_PY' in process.env, false)
  const originalErrorForCwd = console.error
  console.error = () => {}
  try {
    assert.throws(() => plugin.apply({}, { localDir: profile, pythonRuntime: 'legacy', agentCwd: pkg }),
      /agentCwd 必须与 localDir/)
  } finally {
    console.error = originalErrorForCwd
  }

  plugin.apply({}, { localDir: other, pythonRuntime: 'legacy' })
  assert.equal(globalThis.__digestTestConfig.wakeText, 'public prompt')
  assert.equal(globalThis.__digestTestConfig.agentCwd, fs.realpathSync(other))
  assert.equal(fs.realpathSync(path.join(pkg, 'local')), fs.realpathSync(other))
  // ── 包内 Python 模式（pythonRuntime: bundled）─────────────────────────────────
  // 合成的 runtime/<platform>-<arch>：假解释器只是普通文本文件，检查里从不执行它。
  const seg = process.platform + '-' + process.arch
  const rtDir = path.join(pkg, 'runtime', seg)
  const rtManifest = path.join(rtDir, 'manifest.json')
  const bundledPython = fs.realpathSync((() => {
    fs.mkdirSync(path.join(rtDir, 'python'), { recursive: true })
    fs.writeFileSync(rtManifest, JSON.stringify({
      schemaVersion: 1, platform: process.platform, arch: process.arch, python: 'python/python.exe',
    }))
    const fake = path.join(rtDir, 'python', 'python.exe')
    fs.writeFileSync(fake, 'not-executed')
    return fake
  })())

  // 旧 config.python 不许把 CFG.python 盖回去；环境里内外三处都要指向同一个包内文件
  plugin.apply({}, { localDir: profile, pythonRuntime: 'bundled', python: 'X:/stale/python.exe' })
  assert.equal(globalThis.__digestTestConfig.python, bundledPython)
  assert.equal(globalThis.__digestTestConfig.pythonRuntime, 'bundled')
  assert.equal(process.env.DSH_CHAT_FEED_PY, bundledPython)
  const bridge = JSON.parse(process.env.DSH_CHAT_FEED_BUNDLED_RUNTIME)
  assert.equal(bridge.schemaVersion, 1)
  assert.equal(bridge.python, bundledPython)
  assert.equal(bridge.root, fs.realpathSync(rtDir))

  // 公开缺省模式即使在有本地装配资产的机器也使用外置解释器，并清除旧桥。
  for (const absent of [undefined, null, '', '  ']) {
    plugin.apply({}, { localDir: profile, pythonRuntime: absent, python: 'X:/external/python.exe' })
    assert.equal(globalThis.__digestTestConfig.python, 'X:/external/python.exe')
    assert.equal(globalThis.__digestTestConfig.pythonRuntime, 'legacy')
    assert.equal(process.env.DSH_CHAT_FEED_PY, 'X:/external/python.exe')
    assert.equal('DSH_CHAT_FEED_BUNDLED_RUNTIME' in process.env, false)
  }

  // 缺 runtime 时明确失败，且在私人目录联接/环境变更之前失败（不当成 legacy）
  fs.rmSync(path.join(pkg, 'runtime'), { recursive: true, force: true })
  const missingError = (() => { try { plugin.apply({}, { localDir: profile, pythonRuntime: 'bundled' }); return null } catch (e) { return e } })()
  assert.ok(missingError, '缺 runtime 时应当抛错')
  assert.match(String(missingError.code || ''), /^E_RUNTIME_DIR_MISSING$/)
  // 没有运行时、没有显式解释器配置时也能挂载面板。
  plugin.apply({}, { localDir: profile })
  assert.equal(globalThis.__digestTestConfig.pythonRuntime, 'legacy')
  assert.equal('DSH_CHAT_FEED_BUNDLED_RUNTIME' in process.env, false)

  // 坏 manifest 同样明确失败，不回落
  fs.mkdirSync(path.join(rtDir, 'python'), { recursive: true })
  fs.writeFileSync(rtManifest, '{ not json')
  fs.writeFileSync(path.join(rtDir, 'python', 'python.exe'), 'not-executed')
  const brokenError = (() => { try { plugin.apply({}, { localDir: profile, pythonRuntime: 'bundled' }); return null } catch (e) { return e } })()
  assert.ok(brokenError, '坏 manifest 时应当抛错')
  assert.equal(brokenError.code, 'E_MANIFEST_JSON')

  // 未知模式明确报错，不猜
  assert.throws(() => plugin.apply({}, { localDir: profile, pythonRuntime: 'sometimes' }), /pythonRuntime/)

  // 显式 legacy：严格桥必须清掉，旧行为（配置 python → 环境）恢复
  fs.writeFileSync(rtManifest, JSON.stringify({
    schemaVersion: 1, platform: process.platform, arch: process.arch, python: 'python/python.exe',
  }))
  plugin.apply({}, { localDir: other, pythonRuntime: 'legacy' })
  assert.equal('DSH_CHAT_FEED_BUNDLED_RUNTIME' in process.env, false)
  assert.equal(process.env.DSH_CHAT_FEED_PY, envPyBefore)

  // pythonRuntime 的类型边界：只有没设/空串才算缺省，而缺省是 legacy；
  // true、1、对象这类错误类型一律报错，不静默降成任何一侧
  for (const bad of [true, false, 1, {}, ['bundled']]) {
    assert.throws(
      () => plugin.apply({}, { localDir: profile, pythonRuntime: bad }),
      /pythonRuntime/,
      'pythonRuntime=' + JSON.stringify(bad) + ' 应当报错',
    )
  }
  // 严格分支的环境写入失败必须让挂载失败，而不是返回一个"成功"的 CFG
  // 确保严格分支回滚前没有桥。
  plugin.apply({}, { localDir: other, pythonRuntime: 'legacy' })
  assert.equal('DSH_CHAT_FEED_BUNDLED_RUNTIME' in process.env, false)
  const realEnv = process.env
  let envSwapOk = false
  try {
    process.env = new Proxy(realEnv, {
      set(target, key, value) {
        if (key === 'DSH_CHAT_FEED_BUNDLED_RUNTIME') {
          const error = new Error('injected env failure')
          error.code = 'EACCES'
          throw error
        }
        target[key] = value
        return true
      },
    })
    envSwapOk = true
  } catch (e) {
    envSwapOk = false
  }
  if (envSwapOk) {
    try {
      let injected = null
      try {
        plugin.apply({}, { localDir: profile, pythonRuntime: 'bundled' })
      } catch (e) {
        injected = e
      }
      assert.ok(injected, '环境写入失败时不应挂载成功')
      assert.equal(injected.code, 'E_BUNDLED_ENV')
      assert.equal('DSH_CHAT_FEED_BUNDLED_RUNTIME' in process.env, false)
    } finally {
      process.env = realEnv
    }
    assert.equal(typeof process.env, 'object')
  } else {
    console.log('skip: 本机无法替换 process.env，已跳过严格模式环境失败注入')
  }

  // 切回 legacy 时内部键删不掉，必须明确失败（旧的空 catch 会假装已切回 legacy）
  plugin.apply({}, { localDir: profile, pythonRuntime: 'bundled' })
  assert.equal(typeof process.env.DSH_CHAT_FEED_BUNDLED_RUNTIME, 'string')
  const deleteEnvReal = process.env
  let deleteSwapOk = false
  try {
    process.env = new Proxy(deleteEnvReal, {
      // 必须显式转写 set：process.env 是 Node 的特殊对象，默认转发会带上不一样的 receiver，
      // 它只接受"可配置、可写、可枚举的数据描述符"，于是写值会抛 ERR_INVALID_OBJECT_DEFINE_PROPERTY。
      set(target, key, value) {
        target[key] = value
        return true
      },
      deleteProperty(target, key) {
        if (key === 'DSH_CHAT_FEED_BUNDLED_RUNTIME') {
          const error = new Error('injected delete failure')
          error.code = 'EACCES'
          throw error
        }
        return delete target[key]
      },
    })
    deleteSwapOk = true
  } catch (e) {
    deleteSwapOk = false
  }
  if (deleteSwapOk) {
    try {
      let clearError = null
      try {
        plugin.apply({}, { localDir: profile, pythonRuntime: 'legacy' })
      } catch (e) {
        clearError = e
      }
      assert.ok(clearError, '内部键删不掉时不应假装已切回 legacy')
      assert.equal(clearError.code, 'E_BUNDLED_ENV_CLEAR')
    } finally {
      process.env = deleteEnvReal
    }
    plugin.apply({}, { localDir: other, pythonRuntime: 'legacy' })
    assert.equal('DSH_CHAT_FEED_BUNDLED_RUNTIME' in process.env, false)
  } else {
    console.log('skip: 本机无法替换 process.env，已跳过 delete 失败注入')
  }

  const originalError = console.error
  console.error = () => {}
  try {
    assert.throws(() => plugin.apply({}, { localDir: path.join(pkg, 'unsafe') }),
      /私人 profile 不能放在插件包内/)
  } finally {
    console.error = originalError
  }
  console.log('portability: profile isolation, relink, private override and clean inbox OK')
} finally {
  if (oldEnv === undefined) delete process.env.DSH_CHAT_FEED_LOCAL
  else process.env.DSH_CHAT_FEED_LOCAL = oldEnv
  if (envPyBefore === undefined) delete process.env.DSH_CHAT_FEED_PY
  else process.env.DSH_CHAT_FEED_PY = envPyBefore
  delete process.env.DSH_CHAT_FEED_BUNDLED_RUNTIME
  delete globalThis.__digestTestConfig
  const rel = path.relative(os.tmpdir(), fs.realpathSync(base))
  if (rel && !rel.startsWith('..' + path.sep) && rel !== '..' && !path.isAbsolute(rel)) {
    fs.rmSync(base, { recursive: true, force: true })
  }
}
