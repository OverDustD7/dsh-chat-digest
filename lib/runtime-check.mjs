#!/usr/bin/env node
// lib/runtime-check.mjs —— 只读 preflight：报告包内自包含运行时的发现结果，输出精简 JSON。
//
// 它与 lib/runtime.js 同目录，随包发布（lib 本就在 package.json 的 files 里）。
// 只做结构检查：manifest 在不在、是否自洽、声明的文件是否落在包内。
// 不执行解释器、不探测 PATH、不读私人配置、不写任何文件。
// 退出码：0 = found，3 = absent，4 = invalid，2 = 参数错误。

import path from 'node:path'
import { discoverRuntime, pkgRootFromModule } from './runtime.js'

const USAGE = `runtime-check —— 包内运行时结构检查（只读，不执行任何被声明的文件）

用法：
  node lib/runtime-check.mjs [--pkg <dir>] [--platform <p>] [--arch <a>]

  --pkg <dir>      包根；缺省为脚本所在包
  --platform <p>   覆盖 platform（合成检查用），缺省取 process.platform
  --arch <a>       覆盖 arch，缺省取 process.arch
  -h, --help       显示本说明

输出：一行 JSON，字段随结果变化（status/code/platform/arch 以及 found 时的相对路径）。
退出码：0 found｜3 absent｜4 invalid｜2 参数错误

注意：found 只表示声明与所列文件在结构上成立，不代表解释器可执行、依赖齐全或采集能跑通。`

const USAGE_CODES = {
  help: 0,
  args: 2,
}

function emit(payload) {
  process.stdout.write(JSON.stringify(payload) + '\n')
}

function usageError(code, message) {
  emit({ status: 'usage-error', code, message })
  process.exit(USAGE_CODES.args)
}

function parseArgs(argv) {
  const out = { pkg: null, platform: null, arch: null, help: false }
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i]
    if (token === '-h' || token === '--help') {
      out.help = true
      continue
    }
    if (token === '--pkg' || token === '--platform' || token === '--arch') {
      const value = argv[i + 1]
      if (value == null || value.startsWith('--')) {
        return { error: { code: 'E_ARG_VALUE', message: token + ' 需要一个值' } }
      }
      out[token.slice(2)] = value
      i += 1
      continue
    }
    return { error: { code: 'E_ARG_UNKNOWN', message: '未知参数：' + token } }
  }
  return out
}

function toRel(root, target) {
  const rel = path.relative(root, target)
  return rel.split(path.sep).join('/')
}

const parsed = parseArgs(process.argv.slice(2))
if (parsed.error) usageError(parsed.error.code, parsed.error.message)

if (parsed.help) {
  process.stdout.write(USAGE + '\n')
  process.exit(USAGE_CODES.help)
}

const pkgRoot = path.resolve(parsed.pkg || pkgRootFromModule())

let result
try {
  result = discoverRuntime({
    pkgRoot,
    ...(parsed.platform ? { platform: parsed.platform } : {}),
    ...(parsed.arch ? { arch: parsed.arch } : {}),
  })
} catch (error) {
  // 只有参数层面的错误会走到这里；消息里不含任何绝对路径。
  const code = (error && error.code) || 'E_RUNTIME_ARG'
  usageError(code, (error && error.message) || '参数错误')
}

const base = { platform: result.platform, arch: result.arch }

if (result.status === 'found') {
  const tools = Object.keys(result.tools || {})
  emit({
    status: 'found',
    ...base,
    structuralOnly: true,
    runtimeDir: toRel(pkgRoot, result.runtimeDir),
    python: toRel(pkgRoot, result.python),
    tools,
  })
  process.exit(0)
}

if (result.status === 'absent') {
  emit({ status: 'absent', ...base, code: result.code })
  process.exit(3)
}

emit({ status: 'invalid', ...base, code: result.code, ...(result.field ? { field: result.field } : {}) })
process.exit(4)
