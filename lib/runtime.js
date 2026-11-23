// lib/runtime.js —— 包内自包含运行时的**发现与结构校验**（只用 node 内置模块，零 npm 依赖）。
//
// 它只回答一件事：这个包自带的 runtime/<platform>-<arch>/manifest.json 在不在、结构自不自洽、
// 声明的解释器与工具文件是不是确实落在包内。它**不**回答解释器能不能执行、依赖是否齐全、
// 采集流程能不能跑通 —— 结构有效（found）只是后续构建与选择逻辑的前置条件。
//
// 判据边界（与 .migration/business-20261026-runtime/design.md 一致）：
//   · 没有 manifest 就是 absent，不回落系统解释器后仍声称自包含；
//   · manifest 存在但损坏、平台不符、声明文件缺失或越界，一律 invalid，不悄悄降级；
//   · 只有"确实不存在"（ENOENT / ENOTDIR）算 absent；权限或 I/O 失败是**访问失败**，归 invalid，
//     且错误里不带原始路径或 manifest 片段；
//   · 只接受显式相对的正斜杠路径；绝对路径、盘符、UNC、反斜杠、点点段一律拒绝；
//   · runtime 目录、manifest 与所列文件先 realpath，再核对是否仍在包内，联接/符号链接逃包外即 invalid；
//   · 不递归扫描、不做哈希、不读私人目录、不执行任何被声明的文件。
//
// 返回结构：
//   { status: 'absent',  code, platform, arch }
//   { status: 'invalid', code, field?, platform, arch }
//   { status: 'found',   platform, arch, runtimeDir, manifestPath, python, tools, structuralOnly: true }
//
// tools 用无原型对象承载：manifest 里 own property 名为 "__proto__" 的工具项也要逐一校验，
// 不能因为普通对象赋值被原型 setter 吞掉而漏检。

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/** 包根缺省值：本文件在 <包>/lib 下，所以上一级就是包根。 */
export function pkgRootFromModule() {
  return path.dirname(path.dirname(fileURLToPath(import.meta.url)))
}

const SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._-]*$/

function badArgument(message) {
  const error = new TypeError(message)
  error.code = 'E_RUNTIME_ARG'
  return error
}

/** platform / arch 只是路径段，先卡死再拼路径，别给"点点"留缝。 */
function assertSegment(value, name) {
  if (typeof value !== 'string' || !value) throw badArgument(name + ' 必须是非空字符串')
  if (value === '.' || value === '..' || !SEGMENT.test(value)) {
    throw badArgument(name + ' 不能用作路径段')
  }
  return value
}

/** 声明路径必须是显式相对、正斜杠、无点点段、无盘符/UNC/反斜杠。 */
function parseDeclaredPath(value, field) {
  const fail = (why) => {
    const error = new TypeError(field + ' ' + why)
    error.code = 'E_DECLARED_PATH'
    return error
  }
  if (typeof value !== 'string' || !value) throw fail('必须是非空字符串')
  if (value.includes('\u0000')) throw fail('含 NUL 字符')
  if (value.includes('\\')) throw fail('不许用反斜杠')
  if (value.startsWith('/')) throw fail('不许是绝对路径')
  if (/^[A-Za-z]:/.test(value)) throw fail('不许带盘符')
  if (value.startsWith('//')) throw fail('不许是 UNC 路径')
  const parts = value.split('/')
  for (const part of parts) {
    if (!part) throw fail('含空路径段')
    if (part === '.' || part === '..') throw fail('含点点段')
  }
  return parts.join('/')
}

function isInside(rootReal, targetReal) {
  const rel = path.relative(rootReal, targetReal)
  if (rel === '') return true
  if (path.isAbsolute(rel)) return false
  return rel !== '..' && !rel.startsWith('..' + path.sep)
}

function isMissingCode(code) {
  return code === 'ENOENT' || code === 'ENOTDIR'
}

/**
 * lstat 一次，把三种结果分开：拿到 stat、确实不存在、访问失败（权限/IO）。
 * 访问失败不能当成"不存在"，也不能把底层 message（含绝对路径）往上抛。
 */
function statKind(target) {
  try {
    return { stat: fs.lstatSync(target) }
  } catch (error) {
    const code = (error && error.code) || 'EIO'
    if (isMissingCode(code)) return { missing: true }
    return { failed: code }
  }
}

function invalid(code, field, platform, arch) {
  const out = { status: 'invalid', code, platform, arch }
  if (field) out.field = field
  return out
}

/**
 * 发现并校验包内运行时。
 *
 * @param {object} [options]
 * @param {string} [options.pkgRoot] 包根；缺省取模块所在包
 * @param {string} [options.platform] 覆盖 platform（合成检查用）；缺省 process.platform
 * @param {string} [options.arch] 覆盖 arch；缺省 process.arch
 */
export function discoverRuntime(options = {}) {
  const pkgRootInput = options.pkgRoot == null ? pkgRootFromModule() : String(options.pkgRoot)
  const platform = assertSegment(options.platform == null ? process.platform : options.platform, 'platform')
  const arch = assertSegment(options.arch == null ? process.arch : options.arch, 'arch')

  if (!path.isAbsolute(pkgRootInput)) throw badArgument('pkgRoot 必须是绝对路径')

  let pkgReal
  try {
    pkgReal = fs.realpathSync(pkgRootInput)
  } catch (error) {
    const code = (error && error.code) || 'EIO'
    // 整棵目录被搬走 = 这里没有运行时；权限/IO 失败 = 访问失败，另行报。
    if (isMissingCode(code)) return { status: 'absent', code: 'E_PKG_MISSING', platform, arch }
    return invalid('E_PKG_UNREADABLE', null, platform, arch)
  }

  const runtimeDirUnreal = path.join(pkgReal, 'runtime', platform + '-' + arch)
  const dirKind = statKind(runtimeDirUnreal)
  if (dirKind.missing) return { status: 'absent', code: 'E_RUNTIME_DIR_MISSING', platform, arch }
  if (dirKind.failed) return invalid('E_RUNTIME_DIR_UNREADABLE', null, platform, arch)

  // 先核 realpath 是否还在包内，再判类型：runtime/<seg> 本身可能就是指向包外的联接，
  // 若先按 lstat 判 isDirectory，会把"逃逸"误报成"不是目录"。
  let runtimeReal
  try {
    runtimeReal = fs.realpathSync(runtimeDirUnreal)
  } catch (error) {
    return invalid('E_RUNTIME_DIR_UNREADABLE', null, platform, arch)
  }
  if (!isInside(pkgReal, runtimeReal)) return invalid('E_RUNTIME_DIR_ESCAPE', null, platform, arch)
  try {
    if (!fs.statSync(runtimeReal).isDirectory()) return invalid('E_RUNTIME_DIR_NOT_DIR', null, platform, arch)
  } catch (error) {
    return invalid('E_RUNTIME_DIR_UNREADABLE', null, platform, arch)
  }

  const manifestUnreal = path.join(runtimeReal, 'manifest.json')
  const manifestKind = statKind(manifestUnreal)
  if (manifestKind.missing) return { status: 'absent', code: 'E_MANIFEST_MISSING', platform, arch }
  if (manifestKind.failed) return invalid('E_MANIFEST_UNREADABLE', 'manifest.json', platform, arch)

  let manifestReal
  try {
    manifestReal = fs.realpathSync(manifestUnreal)
  } catch (error) {
    return invalid('E_MANIFEST_UNREADABLE', 'manifest.json', platform, arch)
  }
  if (!isInside(pkgReal, manifestReal)) return invalid('E_MANIFEST_ESCAPE', 'manifest.json', platform, arch)
  try {
    if (!fs.statSync(manifestReal).isFile()) return invalid('E_MANIFEST_NOT_FILE', 'manifest.json', platform, arch)
  } catch (error) {
    return invalid('E_MANIFEST_UNREADABLE', 'manifest.json', platform, arch)
  }

  let raw
  try {
    raw = fs.readFileSync(manifestReal, 'utf8')
  } catch (error) {
    return invalid('E_MANIFEST_UNREADABLE', 'manifest.json', platform, arch)
  }

  let manifest
  try {
    // Windows 上手工写/工具导出的 JSON 常带 UTF-8 BOM；JSON.parse 不吃它，先剥掉再解析。
    if (raw.charCodeAt(0) === 0xfeff) raw = raw.slice(1)
    manifest = JSON.parse(raw)
  } catch (error) {
    return invalid('E_MANIFEST_JSON', 'manifest.json', platform, arch)
  }
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) {
    return invalid('E_MANIFEST_SHAPE', null, platform, arch)
  }
  if (manifest.schemaVersion !== 1) return invalid('E_SCHEMA_VERSION', 'schemaVersion', platform, arch)
  if (manifest.platform !== platform) return invalid('E_PLATFORM_MISMATCH', 'platform', platform, arch)
  if (manifest.arch !== arch) return invalid('E_ARCH_MISMATCH', 'arch', platform, arch)

  let pythonRel
  try {
    pythonRel = parseDeclaredPath(manifest.python, 'python')
  } catch (error) {
    return invalid('E_PYTHON_PATH', 'python', platform, arch)
  }

  let toolsIn = null
  if (manifest.tools != null) {
    if (typeof manifest.tools !== 'object' || Array.isArray(manifest.tools)) {
      return invalid('E_TOOLS_TYPE', 'tools', platform, arch)
    }
    toolsIn = manifest.tools
  }

  // 无原型对象：JSON.parse 得到的 own property "__proto__" 在这里会被当成普通键存下来，
  // 后面 Object.keys 才能把它列出来逐一校验（普通对象会被原型 setter 吞掉）。
  const toolsRel = Object.create(null)
  if (toolsIn) {
    for (const name of Object.keys(toolsIn)) {
      if (!name) return invalid('E_TOOL_NAME', 'tools', platform, arch)
      try {
        toolsRel[name] = parseDeclaredPath(toolsIn[name], 'tools.' + name)
      } catch (error) {
        return invalid('E_TOOL_PATH', 'tools.' + name, platform, arch)
      }
    }
  }

  const resolveDeclared = (relValue, field, codes) => {
    const unreal = path.join(runtimeReal, ...relValue.split('/'))
    const kind = statKind(unreal)
    if (kind.missing) return { error: invalid(codes.missing, field, platform, arch) }
    if (kind.failed) return { error: invalid(codes.unreadable, field, platform, arch) }
    let real
    try {
      real = fs.realpathSync(unreal)
    } catch (error) {
      const code = (error && error.code) || 'EIO'
      return { error: invalid(isMissingCode(code) ? codes.missing : codes.unreadable, field, platform, arch) }
    }
    if (!isInside(pkgReal, real)) return { error: invalid(codes.escape, field, platform, arch) }
    let st
    try {
      st = fs.statSync(real)
    } catch (error) {
      const code = (error && error.code) || 'EIO'
      return { error: invalid(isMissingCode(code) ? codes.missing : codes.unreadable, field, platform, arch) }
    }
    if (!st.isFile()) return { error: invalid(codes.notFile, field, platform, arch) }
    return { abs: real }
  }

  const pythonResult = resolveDeclared(pythonRel, 'python', {
    missing: 'E_PYTHON_MISSING',
    unreadable: 'E_PYTHON_UNREADABLE',
    escape: 'E_PYTHON_ESCAPE',
    notFile: 'E_PYTHON_NOT_FILE',
  })
  if (pythonResult.error) return pythonResult.error

  const toolsAbs = Object.create(null)
  for (const name of Object.keys(toolsRel)) {
    const result = resolveDeclared(toolsRel[name], 'tools.' + name, {
      missing: 'E_TOOL_MISSING',
      unreadable: 'E_TOOL_UNREADABLE',
      escape: 'E_TOOL_ESCAPE',
      notFile: 'E_TOOL_NOT_FILE',
    })
    if (result.error) return result.error
    toolsAbs[name] = result.abs
  }

  return {
    status: 'found',
    platform,
    arch,
    runtimeDir: runtimeReal,
    manifestPath: manifestReal,
    python: pythonResult.abs,
    tools: toolsAbs,
    structuralOnly: true,
  }
}
