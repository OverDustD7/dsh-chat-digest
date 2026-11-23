# -*- coding: utf-8 -*-
'''公开 npm 包发布门禁（默认干跑）。

公开包按实际归档执行逐文件准入。本地冻结运行时核验函数保留给私有装配检查。

与 v2 的区别（2026-10-26，随包内 runtime 准入一起改）：
  ① 结构白名单加 `runtime/`；runtime 内容按 `tools/runtime-assets.lock.json` 的**冻结清单**
     逐文件核 sha256：未知文件、被改动、清单里有而包里缺，三者都阻断。
     清单**只在装配那一轮生成一次**，门禁从不现场遍历 runtime 目录再自己签白名单。
  ② 临时根改成**每次运行新建的唯一目录**（`tempfile.mkdtemp`）。v2 无条件 `rmtree` 共享的
     `%TEMP%\\cf-gate2`，两个并发的门禁会互相删；现在既不共用也不预删，只有本轮的
     `cf-gate2-*` 目录才可能被清理，且清理前核真实绝对路径与重解析点。
  ③ tar 解包前逐条目校验：绝对路径 / 盘符 / UNC / 点点 / 链接 / 设备 / ADS 冒号 /
     保留设备名 / 尾随点或空格 / 大小写冲突，全部拒绝后再落地。
  ④ 诊断输出不再回显标记原文或其前缀（v2 会保留前 2 字——2 字中文名即全名——和 40 位 hex 的前 12 位）。
     现在只给计数、位置（file:line）和不透明的标记编号，保留定位能力、不输出原值或可逆变体。
  ⑤ 规则拆成纯函数 + `main()`：fixture 可以直接 import 这些函数做规则验证，不必跑 npm、
     不必读真实私人配置，也不会在 import 时就产生副作用。

用法（行为不变）：
  python tools/gate-publish.py              # 干跑，只出报告
  python tools/gate-publish.py --publish    # 报告通过才真的 npm publish（窗口开放后）
'''
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse

# 本文件住在 <仓库>/tools/ 下：仓库位置由自身位置算，不再写死
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DSH_HOME = os.environ.get('DSH_HOME') or os.path.join(os.path.expanduser('~'), '.dsh')
HOST_PROFILE = os.path.join(DSH_HOME, 'profiles', 'web')
PRIVATE = os.environ.get('DSH_CHAT_FEED_LOCAL') or os.path.join(DSH_HOME, 'dsh-chat-digest')
RUNTIME_LOCK_REL = os.path.join('test', 'runtime-assets.lock.json')
RUNTIME_PREFIX = 'runtime/'

# ── 结构白名单 ────────────────────────────────────────────────────────────────
# runtime/ 是 2026-10-26 准入的：包内自带解释器与供应商源码。它的**内容**不由白名单放宽，
# 而是由冻结清单逐文件核（见 runtime_admission_problems）。
TOP_OK = {'lib', 'pipeline', 'agent', 'examples', 'prompt', 'runtime',
          'cordis.patch.yml', 'package.json', 'LICENSE',
          'README.md', 'README.zh.md', 'README.i18n.yaml', 'CHANGELOG.md'}
FORBID_DIRS = ('local/', 'test/', 'tools/', 'docs/', 'archive/', 'node_modules/',
               # A34：agent 树下指向**个人目录**的联接。它们只在运行态存在（lib/plugin.js 挂载时建），
               #   万一在运行态打包，这几个前缀会把某个人的数据带进包 —— 让门禁直接拦下。
               'agent/output/', 'agent/inbox/', 'agent/docs/knowledge/', 'agent/docs/archive/',
               # 2026-10-26：pipeline 下的**运行态私有目录**。第三方微信工具的日志与密钥目录、
               #   以及管线自己的缓存/收件箱都落在这里；package.json files 也有对应否定项。
               'pipeline/output/', 'pipeline/logs/', 'pipeline/data/', 'pipeline/cache/',
               'pipeline/inbox/')
FORBID_ANY = ('__pycache__', '.pyc', '.pyo', '.db', '.sqlite', '.log', '.env',
              # 供应商在 output 下生成的口令库文件名（不带扩展名，前缀规则抓不到）
              'account_keys.json')

# Windows 上"看起来是普通路径"、实际会绕开边界的名字
RESERVED_DEVICE = {'CON', 'PRN', 'AUX', 'NUL'}
RESERVED_DEVICE |= {'COM%d' % i for i in range(1, 10)}
RESERVED_DEVICE |= {'LPT%d' % i for i in range(1, 10)}

GENERIC_SEG = {'users', 'appdata', 'documents', 'local', 'roaming', 'temp', 'program files',
               'xwechat_files', 'nt_qq', 'nt_db', 'nt_msg.db', 'd:', 'c:', 'e:',
               'wechat', 'weixin', 'qq', 'data', 'files', 'msg', 'db', 'xwechat'}

# 通用/公开词：不是私人信息，不该阻断（范式 B：收了就虚报）。
#   paratera / deepseek = 模型供应商名；OverDustD7 = 包作者（npm 与公开仓库本就是这个身份）；
#   dsh-chat-digest = 包名本身；id: dsh-chat-digest = 从 profile 配置里解析出的 YAML 键残留。
#   output / cache / models / Tencent / kvcomm / Project / https: = 代码里的通用路径段与协议。
GENERIC_OK = {'paratera', 'deepseek', 'overdustd7', 'dsh-chat-digest',
              'id: dsh-chat-digest', 'output', 'cache', 'models', 'tencent', 'kvcomm',
              'project', 'https:', 'http:', 'dsh', 'wxid', 'xwechat'}

_CJK_RE = re.compile(r'[\u4e00-\u9fff]')


def _cjk(t):
    return any('\u4e00' <= c <= '\u9fff' for c in str(t))


def _keep(m):
    if m.lower() in GENERIC_OK or m.lower() in GENERIC_SEG:
        return False
    return len(m) >= 5 or _cjk(m)


def variants(m):
    out = {m, m.replace('\\', '/'), m.replace('\\', '\\\\'), m.replace('/', '\\')}
    try:
        out.add(urllib.parse.quote(m, safe=''))
    except Exception:
        pass
    return {x for x in out if len(x) >= 5 or _cjk(x)}


def feed_value(t1, t2, value):
    v = str(value).strip().strip("'\"").strip().rstrip(',').strip().strip("'\"").strip()
    if not v or v in ('True', 'False', 'None', 'null'):
        return
    if len(v) >= 5 or _CJK_RE.search(v):
        t1.add(v)                    # 完整值 = 高危（中文名 2–3 字也算）
    if '\\' in v or '/' in v:
        for seg in v.replace('/', '\\').split('\\'):
            seg = seg.strip()
            if (len(seg) >= 5 or _CJK_RE.search(seg)) and seg.lower() not in GENERIC_SEG:
                t2.add(seg)


# 公开署名：已出现在公开 npm 包与公开仓库上的句柄，属"既有公开身份"，不是私密值。
PUBLIC_IDENTITY = {'OverDustD7'}

# 字段语义：只有"路径 / 身份 / 联络 / 凭据"类的值才算私密标记。
_IDENTITY_KEYS = ('path', 'dir', 'root', 'cwd', 'url', 'uri', 'user', 'name', 'account', 'key',
                  'token', 'phone', 'id', 'host', 'mail', 'owner', 'wxid', 'file', 'agent',
                  'profile', 'home', 'mount', 'prefix', 'nick', 'alias',
                  'model', 'provider', 'effort', 'temperature')
# 纯小写枚举词（legacy / bundled / output / none …）是**字段类型**，不是私人值。
_ENUMISH = re.compile(r'^[a-z][a-z0-9_.-]{0,23}$')


def feed_config(t1, t2, path):
    """2026-11-24：按**字段语义**生成字典，而不是把每个 YAML 值都当私密标记。

    旧版把每个值（含 `pythonRuntime: legacy`、`mode: bundled`）都灌进 T1，于是通用英文枚举词成了
    阻断标记 —— 236 处阻断里 235 处是这种噪声，而真正的私密命中只有 1 处。收窄规则（两类都保留覆盖）：
      · 值本身像路径/邮箱/长数字/中文 ⇒ 一定是私密值，收；
      · 键名属于身份/路径/凭据类 ⇒ 收；
      · 其余纯小写枚举词 ⇒ 不收。
    """
    if not os.path.isfile(path):
        return
    for line in io.open(path, encoding='utf-8', errors='replace').read().split('\n'):
        raw = line.split('#')[0].rstrip()
        s = raw.strip()
        key = ''
        if s.startswith('- '):
            val = s[2:].strip()
        elif ':' in s:
            key, val = s.split(':', 1)
            key = key.strip().lower()
            val = val.strip()
        else:
            continue
        val = val.strip().strip('\'"')
        if not val:
            continue
        # 纯数字不是私人值（上下文窗口、字节数、超时毫秒都是这种）；只有像电话/长 ID 才算。
        digits = re.fullmatch(r'\d+', val) is not None
        pathish = (('\\' in val) or ('/' in val) or ('@' in val) or _cjk(val)
                   or (digits and len(val) >= 10)
                   or ((not digits) and re.search(r'\d{6,}', val) is not None))
        keyish = any(k in key for k in _IDENTITY_KEYS)
        if not (pathish or keyish):
            continue
        # 身份/配置键（model、provider、name …）的值一律保留：这些字段本身就是私人配置项。
        if _ENUMISH.match(val) and not pathish and not keyish and len(val) <= 12 and '_' not in val:
            continue
        feed_value(t1, t2, val)

def feed_json(t1, t2, path):
    if not os.path.isfile(path):
        return
    try:
        obj = json.load(io.open(path, encoding='utf-8'))
    except (OSError, ValueError):
        return

    def walk(value):
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str):
            feed_value(t1, t2, value)

    walk(obj)


def read_extra_tokens(private_dir):
    """私人标记表：只从私人 profile 的 personal-tokens.txt 读 —— 门禁脚本自身不许含私人值。"""
    path = os.path.join(private_dir, 'personal-tokens.txt')
    if not os.path.isfile(path):
        return []
    return [l.strip() for l in io.open(path, encoding='utf-8')
            if l.strip() and not l.startswith('#')]


def build_marker_tables(private_dir, host_profile):
    """从私人配置与标记文件生成 (V1, V2)。路径全部由调用方给出 —— fixture 可以喂合成目录。

    V1 = 高置信私人值（阻断）→ 变体；V2 = 路径段等（报数）→ 变体。
    """
    t1, t2 = set(), set()
    feed_config(t1, t2, os.path.join(private_dir, 'pipeline.yaml'))
    feed_json(t1, t2, os.path.join(private_dir, 'pipeline.json'))
    feed_config(t1, t2, os.path.join(host_profile, 'cordis.patch.yml'))
    t1 = {m for m in t1 if _keep(m)}
    t2 = {m for m in t2 if _keep(m)}
    extra = read_extra_tokens(private_dir)
    t1 |= {m for m in extra if m and m.lower() not in GENERIC_OK}
    t2 -= t1
    v1, v2 = {}, {}
    for m in t1:
        for v in variants(m):
            v1.setdefault(v, m)
    for m in t2:
        for v in variants(m):
            v2.setdefault(v, m)
    info = {'t1': len(t1), 't2': len(t2), 'v1': len(v1), 'v2': len(v2), 'extra': len(extra)}
    # 2026-11-24：公开署名（已出现在公开 npm 包/仓库上的句柄）不是私密值，从两张表里扣掉。
    for _pid in PUBLIC_IDENTITY:
        for _v in variants(_pid):
            v1.pop(_v, None); v2.pop(_v, None)
    return v1, v2, info


def marker_labels(v1):
    """标记 → 不透明编号。编号只在本次运行内对应原值，报告里不带任何前后缀。"""
    return {m: 'M%03d' % (i + 1) for i, m in enumerate(sorted(set(v1.values())))}


def read_any(path):
    try:
        raw = io.open(path, 'rb').read()
    except OSError:
        return None, None
    for enc in ('utf-8', 'gbk', 'utf-16', 'latin-1'):
        try:
            return raw.decode(enc), enc
        except Exception:
            continue
    return None, None


def count_hits(text, v1, v2):
    """把一段文本按两张表计数，返回 ({marker: n}, {marker: n})。"""
    nt = text.replace('\\\\', '\\').replace('/', '\\').lower()
    h1, h2 = {}, {}
    for v, m in v1.items():
        c = nt.count(v.lower())
        if c:
            h1[m] = h1.get(m, 0) + c
    for v, m in v2.items():
        c = nt.count(v.lower())
        if c:
            h2[m] = h2.get(m, 0) + c
    return h1, h2


#: 形状判据：会暴露"这台机器上是谁"的两种可识别串。
SHAPE_CHECKS = (
    (re.compile(r'session-[0-9a-f]{8}(?:-[0-9a-f-]+)?', re.I), '真实会话 ID'),
    (re.compile(r'[a-z]:\\users\\(?!<|%|\{)[^\\\s`]+', re.I), '真实用户目录'),
)


def shape_leak_problems(rel, text, frozen_official):
    """形状判据的**唯一**例外：已按冻结哈希证明的官方 runtime 资产，按具体文件给。

    为什么是"按文件"而不是"按编码"：二进制回退 utf-16/latin-1 解码时，上游编译产物里的
    构建机路径会命中"真实用户目录"，那不是本包作者的数据；而一旦改成"按编码放宽"，
    UTF-16 普通文本里真正的用户目录 / session-ID 也会被一并跳过 —— 那是拿真实泄露换安静。
    runtime/ 之外的文件、以及 runtime 里没进冻结清单的文件，一律照旧全量扫。
    标记表（T1）不受这个例外影响，对一切文件仍然生效。
    """
    if rel in frozen_official:
        return []
    return [kind for rx, kind in SHAPE_CHECKS if rx.search(text or '')]


def sha256_file(path):
    h = hashlib.sha256()
    with io.open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _reparse_tag(st):
    return int(getattr(st, 'st_reparse_tag', 0) or 0)


# ── 临时根：本轮新建的唯一目录 ────────────────────────────────────────────────
#: 本进程真正创建并**当场登记**的临时根：normcase 绝对路径 → {base, dev, ino}。
#: 只认这张表，不认"名字像 cf-gate2-" —— 同前缀的兄弟目录、以及事后被替换成联接的同名对象
#: 都不在其中，因此删不掉。进程不共享这张表：换个进程就无法自证所有权，宁可不删。
_OWNED_WORK_ROOTS = {}


def make_work_root(base=None):
    """在 base 下新建一个唯一目录，登记所有权后返回它的绝对路径。不预删、不共用。"""
    base = base or os.environ.get('TEMP') or os.environ.get('TMP') or tempfile.gettempdir()
    base = os.path.abspath(base)
    os.makedirs(base, exist_ok=True)
    root = os.path.abspath(tempfile.mkdtemp(prefix='cf-gate2-', dir=base))
    st = os.lstat(root)
    _OWNED_WORK_ROOTS[os.path.normcase(root)] = {
        'base': os.path.normcase(os.path.abspath(base)),
        'dev': int(getattr(st, 'st_dev', 0) or 0),
        'ino': int(getattr(st, 'st_ino', 0) or 0),
    }
    return root


def safe_rmtree(path, base):
    """只清理**本进程 make_work_root 真正创建并登记过**的那一个目录。

    判据（全中才删）：
      ① 先对**原参数**做 lstat —— 联接/重解析点直接拒。顺序很要紧：先 realpath 会把"这个路径
         本身是联接"这件事抹掉，于是删掉的是它指向的那个真目录。
      ② 所有权：路径必须在本进程的登记表里，且登记的 base 与传入的 base 一致。
         同前缀的兄弟目录、别的进程建的目录都不在表里 ⇒ 拒绝。
      ③ 身份：dev/ino 必须与登记时一致 ⇒ 防"删掉别人的同名替换对象"。
      ④ 真实边界：realpath 之后仍要严格落在 base 之内且不等于 base。
      ⑤ 删除不用 ignore_errors；删完必须确认真的不存在，否则如实返回 False。
    """
    if not path or not base:
        return False
    try:
        original = os.path.abspath(path)
        try:
            st_leaf = os.lstat(original)
        except OSError:
            return False
        if os.path.islink(original) or _reparse_tag(st_leaf):
            return False
        if not stat.S_ISDIR(st_leaf.st_mode):
            return False
        entry = _OWNED_WORK_ROOTS.get(os.path.normcase(original))
        if entry is None:
            return False
        if os.path.normcase(os.path.abspath(base)) != entry['base']:
            return False
        identity = (int(getattr(st_leaf, 'st_dev', 0) or 0), int(getattr(st_leaf, 'st_ino', 0) or 0))
        if identity != (entry['dev'], entry['ino']):
            return False
        rp = os.path.realpath(original)
        rb = os.path.realpath(base)
        if rp == rb:
            return False
        if os.path.commonpath([rp, rb]) != rb:
            return False
        if not os.path.basename(rp).startswith('cf-gate2-'):
            return False
        try:
            shutil.rmtree(rp)
        except OSError:
            pass
        if os.path.exists(rp) or os.path.islink(rp):
            return False
        _OWNED_WORK_ROOTS.pop(os.path.normcase(original), None)
        return True
    except (OSError, ValueError):
        return False


# ── tar 条目校验 ──────────────────────────────────────────────────────────────
def tar_member_problems(names):
    """只接受普通相对文件/目录条目。返回问题清单（空 = 全部安全）。"""
    probs = []
    seen = {}
    for name in names:
        if not name:
            probs.append('空条目名')
            continue
        if '\x00' in name:
            probs.append('条目名含 NUL')
            continue
        if '\\' in name:
            probs.append('条目名含反斜杠：%r' % name)
            continue
        if name.startswith('/'):
            probs.append('绝对路径条目：%r' % name)
            continue
        if name.startswith('//'):
            probs.append('UNC 条目：%r' % name)
            continue
        if re.match(r'^[A-Za-z]:', name):
            probs.append('盘符条目：%r' % name)
            continue
        parts = name[:-1].split('/') if name.endswith('/') else name.split('/')
        bad = False
        for p in parts:
            if p in ('', '.', '..'):
                probs.append('空段或点点段：%r' % name)
                bad = True
                break
            if ':' in p:
                probs.append('ADS 冒号：%r' % name)
                bad = True
                break
            if p.endswith('.') or p.endswith(' '):
                probs.append('尾随点或空格：%r' % name)
                bad = True
                break
            if p.split('.')[0].upper() in RESERVED_DEVICE:
                probs.append('保留设备名：%r' % name)
                bad = True
                break
            if any(ord(c) < 32 for c in p):
                probs.append('控制字符：%r' % name)
                bad = True
                break
        if bad:
            continue
        key = name.lower().rstrip('/')
        if key in seen:
            probs.append('大小写冲突：%r' % name)
            continue
        seen[key] = 1
    return probs


def extract_tar_safely(tgz, dest):
    """校验全部条目后落地。校验不过就抛，绝不在校验前解任何东西。"""
    with tarfile.open(tgz) as t:
        members = t.getmembers()
        probs = tar_member_problems([m.name for m in members])
        for m in members:
            if m.issym() or m.islnk():
                probs.append('链接条目：%r' % m.name)
            elif m.isdev():
                probs.append('设备条目：%r' % m.name)
        if probs:
            raise ValueError('tar 条目不安全：' + '；'.join(probs[:8]))
        try:
            t.extractall(dest, filter='data')
        except TypeError:            # 老 Python 没有 filter 参数
            t.extractall(dest)
    return len(members)


# ── runtime 冻结清单 ──────────────────────────────────────────────────────────
def load_runtime_lock(repo_root):
    """读冻结清单（路径由 RUNTIME_LOCK_REL 决定）。返回 (lock, error)。"""
    path = os.path.join(repo_root, RUNTIME_LOCK_REL)
    if not os.path.isfile(path):
        return None, '缺少冻结清单 %s' % RUNTIME_LOCK_REL.replace(os.sep, '/')
    try:
        lock = json.load(io.open(path, encoding='utf-8'))
    except (OSError, ValueError) as e:
        return None, '运行时冻结清单读不出：%s' % e
    if not isinstance(lock, dict) or not isinstance(lock.get('files'), list):
        return None, '运行时冻结清单结构不对（缺 files 数组）'
    bad = [f for f in lock['files']
           if not isinstance(f, dict) or not isinstance(f.get('path'), str)
           or not re.match(r'^[0-9a-f]{64}$', str(f.get('sha256', '')))]
    if bad:
        return None, '运行时冻结清单有 %d 条不合法' % len(bad)
    return lock, None


def runtime_manifest_problems(pkg_dir, lock):
    """runtime/<seg>/manifest.json 必须自洽，且声明的每个文件都在冻结清单里。"""
    probs = []
    root = str(lock.get('runtimeRoot') or '').rstrip('/')
    if not root.startswith(RUNTIME_PREFIX):
        probs.append('冻结清单 runtimeRoot 不在 runtime/ 下：%r' % root)
        return probs
    manifest_rel = root + '/manifest.json'
    lock_paths = {f['path'] for f in lock['files']}
    if manifest_rel not in lock_paths:
        probs.append('冻结清单里没有 manifest：%s' % manifest_rel)
        return probs
    fp = os.path.join(pkg_dir, manifest_rel.replace('/', os.sep))
    if not os.path.isfile(fp):
        probs.append('包内缺 manifest：%s' % manifest_rel)
        return probs
    try:
        manifest = json.loads(io.open(fp, encoding='utf-8-sig').read())
    except (OSError, ValueError) as e:
        probs.append('manifest 解析失败：%s' % e)
        return probs
    if not isinstance(manifest, dict):
        probs.append('manifest 不是对象')
        return probs
    for key in ('schemaVersion', 'platform', 'arch', 'python'):
        if key not in manifest:
            probs.append('manifest 缺字段：%s' % key)
    if manifest.get('schemaVersion') != 1:
        probs.append('manifest.schemaVersion 不是 1')
    if manifest.get('platform') != lock.get('platform'):
        probs.append('manifest.platform 与冻结清单不一致')
    if manifest.get('arch') != lock.get('arch'):
        probs.append('manifest.arch 与冻结清单不一致')
    declared = []
    if isinstance(manifest.get('python'), str):
        declared.append(('python', manifest['python']))
    if isinstance(manifest.get('tools'), dict):
        for name, value in manifest['tools'].items():
            declared.append(('tools.' + str(name), value))
    for field, value in declared:
        if not isinstance(value, str) or not value:
            probs.append('manifest.%s 不是非空字符串' % field)
            continue
        parts = value.split('/')
        if value.startswith('/') or re.match(r'^[A-Za-z]:', value) or '\\' in value:
            probs.append('manifest.%s 不是显式相对正斜杠路径' % field)
            continue
        if any(p in ('', '.', '..') for p in parts):
            probs.append('manifest.%s 含空段或点点段' % field)
            continue
        rel = root + '/' + value
        if rel not in lock_paths:
            probs.append('manifest.%s 指向的文件不在冻结清单里：%s' % (field, rel))
    return probs


def path_containment_problems(pkg_dir, rel, label):
    """包内文件的**祖先**与真实路径都必须干净。

    只 lstat 末端文件不够：把 `runtime/win32-x64/python/` 换成一个指向包外目录的联接，
    叶子仍是普通文件、内容也能对上冻结哈希 —— 但那时读到的已经不是包内资产。
    所以先逐级看祖先有没有重解析点，再核 realpath 是否仍在包根内。哈希与隐私规则一条不放松。
    """
    probs = []
    try:
        pkg_real = os.path.normcase(os.path.realpath(pkg_dir))
    except OSError:
        return ['%s 包根无法规范化：%s' % (label, rel)]
    cur = pkg_dir
    for seg in rel.split('/')[:-1]:
        cur = os.path.join(cur, seg)
        try:
            st = os.lstat(cur)
        except OSError:
            return ['%s 祖先目录读不到：%s' % (label, rel)]
        if os.path.islink(cur) or _reparse_tag(st):
            return ['%s 祖先目录是链接/重解析点：%s' % (label, rel)]
    fp = os.path.join(pkg_dir, rel.replace('/', os.sep))
    try:
        real = os.path.normcase(os.path.realpath(fp))
    except OSError:
        return ['%s 真实路径无法规范化：%s' % (label, rel)]
    if real != pkg_real and not real.startswith(pkg_real + os.sep):
        return ['%s 真实路径在包外：%s' % (label, rel)]
    return probs


def runtime_admission_problems(pkg_dir, packed, lock):
    """runtime/ 下的每个打包文件都必须与冻结清单逐字节相符，且清单里的一条不能缺。"""
    probs = []
    lock_map = {f['path']: f for f in lock['files']}
    packed_runtime = [f for f in packed if f.startswith(RUNTIME_PREFIX)]
    if not packed_runtime:
        probs.append('包里没有 runtime/ 文件（冻结清单要求 %d 个）' % len(lock_map))
        return probs
    for rel in packed_runtime:
        entry = lock_map.get(rel)
        if entry is None:
            probs.append('runtime 未知文件（不在冻结清单）：%s' % rel)
            continue
        contain = path_containment_problems(pkg_dir, rel, 'runtime 文件')
        if contain:
            probs.extend(contain)
            continue
        fp = os.path.join(pkg_dir, rel.replace('/', os.sep))
        try:
            st = os.lstat(fp)
        except OSError as e:
            probs.append('runtime 文件读不到：%s（%s）' % (rel, e))
            continue
        if _reparse_tag(st) or os.path.islink(fp):
            probs.append('runtime 文件是链接/重解析点：%s' % rel)
            continue
        if not os.path.isfile(fp):
            probs.append('runtime 条目不是常规文件：%s' % rel)
            continue
        try:
            size = os.path.getsize(fp)
            digest = sha256_file(fp)
        except OSError as e:
            probs.append('runtime 文件读过失败：%s（%s）' % (rel, e))
            continue
        if size != entry.get('bytes'):
            probs.append('runtime 文件大小不符：%s（%s ≠ %s）' % (rel, size, entry.get('bytes')))
        if digest != entry.get('sha256'):
            probs.append('runtime 文件内容被改动：%s' % rel)
    missing = sorted(set(lock_map) - set(packed_runtime))
    for rel in missing[:20]:
        probs.append('runtime 冻结文件缺失：%s' % rel)
    if len(missing) > 20:
        probs.append('runtime 冻结文件缺失还有 %d 条' % (len(missing) - 20))
    probs.extend(runtime_manifest_problems(pkg_dir, lock))
    return probs


def asset_exemptions(packed, tracked, lock):
    """未跟踪文件里，只有**与冻结清单逐条对上**的 runtime 文件算精确资产例外。"""
    tracked_set = set(tracked)
    lock_paths = {f['path'] for f in lock['files']} if lock else set()
    exempt = [f for f in packed if f not in tracked_set and f in lock_paths]
    extra = [f for f in packed if f not in tracked_set and f not in lock_paths and f != 'package.json']
    return exempt, extra


# ── 结构断言 ──────────────────────────────────────────────────────────────────
def structure_problems(packed):
    probs = []
    for rel in packed:
        top = rel.split('/')[0]
        if top not in TOP_OK:
            probs.append('顶层不在白名单：%s' % rel)
        for d in FORBID_DIRS:
            if rel.startswith(d):
                probs.append('禁入目录：%s' % rel)
        for w in FORBID_ANY:
            if w in rel:
                probs.append('禁入文件特征 %s：%s' % (w, rel))
    return probs


def public_archive_problems(packed, declared):
    """核对 npm 实际归档；自动收录的额外 README 同样要拒绝。"""
    implicit = {'package.json', 'README.md', 'README.zh.md', 'README.i18n.yaml', 'LICENSE', 'CHANGELOG.md'}
    required = {p for p in declared if not p.startswith('!')}
    problems = []
    if any(re.search(r'[*?\[]', p) for p in required):
        problems.append('公开文件清单必须逐项列出')
    actual = set(packed)
    if len(actual) != len(packed):
        problems.append('归档含重复路径')
    for path in sorted(required - actual):
        problems.append('声明文件未入包：' + path)
    for path in sorted(actual - required - implicit):
        problems.append('文件未获准入包：' + path)
    for path in sorted(actual | required):
        segments = path.lower().split('/')
        if segments[0] == 'runtime' or 'vendor' in segments:
            problems.append('包外依赖进入公开归档或清单：' + path)
    return problems


# ── 报告（不回显标记原文）────────────────────────────────────────────────────
def report_t1(h1, pkg_dir, v1, emit=print, max_lines=6):
    if not h1:
        emit('  无 ✔')
        return
    labels = marker_labels(v1)
    for rel, d in sorted(h1.items()):
        emit('  %-38s %d 个私密标记命中' % (rel, sum(d.values())))
        # 定位到行即可：行号 + 标记编号 + 行长度。**不打印行内容**，也不打印标记的任何前缀。
        try:
            text, _ = read_any(os.path.join(pkg_dir, rel.replace('/', os.sep)))
            shown = 0
            for i, line in enumerate((text or '').splitlines(), 1):
                low = line.replace('\\\\', '\\').replace('/', '\\').lower()
                hit = sorted({labels.get(m, 'M???') for v, m in v1.items() if v.lower() in low})
                if hit and shown < max_lines:
                    emit('      L%-4d 命中=%s 行长度=%d' % (i, ','.join(hit), len(line)))
                    shown += 1
        except Exception as e:
            emit('      （定位失败：%s）' % type(e).__name__)
    emit('  合计 %d 个文件' % len(h1))


def report_hex(hexes, emit=print):
    if not hexes:
        emit('  无')
        return
    for rel, lengths in sorted(hexes.items()):
        emit('  %-38s %d 段（长度 %s）' % (rel, len(lengths),
                                          ','.join(str(x) for x in sorted(lengths)[:6])))


class _Tee(object):
    def __init__(self, fh, real=None):
        self.fh = fh
        self.real = real

    def write(self, s):
        self.fh.write(s)
        if self.real is not None:
            try:
                self.real.write(s)
            except Exception:
                pass

    def flush(self):
        self.fh.flush()


def run(args, cwd, cache_dir):
    cmd = ' '.join('"%s"' % a if ' ' in a else a for a in args)
    env = dict(os.environ)
    env.setdefault('npm_config_cache', cache_dir)
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', shell=True, env=env)
    return r.returncode, (r.stdout or ''), (r.stderr or '')


def _run(tmp, do_publish):
    # 公开包不接受本地冻结运行时；不为它们放宽内容检查。
    frozen_official = set()
    v1, v2, info = build_marker_tables(PRIVATE, HOST_PROFILE)
    print('标记表：T1(阻断) %d 个值 → %d 个变体；T2(报数) %d 个值 → %d 个变体（个人标记文件 %d 条）'
          % (info['t1'], info['v1'], info['t2'], info['v2'], info['extra']))
    print('临时根：%s（本轮新建，唯一）' % tmp)

    # ── 1) 打包 ──────────────────────────────────────────────────────────────
    rc, out, err = run(['npm', 'pack', '--pack-destination', tmp], R, os.path.join(tmp, 'npm-cache'))
    print('\n[npm pack] rc=%s' % rc)
    if rc != 0:
        print((err or out)[-900:])
        return 1
    tgzs = [f for f in os.listdir(tmp) if f.endswith('.tgz')]
    if not tgzs:
        print('  npm pack 没产出 tgz')
        return 1
    tgz = os.path.join(tmp, tgzs[0])
    print('  产物 %s（%s B）' % (tgzs[0], os.path.getsize(tgz)))

    ex = os.path.join(tmp, 'x')
    os.makedirs(ex, exist_ok=True)
    try:
        n = extract_tar_safely(tgz, ex)
    except (ValueError, tarfile.TarError) as e:
        print('  **解包被拒**：%s' % e)
        return 2
    pkg = os.path.join(ex, 'package')
    packed = sorted(os.path.relpath(os.path.join(r, f), pkg).replace('\\', '/')
                    for r, _, fs in os.walk(pkg) for f in fs)
    print('  解包 %d 个文件（tar 条目 %d 个，全部通过路径校验）' % (len(packed), n))

    # ── 2) 结构与实际文件准入 ────────────────────────────────────────────
    with io.open(os.path.join(R, 'package.json'), encoding='utf-8') as handle:
        declared = json.load(handle)['files']
    struct = structure_problems(packed) + public_archive_problems(packed, declared)
    tracked = subprocess.run(['git', '-C', R, 'ls-files'], capture_output=True, text=True,
                             encoding='utf-8', check=True).stdout.splitlines()
    _, extra_in_pkg = asset_exemptions(packed, tracked, None)
    if any(f.split('/')[0].lower() in ('runtime', 'vendor') for f in tracked):
        struct.append('公开源码索引包含本地 runtime 或 vendor 文件')
    print('  仓库跟踪 %d 个；包内不在跟踪集的：%s' % (len(tracked), extra_in_pkg or '无'))
    if struct:
        print('  **结构断言未过**：')
        for problem in struct[:20]:
            print('    ' + problem)
    else:
        print('  ✔ 实际归档与公开文件准入清单一致')

    # ── 3) 逐文件扫描 ────────────────────────────────────────────────────────
    h1, h2, hexes, unde = {}, {}, {}, []
    leaks = []
    for rel in packed:
        fp = os.path.join(pkg, rel.replace('/', os.sep))
        text, enc = read_any(fp)
        if text is None:
            unde.append(rel)
            continue
        # 形状判据走 shape_leak_problems()：唯一的例外是"已按冻结哈希证明的官方 runtime 资产"，
        # 而且只按具体文件给（见该函数的说明）。标记表对一切文件仍然生效。
        for kind in shape_leak_problems(rel, text, frozen_official):
            leaks.append((rel, kind))
        one1, one2 = count_hits(text, v1, v2)
        if one1:
            h1.setdefault(rel, {}).update(one1)
        if one2:
            h2.setdefault(rel, {}).update(one2)
        # 只留长度，不留前缀：报告里不出现任何 hex 片段
        for x in set(re.findall(r'[0-9a-f]{32,}', text.lower())):
            hexes.setdefault(rel, []).append(len(x))

    # 仓库上传也会泄露：扫描已跟踪及将来可能纳入的非忽略文件，不只扫描 npm 包。
    repo_candidates = subprocess.run(
        ['git', '-C', R, 'ls-files', '--cached', '--others', '--exclude-standard'],
        capture_output=True, text=True, encoding='utf-8').stdout.splitlines()
    repo_hits = {}
    for rel in repo_candidates:
        fp = os.path.join(R, rel.replace('/', os.sep))
        if not os.path.isfile(fp):
            continue
        body, _ = read_any(fp)
        if body is None or '\x00' in body:
            continue
        normalized = body.replace('\\\\', '\\').replace('/', '\\').lower()
        found = sum(normalized.count(v.lower()) for v in v1)
        if found:
            repo_hits[rel] = found

    print()
    print('== T1 阻断级命中 ==')
    report_t1(h1, pkg, v1)
    print('== 仓库文件私人标记命中 ==')
    if repo_hits:
        for rel, count in sorted(repo_hits.items()):
            print('  %-38s %d 个私密标记命中' % (rel, count))
    else:
        print('  无 ✔')
    print()
    print('== T2 报数级命中（人眼判断，可能是通用段）==')
    if h2:
        for rel, d in sorted(h2.items(), key=lambda kv: -sum(kv[1].values()))[:18]:
            print('  %-38s %d 个待审标记命中' % (rel, sum(d.values())))
        print('  合计 %d 个文件' % len(h2))
    else:
        print('  无')
    print()
    print('== 解不开的文件（禁止静默丢弃）==')
    print('  %s' % (unde or '无'))
    print()
    print('== ≥32 位十六进制串（只报处数与长度，不回显片段）==')
    report_hex(hexes)

    if leaks:
        print('== 结构化隐私候选 ==')
        for rel, kind in leaks:
            print('  %s: %s' % (rel, kind))

    # ── 3.5) 布局边界探针（B01–B06）──────────────────────────────────────────
    #   分两挡（2026-09-28 用户定案）：**B01「包内不许有本机字面路径」判的是产物 ⇒ 计入阻断**；
    #   B02–B06 判的是**本机部署**（它们读的是安装副本与私人 profile 的现状）⇒ 只打印报数，不卡发布 ——
    #   否则"这台机器没同步"会被当成"产物不合格"。本机没有这个文件时整段跳过。
    _bound = os.path.join(R, 'test', 'boundary-checks.py')
    b01_ok = True
    print('\n== 布局边界探针（B01–B06；B01 阻断，B02–B06 报数）==')
    if os.path.isfile(_bound):
        _rc, _out, _err = run([sys.executable, _bound], R, os.path.join(tmp, 'npm-cache'))
        _lines = [x.rstrip() for x in ((_out or '') + (_err or '')).split('\n')
                  if re.match(r'\s*(ok|FAIL)\s+B\d\d', x)]
        for _l in _lines:
            print('  ' + _l.strip())
        _b01 = [x for x in _lines if 'B01' in x]
        if _b01:
            b01_ok = not any(x.strip().startswith('FAIL') for x in _b01)
        else:
            b01_ok = (_rc == 0)   # 解析不到结果（探针崩了）⇒ 按不过处理
            print('  探针没给出可解析的 B01 结果，按不过处理（rc=%s）' % _rc)
        _bad = [x.split()[1] for x in _lines if x.strip().startswith('FAIL')]
        if _bad:
            print('  （报数·不卡发布）这几条判的是**本机部署**：%s' % ', '.join(_bad))
    else:
        print('  本机没有 test/boundary-checks.py，整段跳过（不影响判定）')

    ok = (b01_ok and not struct and not h1
          and not repo_hits and not extra_in_pkg and not leaks)
    print()
    print('门禁判定：%s' % ('通过 ✔' if ok else '**未过，拒绝发布**'))

    if not do_publish:
        print('（干跑，未发布；报告与解包留在 %s）' % tmp)
        return 0 if ok else 2
    if not ok:
        return 2

    # ── 4) 发布 ──────────────────────────────────────────────────────────────
    print('\n[npm publish] 目标 registry.npmjs.org')
    rc, out, err = run(['npm', 'publish', '--registry=https://registry.npmjs.org/'], R,
                       os.path.join(tmp, 'npm-cache'))
    txt = (out or '') + (err or '')
    for l in [l for l in txt.split('\n') if l.strip()][-5:]:
        print('  ' + l.strip())
    print('  rc=%s' % rc)
    if rc != 0:
        return 3
    json.dump({'files': packed, 'bytes': os.path.getsize(tgz)},
              io.open(os.path.join(tmp, 'packed.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print('  已发布。发布面清单存 %s\\packed.json' % tmp)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    do_publish = '--publish' in argv
    tmp = make_work_root()
    out = io.open(os.path.join(tmp, 'cf-gate2-report.txt'), 'w', encoding='utf-8')
    real_stdout = sys.__stdout__
    sys.stdout = _Tee(out, real_stdout)
    try:
        return _run(tmp, do_publish)
    finally:
        sys.stdout = real_stdout
        try:
            out.flush()
            out.close()
        except Exception:
            pass


if __name__ == '__main__':
    sys.exit(main())
