# -*- coding: utf-8 -*-
'''发布门禁 v2（干跑）。

与 cf-publish-130.py 的区别：
  ① 标记表**从用户的真实配置自动生成**（local/pipeline.yaml + profile/cordis.patch.yml），
     不再依赖我硬编码的那串；硬编码串只作为补充。
  ② 两档判定：T1 = 高置信私人值（阻断）；T2 = 路径段等（逐标记报数，人眼过）。
  ③ 对打包集做**结构断言**（顶层白名单 + 禁入目录 + 缓存文件）。
  ④ 默认**不发**；要发必须显式传 --publish。

用法：
  python cf-gate2.py              # 干跑，只出报告
  python cf-gate2.py --publish    # 报告通过才真的 npm publish（窗口开放后）
'''
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.parse

# 本文件住在 <仓库>/tools/ 下：仓库位置由自身位置算，不再写死
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DSH_HOME = os.environ.get('DSH_HOME') or os.path.join(os.path.expanduser('~'), '.dsh')
HOST_PROFILE = os.path.join(DSH_HOME, 'profiles', 'web')
PRIVATE = os.environ.get('DSH_CHAT_FEED_LOCAL') or os.path.join(DSH_HOME, 'dsh-chat-digest')
TMP = os.path.join(os.environ.get('TEMP', '.'), 'cf-gate2')
DO_PUBLISH = '--publish' in sys.argv

# 控制台是 GBK，中文/符号会炸；报告一律直接写 UTF-8 文件
_OUT = io.open(os.path.join(TMP if os.path.isdir(TMP) else os.environ.get('TEMP', '.'),
                            'cf-gate2-report.txt'), 'w', encoding='utf-8')


class _Tee(object):
    def write(self, s):
        _OUT.write(s)
        try:
            sys.__stdout__.write(s)
        except Exception:
            pass
    def flush(self):
        _OUT.flush()


sys.stdout = _Tee()

# ── 结构白名单 ────────────────────────────────────────────────────────────────
TOP_OK = {'lib', 'pipeline', 'agent', 'examples', 'prompt',
          'cordis.patch.yml', 'package.json', 'LICENSE',
          'README.md', 'README.zh.md', 'README.i18n.yaml', 'CHANGELOG.md'}
FORBID_DIRS = ('local/', 'test/', 'tools/', 'docs/', 'archive/', 'node_modules/',
               # A34：agent 树下指向**个人目录**的联接。它们只在运行态存在（lib/plugin.js 挂载时建），
               #   万一在运行态打包，这几个前缀会把某个人的数据带进包 —— 让门禁直接拦下。
               'agent/output/', 'agent/inbox/', 'agent/docs/knowledge/', 'agent/docs/archive/')
FORBID_ANY = ('__pycache__', '.pyc', '.pyo', '.db', '.sqlite', '.log', '.env')

# ── 补充标记（我硬编码的，作为自动标记表的并集）──────────────────────────────
# 私密标记**只从私人 profile 的 personal-tokens.txt 读**——
#   门禁脚本自身不许含任何私人值，否则它自己就成了泄露源。
EXTRA = []
_tok = os.path.join(PRIVATE, 'personal-tokens.txt')
if os.path.isfile(_tok):
    EXTRA = [l.strip() for l in io.open(_tok, encoding='utf-8')
             if l.strip() and not l.startswith('#')]

T1 = set()   # 高置信私人值 → 阻断
T2 = set()   # 路径段等 → 报数给人眼
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


def feed_value(value):
    v = str(value).strip().strip("'\"").strip().rstrip(',').strip().strip("'\"").strip()
    if not v or v in ('True', 'False', 'None', 'null'):
        return
    if len(v) >= 5 or _CJK_RE.search(v):
        T1.add(v)                    # 完整值 = 高危（中文名 2–3 字也算）
    if '\\' in v or '/' in v:
        for seg in v.replace('/', '\\').split('\\'):
            seg = seg.strip()
            if (len(seg) >= 5 or _CJK_RE.search(seg)) and seg.lower() not in GENERIC_SEG:
                T2.add(seg)


def feed_config(path):
    if not os.path.isfile(path):
        return
    for line in io.open(path, encoding='utf-8', errors='replace').read().split('\n'):
        raw = line.split('#')[0].rstrip()
        s = raw.strip()
        if s.startswith('- '):
            feed_value(s[2:])
        elif ':' in s:
            feed_value(s.split(':', 1)[1])


def feed_json(path):
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
            feed_value(value)
    walk(obj)


feed_config(os.path.join(PRIVATE, 'pipeline.yaml'))
feed_json(os.path.join(PRIVATE, 'pipeline.json'))
feed_config(os.path.join(HOST_PROFILE, 'cordis.patch.yml'))
# 通用/公开词不阻断、也不进报数档（否则满屏假阳性，范式 B：收了就虚报）
# A50（2026-09-27）修：**含 CJK 的标记不受长度限制**。原来一刀切 `len(m) >= 5`，
#   会把 2–3 字的中文姓名整条吃掉，使门禁误报 T1=0。
def _cjk(t):
    return any('\u4e00' <= c <= '\u9fff' for c in t)


def _keep(m):
    if m.lower() in GENERIC_OK or m.lower() in GENERIC_SEG:
        return False
    return len(m) >= 5 or _cjk(m)


T1 = {m for m in T1 if _keep(m)}
T2 = {m for m in T2 if _keep(m)}
# 我自己维护的私密标记表（local/personal-tokens.txt）**不裁剪**：写在里面就是要拦的
T1 |= {m.strip() for m in EXTRA if m.strip() and m.lower() not in GENERIC_OK}
T2 -= T1


def variants(m):
    out = {m, m.replace('\\', '/'), m.replace('\\', '\\\\'), m.replace('/', '\\')}
    try:
        out.add(urllib.parse.quote(m, safe=''))
    except Exception:
        pass
    return {x for x in out if len(x) >= 5 or _cjk(x)}


V1 = {}
for m in T1:
    for v in variants(m):
        V1.setdefault(v, m)
V2 = {}
for m in T2:
    for v in variants(m):
        V2.setdefault(v, m)

print('标记表：T1(阻断) %d 个值 → %d 个变体；T2(报数) %d 个值 → %d 个变体'
      % (len(T1), len(V1), len(T2), len(V2)))


def run(args):
    cmd = ' '.join('"%s"' % a if ' ' in a else a for a in args)
    env = dict(os.environ)
    env.setdefault('npm_config_cache', os.path.join(TMP, 'npm-cache'))
    r = subprocess.run(cmd, cwd=R, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', shell=True, env=env)
    return r.returncode, (r.stdout or ''), (r.stderr or '')


# ── 1) 打包 ───────────────────────────────────────────────────────────────────
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
rc, out, err = run(['npm', 'pack', '--pack-destination', TMP])
print('\n[npm pack] rc=%s' % rc)
if rc != 0:
    print((err or out)[-900:]); sys.exit(1)
tgzs = [f for f in os.listdir(TMP) if f.endswith('.tgz')]
tgz = os.path.join(TMP, tgzs[0])
print('  产物 %s（%s B）' % (tgzs[0], os.path.getsize(tgz)))
ex = os.path.join(TMP, 'x')
os.makedirs(ex, exist_ok=True)
with tarfile.open(tgz) as t:
    t.extractall(ex)
pkg = os.path.join(ex, 'package')
packed = sorted(os.path.relpath(os.path.join(r, f), pkg).replace('\\', '/')
                for r, _, fs in os.walk(pkg) for f in fs)
print('  解包 %d 个文件' % len(packed))

# ── 2) 结构断言 ───────────────────────────────────────────────────────────────
struct = []
for rel in packed:
    top = rel.split('/')[0]
    if top not in TOP_OK:
        struct.append('顶层不在白名单：%s' % rel)
    for d in FORBID_DIRS:
        if rel.startswith(d):
            struct.append('禁入目录：%s' % rel)
    for w in FORBID_ANY:
        if w in rel:
            struct.append('禁入文件特征 %s：%s' % (w, rel))

tracked = subprocess.run(['git', '-C', R, 'ls-files'], capture_output=True, text=True,
                         encoding='utf-8').stdout.splitlines()
extra_in_pkg = [f for f in packed if f not in tracked and f != 'package.json']
print('  仓库跟踪 %d 个；包内不在跟踪集的：%s' % (len(tracked), extra_in_pkg or '无'))
if struct:
    print('  **结构断言未过**：')
    for s in struct[:20]:
        print('    ' + s)
else:
    print('  ✔ 结构断言通过（顶层白名单 / 无禁入目录 / 无缓存与库文件）')

# ── 3) 逐文件扫描 ─────────────────────────────────────────────────────────────
def read_any(path):
    raw = io.open(path, 'rb').read()
    for enc in ('utf-8', 'gbk', 'utf-16', 'latin-1'):
        try:
            return raw.decode(enc), enc
        except Exception:
            continue
    return None, None


h1, h2, hexes, unde = {}, {}, {}, []
leaks = []
for rel in packed:
    fp = os.path.join(pkg, rel.replace('/', os.sep))
    text, enc = read_any(fp)
    if text is None:
        unde.append(rel); continue
    nt = text.replace('\\\\', '\\').replace('/', '\\').lower()
    if re.search(r'session-[0-9a-f]{8}(?:-[0-9a-f-]+)?', text, re.I):
        leaks.append((rel, '真实会话 ID'))
    if re.search(r'[a-z]:\\users\\(?!<|%|\{)[^\\\s`]+', text, re.I):
        leaks.append((rel, '真实用户目录'))
    for v, m in V1.items():
        n = nt.count(v.lower())
        if n:
            h1.setdefault(rel, {})[m] = h1.get(rel, {}).get(m, 0) + n
    for v, m in V2.items():
        n = nt.count(v.lower())
        if n:
            h2.setdefault(rel, {})[m] = h2.get(rel, {}).get(m, 0) + n
    for x in set(re.findall(r'[0-9a-f]{32,}', text.lower())):
        hexes.setdefault(rel, []).append('%s…(%d)' % (x[:12], len(x)))

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
    found = sum(normalized.count(v.lower()) for v in V1)
    if found:
        repo_hits[rel] = found

print()
print('== T1 阻断级命中 ==')
if h1:
    for rel, d in sorted(h1.items()):
        print('  %-38s %d 个私密标记命中' % (rel, sum(d.values())))
        # A67：**把命中行定位出来（掩码）** —— 只说"3 处"没法修，等于把排查推给下一个人；
        #   标记本身也只显示前 2 字 + 长度，避免门禁输出自己变成泄漏面。
        try:
            _t, _ = read_any(os.path.join(pkg, rel.replace('/', os.sep)))
            _shown = 0
            for _i, _ln in enumerate((_t or '').splitlines(), 1):
                _low = _ln.replace('\\\\', '\\').replace('/', '\\').lower()
                _hit = sorted({str(m) for v, m in V1.items() if v.lower() in _low})
                if _hit and _shown < 6:
                    _s = _ln
                    for v in V1:
                        if v.lower() in _low:
                            _s = re.sub(re.escape(v), '«命中»', _s, flags=re.I)
                    print('      L%-4d %s   ← %s' % (_i, _s.strip()[:60],
                          ', '.join((h[:2] + '…(%d)' % len(h)) for h in _hit)))
                    _shown += 1
        except Exception as _e:
            print('      （定位失败：%s）' % _e)
    print('  合计 %d 个文件' % len(h1))
else:
    print('  无 ✔')
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
print('== ≥32 位十六进制串（人眼确认是否哈希）==')
if hexes:
    for rel, hs in sorted(hexes.items()):
        print('  %-38s %s' % (rel, ', '.join(hs[:5])))
else:
    print('  无')

if leaks:
    print('== 结构化隐私候选 ==')
    for rel, kind in leaks:
        print('  %s: %s' % (rel, kind))
ok = not struct and not h1 and not repo_hits and not extra_in_pkg and not leaks
print()
print('门禁判定：%s' % ('通过 ✔' if ok else '**未过，拒绝发布**'))

if not DO_PUBLISH:
    print('（干跑，未发布）')
    sys.exit(0 if ok else 2)

if not ok:
    sys.exit(2)

# ── 4) 发布 ───────────────────────────────────────────────────────────────────
print('\n[npm publish] 目标 registry.npmjs.org')
rc, out, err = run(['npm', 'publish', '--registry=https://registry.npmjs.org/'])
txt = (out or '') + (err or '')
for l in [l for l in txt.split('\n') if l.strip()][-5:]:
    print('  ' + l.strip())
print('  rc=%s' % rc)
if rc != 0:
    sys.exit(3)
json.dump({'files': packed, 'bytes': os.path.getsize(tgz)},
          io.open(os.path.join(TMP, 'packed.json'), 'w', encoding='utf-8'), ensure_ascii=False)
print('  已发布。发布面清单存 %s\\packed.json' % TMP)
