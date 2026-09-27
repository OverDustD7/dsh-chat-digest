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
PROFILE = os.path.join(os.environ.get('USERPROFILE', ''), '.dsh', 'profiles', 'web')
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
# 私密标记**只从 local/personal-tokens.txt 读**（local/ 已被 .gitignore 忽略）——
#   门禁脚本自身不许含任何私人值，否则它自己就成了泄露源。
EXTRA = []
_tok = os.path.join(R, 'local', 'personal-tokens.txt')
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
              'project', 'https:', 'http:', 'dsh', 'wxid', 'xwechat', '***REMOVED***-preset'}


def feed_config(path):
    if not os.path.isfile(path):
        return
    for line in io.open(path, encoding='utf-8', errors='replace').read().split('\n'):
        raw = line.split('#')[0].rstrip()
        s = raw.strip()
        if not s:
            continue
        if s.startswith('- '):          # 列表项（群名等）
            v = s[2:].strip()
        elif ':' in s:
            v = s.split(':', 1)[1].strip()
        else:
            continue
        v = v.strip().strip("'\"").strip().rstrip(',').strip().strip("'\"").strip()
        if not v or v in ('True', 'False', 'None', 'null'):
            continue
        if len(v) >= 5:
            T1.add(v)                    # 完整值 = 高危
        if '\\' in v or '/' in v:
            for seg in v.replace('/', '\\').split('\\'):
                seg = seg.strip()
                if len(seg) >= 5 and seg.lower() not in GENERIC_SEG:
                    T2.add(seg)


feed_config(os.path.join(R, 'local', 'pipeline.yaml'))
feed_config(os.path.join(R, 'local', 'pipeline.json'))
feed_config(os.path.join(PROFILE, 'cordis.patch.yml'))
T1 |= set(EXTRA)
# 通用/公开词不阻断、也不进报数档（否则满屏假阳性，范式 B：收了就虚报）
T1 = {m for m in T1 if m.lower() not in GENERIC_OK and m.lower() not in GENERIC_SEG and len(m) >= 5}
T2 = {m for m in T2 if m.lower() not in GENERIC_OK and len(m) >= 5}
T2 -= T1


def variants(m):
    out = {m, m.replace('\\', '/'), m.replace('\\', '\\\\'), m.replace('/', '\\')}
    try:
        out.add(urllib.parse.quote(m, safe=''))
    except Exception:
        pass
    return {x for x in out if len(x) >= 5}


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
print('  T1 例：%s' % ', '.join(sorted(T1)[:6]))


def run(args):
    cmd = ' '.join('"%s"' % a if ' ' in a else a for a in args)
    r = subprocess.run(cmd, cwd=R, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', shell=True)
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
                         encoding='utf-8').stdout.split()
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
for rel in packed:
    fp = os.path.join(pkg, rel.replace('/', os.sep))
    text, enc = read_any(fp)
    if text is None:
        unde.append(rel); continue
    nt = text.replace('\\\\', '\\').replace('/', '\\').lower()
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

print()
print('== T1 阻断级命中 ==')
if h1:
    for rel, d in sorted(h1.items()):
        print('  %-38s %s' % (rel, ', '.join('%s×%d' % (k, v) for k, v in sorted(d.items()))))
    print('  合计 %d 个文件' % len(h1))
else:
    print('  无 ✔')
print()
print('== T2 报数级命中（人眼判断，可能是通用段）==')
if h2:
    for rel, d in sorted(h2.items(), key=lambda kv: -sum(kv[1].values()))[:18]:
        print('  %-38s %s' % (rel, ', '.join('%s×%d' % (k, v) for k, v in
              sorted(d.items(), key=lambda kv: -kv[1])[:6])))
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

ok = not struct and not h1
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
