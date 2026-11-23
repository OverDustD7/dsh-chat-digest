// test/runtime-discovery-checks.mjs —— 包内运行时发现契约的合成检查（临时目录，零外部依赖）。
//
// 只验结构契约：absent / invalid / found 的分界、路径格式拒绝、联接逃逸拒绝、整体移动后仍可发现。
// 假 python 是不执行的文本文件；全程没有真实 Python、没有依赖、没有网络。
// 清理前先确认临时根确实落在本次创建的系统临时目录下，且不跟随任何联接。

import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { mock } from 'node:test'
import { discoverRuntime } from '../lib/runtime.js'

const tmpBase = fs.realpathSync(os.tmpdir())
const root = fs.realpathSync(fs.mkdtempSync(path.join(tmpBase, 'dsh-chat-digest-runtime-')))
const outside = path.join(root, 'outside')
fs.mkdirSync(outside, { recursive: true })

let passed = 0
let failed = 0
const skipped = []

function check(name, fn) {
  try {
    fn()
    passed += 1
    process.stdout.write('ok   ' + name + '\n')
  } catch (error) {
    failed += 1
    process.stdout.write('FAIL ' + name + ' :: ' + ((error && error.message) || error) + '\n')
  }
}

function writeFile(target, content) {
  fs.mkdirSync(path.dirname(target), { recursive: true })
  fs.writeFileSync(target, content, 'utf8')
}

function writeManifest(pkg, segment, manifest) {
  writeFile(path.join(pkg, 'runtime', segment, 'manifest.json'), JSON.stringify(manifest, null, 2))
}

function baseManifest(overrides = {}) {
  return { schemaVersion: 1, platform: 'linux', arch: 'x64', python: 'python/python.exe', ...overrides }
}

// 一个结构完整的合成包：manifest + 假解释器 + 一个工具
function makeValidPkg(name, segment = 'linux-x64') {
  const pkg = path.join(root, name)
  writeManifest(pkg, segment, baseManifest({ tools: { 'example-tool': 'tools/example/entry.py' } }))
  writeFile(path.join(pkg, 'runtime', segment, 'python', 'python.exe'), '#!/bin/sh\nexit 0\n')
  writeFile(path.join(pkg, 'runtime', segment, 'tools', 'example', 'entry.py'), 'print("noop")\n')
  return pkg
}

check('没装运行时：absent，不回落', () => {
  const pkg = path.join(root, 'empty-pkg')
  fs.mkdirSync(pkg, { recursive: true })
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(result.status, 'absent')
  assert.equal(result.code, 'E_RUNTIME_DIR_MISSING')
})

check('运行时目录在但缺 manifest：absent（只有这一种 absent）', () => {
  const pkg = path.join(root, 'no-manifest')
  fs.mkdirSync(path.join(pkg, 'runtime', 'linux-x64'), { recursive: true })
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(result.status, 'absent')
  assert.equal(result.code, 'E_MANIFEST_MISSING')
})

check('合法结构：found，且只声明结构有效', () => {
  const pkg = makeValidPkg('valid-pkg')
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(result.status, 'found')
  assert.equal(result.structuralOnly, true)
  assert.ok(fs.statSync(result.python).isFile())
  assert.deepEqual(Object.keys(result.tools), ['example-tool'])
})

check('整体搬走之后仍能发现（路径全部相对包）', () => {
  const pkg = makeValidPkg('relocatable-pkg')
  const moved = path.join(root, 'relocated', 'deeper', 'pkg')
  fs.mkdirSync(path.dirname(moved), { recursive: true })
  fs.renameSync(pkg, moved)
  const before = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(before.status, 'absent')
  assert.equal(before.code, 'E_PKG_MISSING')
  const after = discoverRuntime({ pkgRoot: moved, platform: 'linux', arch: 'x64' })
  assert.equal(after.status, 'found')
  assert.ok(fs.statSync(after.python).isFile())
})

check('平台不符：invalid', () => {
  const pkg = makeValidPkg('platform-mismatch')
  const dir = path.join(pkg, 'runtime', 'linux-x64', 'manifest.json')
  fs.writeFileSync(dir, JSON.stringify(baseManifest({ platform: 'win32' })), 'utf8')
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(result.status, 'invalid')
  assert.equal(result.code, 'E_PLATFORM_MISMATCH')
})

check('架构不符：invalid', () => {
  const pkg = makeValidPkg('arch-mismatch')
  fs.writeFileSync(path.join(pkg, 'runtime', 'linux-x64', 'manifest.json'),
    JSON.stringify(baseManifest({ arch: 'arm64' })), 'utf8')
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(result.status, 'invalid')
  assert.equal(result.code, 'E_ARCH_MISMATCH')
})

check('schemaVersion 不是 1：invalid', () => {
  const pkg = makeValidPkg('schema-version')
  fs.writeFileSync(path.join(pkg, 'runtime', 'linux-x64', 'manifest.json'),
    JSON.stringify(baseManifest({ schemaVersion: 2 })), 'utf8')
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(result.status, 'invalid')
  assert.equal(result.code, 'E_SCHEMA_VERSION')
})

check('manifest 不是 JSON：invalid，不静默当 absent', () => {
  const pkg = makeValidPkg('bad-json')
  fs.writeFileSync(path.join(pkg, 'runtime', 'linux-x64', 'manifest.json'), '{ not json', 'utf8')
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(result.status, 'invalid')
  assert.equal(result.code, 'E_MANIFEST_JSON')
})

check('声明的解释器文件缺失：invalid', () => {
  const pkg = makeValidPkg('python-missing')
  fs.rmSync(path.join(pkg, 'runtime', 'linux-x64', 'python'), { recursive: true, force: true })
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(result.status, 'invalid')
  assert.equal(result.code, 'E_PYTHON_MISSING')
})

check('声明的解释器是目录：invalid，不把目录当解释器', () => {
  const pkg = makeValidPkg('python-is-dir')
  const seg = path.join(pkg, 'runtime', 'linux-x64')
  fs.rmSync(path.join(seg, 'python', 'python.exe'), { force: true })
  fs.mkdirSync(path.join(seg, 'python', 'python.exe'), { recursive: true })
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(result.status, 'invalid')
  assert.equal(result.code, 'E_PYTHON_NOT_FILE')
})

check('声明的工具文件缺失：invalid', () => {
  const pkg = makeValidPkg('tool-missing')
  fs.rmSync(path.join(pkg, 'runtime', 'linux-x64', 'tools'), { recursive: true, force: true })
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(result.status, 'invalid')
  assert.equal(result.code, 'E_TOOL_MISSING')
  assert.equal(result.field, 'tools.example-tool')
})

check('非法声明路径：绝对/盘符/UNC/反斜杠/点点段全部拒绝', () => {
  const cases = [
    ['/usr/bin/python3', 'E_PYTHON_PATH'],
    ['C:/tmp/python.exe', 'E_PYTHON_PATH'],
    ['\\\\server\\share\\python.exe', 'E_PYTHON_PATH'],
    ['python\\python.exe', 'E_PYTHON_PATH'],
    ['../python.exe', 'E_PYTHON_PATH'],
    ['python/../../escape.exe', 'E_PYTHON_PATH'],
    ['python//python.exe', 'E_PYTHON_PATH'],
  ]
  cases.forEach(([declared, expected], index) => {
    const pkg = makeValidPkg('bad-path-' + index)
    writeManifest(pkg, 'linux-x64', baseManifest({ python: declared }))
    const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
    assert.equal(result.status, 'invalid', 'declared=' + declared)
    assert.equal(result.code, expected, 'declared=' + declared)
  })
})

check('platform/arch 参数被当作路径段校验，点点不能逃逸', () => {
  const pkg = makeValidPkg('bad-segment')
  assert.throws(() => discoverRuntime({ pkgRoot: pkg, platform: '..', arch: 'x64' }), /platform/)
  assert.throws(() => discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: '../x64' }), /arch/)
  assert.throws(() => discoverRuntime({ pkgRoot: pkg, platform: 'linux/x64', arch: 'x64' }), /platform/)
})

check('runtime 目录是指向包外的联接：invalid', () => {
  const pkg = makeValidPkg('runtime-escape-src')
  const outsideRuntime = path.join(outside, 'runtime-outside')
  writeFile(path.join(outsideRuntime, 'manifest.json'), JSON.stringify(baseManifest()))
  writeFile(path.join(outsideRuntime, 'python', 'python.exe'), '#!/bin/sh\nexit 0\n')
  fs.renameSync(path.join(pkg, 'runtime', 'linux-x64'), path.join(pkg, 'runtime', 'linux-x64-keep'))
  let linked = false
  try {
    fs.symlinkSync(outsideRuntime, path.join(pkg, 'runtime', 'linux-x64'), 'junction')
    linked = true
  } catch (error) {
    skipped.push('runtime 联接逃逸（创建联接失败：' + error.code + '）')
  }
  if (linked) {
    const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
    assert.equal(result.status, 'invalid')
    assert.equal(result.code, 'E_RUNTIME_DIR_ESCAPE')
  }
})

function tryLink(kind, target, linkPath) {
  try {
    fs.symlinkSync(target, linkPath, kind)
    return true
  } catch (error) {
    return error.code || 'EPERM'
  }
}

const manifestEscape = (() => {
  const pkg = makeValidPkg('manifest-escape')
  const outsideManifest = path.join(outside, 'manifest.json')
  writeFile(outsideManifest, JSON.stringify(baseManifest()))
  fs.rmSync(path.join(pkg, 'runtime', 'linux-x64', 'manifest.json'), { force: true })
  const linked = tryLink('file', outsideManifest, path.join(pkg, 'runtime', 'linux-x64', 'manifest.json'))
  return { pkg, linked }
})()
if (manifestEscape.linked === true) {
  check('manifest.json 是指向包外的联接：invalid', () => {
    const result = discoverRuntime({ pkgRoot: manifestEscape.pkg, platform: 'linux', arch: 'x64' })
    assert.equal(result.status, 'invalid')
    assert.equal(result.code, 'E_MANIFEST_ESCAPE')
  })
} else {
  skipped.push('manifest 联接逃逸（本机无法创建文件符号链接：' + manifestEscape.linked + '）')
}

const pythonEscape = (() => {
  const pkg = makeValidPkg('python-escape')
  const outsidePython = path.join(outside, 'outside-python.exe')
  writeFile(outsidePython, '#!/bin/sh\nexit 0\n')
  fs.rmSync(path.join(pkg, 'runtime', 'linux-x64', 'python', 'python.exe'), { force: true })
  const linked = tryLink('file', outsidePython, path.join(pkg, 'runtime', 'linux-x64', 'python', 'python.exe'))
  return { pkg, linked }
})()
if (pythonEscape.linked === true) {
  check('声明的 python 是指向包外的联接：invalid', () => {
    const result = discoverRuntime({ pkgRoot: pythonEscape.pkg, platform: 'linux', arch: 'x64' })
    assert.equal(result.status, 'invalid')
    assert.equal(result.code, 'E_PYTHON_ESCAPE')
  })
} else {
  skipped.push('python 联接逃逸（本机无法创建文件符号链接：' + pythonEscape.linked + '）')
}

check('own "__proto__" 工具项：目标缺失时必须 invalid，不能 found', () => {
  const pkg = path.join(root, 'proto-tool-missing')
  const seg = path.join(pkg, 'runtime', 'linux-x64')
  fs.mkdirSync(path.join(seg, 'python'), { recursive: true })
  fs.writeFileSync(path.join(seg, 'manifest.json'),
    '{"schemaVersion":1,"platform":"linux","arch":"x64","python":"python/python.exe",'
    + '"tools":{"__proto__":"tools/missing.py"}}', 'utf8')
  fs.writeFileSync(path.join(seg, 'python', 'python.exe'), '#!/bin/sh\nexit 0\n', 'utf8')
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.notEqual(result.status, 'found')
  assert.equal(result.status, 'invalid')
  assert.ok(['E_TOOL_MISSING', 'E_TOOL_NAME', 'E_TOOL_PATH'].includes(result.code), 'code=' + result.code)
})

check('own "__proto__" 工具项：目标存在时也要真的收进来', () => {
  const pkg = path.join(root, 'proto-tool-present')
  const seg = path.join(pkg, 'runtime', 'linux-x64')
  fs.mkdirSync(path.join(seg, 'python'), { recursive: true })
  fs.mkdirSync(path.join(seg, 'tools'), { recursive: true })
  fs.writeFileSync(path.join(seg, 'manifest.json'),
    '{"schemaVersion":1,"platform":"linux","arch":"x64","python":"python/python.exe",'
    + '"tools":{"__proto__":"tools/entry.py"}}', 'utf8')
  fs.writeFileSync(path.join(seg, 'python', 'python.exe'), '#!/bin/sh\nexit 0\n', 'utf8')
  fs.writeFileSync(path.join(seg, 'tools', 'entry.py'), 'print(1)\n', 'utf8')
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(result.status, 'found')
  assert.deepEqual(Object.keys(result.tools), ['__proto__'])
  assert.equal(path.basename(result.tools['__proto__']), 'entry.py')
})

check('读取 manifest 遇到 EACCES：invalid 且不回显原始路径', () => {
  const pkg = makeValidPkg('io-manifest')
  const patched = mock.method(fs, 'readFileSync', () => {
    const error = new Error('denied by synthetic fault injection')
    error.code = 'EACCES'
    throw error
  })
  try {
    const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
    assert.equal(result.status, 'invalid')
    assert.equal(result.code, 'E_MANIFEST_UNREADABLE')
    assert.equal(JSON.stringify(result).includes(root), false)
  } finally {
    patched.mock.restore()
  }
})

check('lstat 遇到 EACCES：invalid，不当成 absent', () => {
  const pkg = makeValidPkg('io-lstat')
  const patched = mock.method(fs, 'lstatSync', () => {
    const error = new Error('denied by synthetic fault injection')
    error.code = 'EACCES'
    throw error
  })
  try {
    const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
    assert.equal(result.status, 'invalid')
    assert.equal(result.code, 'E_RUNTIME_DIR_UNREADABLE')
    assert.equal(JSON.stringify(result).includes(root), false)
  } finally {
    patched.mock.restore()
  }
})

check('假解释器不会被本检查执行', () => {
  const pkg = path.join(root, 'no-exec')
  writeManifest(pkg, 'linux-x64', baseManifest())
  const marker = path.join(root, 'EXECUTED.marker')
  writeFile(path.join(pkg, 'runtime', 'linux-x64', 'python', 'python.exe'),
    '#!/bin/sh\ntouch "' + marker.replace(/\\/g, '/') + '"\n')
  const result = discoverRuntime({ pkgRoot: pkg, platform: 'linux', arch: 'x64' })
  assert.equal(result.status, 'found')
  assert.equal(fs.existsSync(marker), false)
})

// 清理：只允许删除本次 mkdtemp 实际创建、且当前 realpath 仍等于它的那一个目录。
// 系统临时根本身、根外的路径、realpath 已经变了的路径，一律拒绝删除。
const createdDir = root
const realRoot = fs.realpathSync(createdDir)
const stillTheSameDir = realRoot === createdDir
const strictlyInsideTmp = realRoot !== tmpBase && realRoot.startsWith(tmpBase + path.sep)
if (!stillTheSameDir || !strictlyInsideTmp) {
  process.stdout.write('清理跳过：目标不是本次创建的唯一临时子目录（' + realRoot + '）\n')
} else {
  fs.rmSync(realRoot, { recursive: true, force: true })
  process.stdout.write('清理完成：' + (fs.existsSync(realRoot) ? '仍存在' : '已删除') + '\n')
}

process.stdout.write('\n通过 ' + passed + ' / 失败 ' + failed + (skipped.length ? ' / 跳过 ' + skipped.length : '') + '\n')
skipped.forEach((item) => process.stdout.write('skip ' + item + '\n'))
process.exitCode = failed ? 1 : 0
