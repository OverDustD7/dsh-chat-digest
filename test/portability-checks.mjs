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

try {
  fs.mkdirSync(path.join(pkg, 'lib'), { recursive: true })
  fs.mkdirSync(path.join(pkg, 'prompt'), { recursive: true })
  fs.writeFileSync(path.join(pkg, 'package.json'), '{"type":"module"}')
  fs.copyFileSync(source, path.join(pkg, 'lib', 'plugin.js'))
  fs.writeFileSync(path.join(pkg, 'lib', 'host-body.txt'),
    'return { apply() { globalThis.__digestTestConfig = CFG } };')
  fs.writeFileSync(path.join(pkg, 'prompt', 'prompt.md'), 'public prompt')
  fs.writeFileSync(path.join(pkg, 'prompt', 'round.md'), 'public round')
  fs.mkdirSync(profile)
  fs.writeFileSync(path.join(profile, 'prompt.md'), 'private prompt')

  const plugin = await import(pathToFileURL(path.join(pkg, 'lib', 'plugin.js')).href)
  plugin.apply({}, { localDir: profile })
  // A66：私人夹那份是**追加**（"本机补充"），不是整份替换 —— 包内规程必须仍在
  assert.match(globalThis.__digestTestConfig.wakeText, /public prompt/)
  assert.match(globalThis.__digestTestConfig.wakeText, /private prompt/)
  assert.equal(globalThis.__digestTestConfig.agentCwd, fs.realpathSync(profile))
  assert.equal(process.env.DSH_CHAT_FEED_LOCAL, fs.realpathSync(profile))
  assert.equal(fs.realpathSync(path.join(pkg, 'local')), fs.realpathSync(profile))
  assert.equal(fs.realpathSync(path.join(pkg, 'agent', 'output')),
    fs.realpathSync(path.join(profile, 'output')))
  assert.equal(fs.existsSync(path.join(profile, 'inbox', 'sample.txt')), false)
  const originalErrorForCwd = console.error
  console.error = () => {}
  try {
    assert.throws(() => plugin.apply({}, { localDir: profile, agentCwd: pkg }),
      /agentCwd 必须与 localDir/)
  } finally {
    console.error = originalErrorForCwd
  }

  plugin.apply({}, { localDir: other })
  assert.equal(globalThis.__digestTestConfig.wakeText, 'public prompt')
  assert.equal(globalThis.__digestTestConfig.agentCwd, fs.realpathSync(other))
  assert.equal(fs.realpathSync(path.join(pkg, 'local')), fs.realpathSync(other))
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
  delete globalThis.__digestTestConfig
  const rel = path.relative(os.tmpdir(), fs.realpathSync(base))
  if (rel && !rel.startsWith('..' + path.sep) && rel !== '..' && !path.isAbsolute(rel)) {
    fs.rmSync(base, { recursive: true, force: true })
  }
}
