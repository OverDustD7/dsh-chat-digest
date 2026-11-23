# -*- coding: utf-8 -*-
'''打包准入规则检查（隔离 fixture；**不跑真实发布门禁**）。

它不调用 `main()`：不跑 `npm pack`、不触发 `prepack`、不联网、不读真实私人配置。
做法是 import `tools/gate-publish.py` 里的纯函数，用合成的目录与清单验证规则本身。

运行：
    CF_FIXTURE_ROOT=<某个空目录> python test/packaging-admission-checks.py

所有写入都在 CF_FIXTURE_ROOT 下；不提供这个变量就直接失败（免得顺手写进系统临时目录）。
退出码：0 全过，1 有失败。
'''
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

FAILS = []
CHECKS = [0]


def check(name, cond, detail=''):
    CHECKS[0] += 1
    if not cond:
        FAILS.append('%s%s' % (name, ('：' + detail) if detail else ''))


def load_gate():
    path = os.path.join(REPO, 'tools', 'gate-publish.py')
    spec = importlib.util.spec_from_file_location('cf_gate_publish', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256(path):
    h = hashlib.sha256()
    with io.open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, 'w', encoding='utf-8').write(text)


def build_lock(pkg, rels, root='runtime/win32-x64'):
    files = []
    for rel in sorted(rels):
        fp = os.path.join(pkg, rel.replace('/', os.sep))
        files.append({'path': rel, 'bytes': os.path.getsize(fp), 'sha256': sha256(fp)})
    return {'schemaVersion': 1, 'runtimeRoot': root, 'platform': 'win32', 'arch': 'x64',
            'files': files}


def make_dir_link(link, target):
    """造一个目录联接/符号链接（合成数据，目标也在本轮假根内）。失败返回 False。"""
    try:
        os.symlink(target, link, target_is_directory=True)
        if os.path.isdir(link):
            return True
    except (OSError, NotImplementedError, AttributeError):
        pass
    try:
        r = subprocess.run(['cmd', '/c', 'mklink', '/J', link, target],
                           capture_output=True, text=True)
        return r.returncode == 0 and os.path.isdir(link)
    except (OSError, ValueError):
        return False


RUNTIME_FILES = [
    'runtime/win32-x64/manifest.json',
    'runtime/win32-x64/python/python.exe',
    'runtime/win32-x64/vendor/WeChatDataAnalysis/src/wechat_decrypt_tool/wechat_decrypt.py',
    'runtime/win32-x64/vendor/nt_msg_db_util/3.export.py',
]


def make_runtime(pkg):
    """合成一份最小 runtime：结构与真实包一致，字节是合成的（从不执行）。"""
    write(os.path.join(pkg, 'runtime', 'win32-x64', 'manifest.json'), json.dumps({
        'schemaVersion': 1, 'platform': 'win32', 'arch': 'x64',
        'python': 'python/python.exe',
        'tools': {
            'wechat-decrypt': 'vendor/WeChatDataAnalysis/src/wechat_decrypt_tool/wechat_decrypt.py',
            'nt_msg_db_util-export': 'vendor/nt_msg_db_util/3.export.py',
        },
    }, ensure_ascii=False))
    write(os.path.join(pkg, 'runtime', 'win32-x64', 'python', 'python.exe'), 'synthetic-interpreter')
    write(os.path.join(pkg, 'runtime', 'win32-x64', 'vendor', 'WeChatDataAnalysis', 'src',
                       'wechat_decrypt_tool', 'wechat_decrypt.py'), 'class WeChatDatabaseDecryptor: pass\n')
    write(os.path.join(pkg, 'runtime', 'win32-x64', 'vendor', 'nt_msg_db_util', '3.export.py'),
          'def main():\n    return 0\n')


def mutate_dirs(pkg, packs):
    """为负例准备同一份文件的第二、三个版本（不改正例用到的目录）。"""
    return pkg, packs


def main():
    root_env = os.environ.get('CF_FIXTURE_ROOT')
    if not root_env or not os.path.isabs(root_env):
        print('FAIL: 必须显式给 CF_FIXTURE_ROOT 绝对路径')
        return 1
    base = os.path.realpath(root_env)
    if os.path.isdir(base) and os.listdir(base):
        print('FAIL: CF_FIXTURE_ROOT 必须是空目录（避免误删已有内容）')
        return 1
    os.makedirs(base, exist_ok=True)

    npm = os.path.join(base, 'npm')
    dsh_home = os.path.join(base, 'dsh_home')
    private = os.path.join(base, 'private')
    host_profile = os.path.join(base, 'host_profile')
    pkg = os.path.join(base, 'pkg')
    temp_base = os.path.join(base, 'temp_base')
    lock_root = os.path.join(base, 'lockrepo')
    for d in (npm, dsh_home, private, host_profile, pkg, temp_base, lock_root):
        os.makedirs(d, exist_ok=True)

    # 隔离的环境：npm 的 user/global 配置与缓存都指向 fixture 内，且离线 + 不跑脚本
    os.environ['DSH_HOME'] = dsh_home
    os.environ['DSH_CHAT_FEED_LOCAL'] = private
    os.environ['npm_config_userconfig'] = os.path.join(npm, 'npmrc')
    os.environ['npm_config_globalconfig'] = os.path.join(npm, 'global-npmrc')
    os.environ['npm_config_cache'] = os.path.join(npm, 'cache')
    os.environ['npm_config_offline'] = 'true'
    os.environ['npm_config_ignore_scripts'] = 'true'

    private_token = 'ZQSYNTH9137'
    pipeline_value = 'ZQ-TOKEN-778812'
    host_value = 'zqmodel4412x'
    long_hex = 'ab' * 20

    write(os.path.join(private, 'pipeline.yaml'),
          'self_wxid: "%s"\nwx_key_dir: "X:\\ExampleWorkspace\\fixture-private\\wxkeys"\n' % private_token)
    write(os.path.join(private, 'personal-tokens.txt'), '# 合成标记\n%s\n' % pipeline_value)
    write(os.path.join(host_profile, 'cordis.patch.yml'), 'model: "%s"\n' % host_value)

    gate = load_gate()

    # ── A. import 本身没有副作用 ─────────────────────────────────────────────
    check('模块根指向仓库', os.path.realpath(gate.R) == os.path.realpath(REPO), gate.R)
    check('私人目录由环境决定', os.path.realpath(gate.PRIVATE) == os.path.realpath(private), gate.PRIVATE)
    check('import 不建临时根', not [n for n in os.listdir(temp_base) if n.startswith('cf-gate2-')])
    check('模块有 main', callable(getattr(gate, 'main', None)))

    # ── B. 标记表与"不回显原值" ──────────────────────────────────────────────
    v1, v2, info = gate.build_marker_tables(private, host_profile)
    marks = set(v1.values())
    check('T1 收到 pipeline.yaml 的值', private_token in marks, str(sorted(marks)))
    check('T1 收到个人标记文件的值', pipeline_value in marks)
    check('T1 收到 host profile 的值', host_value in marks)
    check('标记表计数自洽', info['t1'] == len(set(v1.values())) and info['v1'] >= info['t1'], str(info))

    leaky = os.path.join(pkg, 'lib', 'leaky.js')
    write(leaky, 'const a = "%s";\nconst b = "%s";\nconst h = "%s";\n' % (private_token, pipeline_value, long_hex))
    text = io.open(leaky, encoding='utf-8').read()
    h1, h2 = gate.count_hits(text, v1, v2)
    check('命中被算出来', sum(h1.values()) >= 2, str(h1))

    buf = io.StringIO()
    gate.report_t1({'lib/leaky.js': h1}, pkg, v1, emit=lambda s: buf.write(s + '\n'))
    out1 = buf.getvalue()
    check('T1 报告不含原值', private_token not in out1 and pipeline_value not in out1, out1[:200])
    check('T1 报告给出位置', ('L1' in out1) and ('命中=M' in out1), out1[:200])
    buf2 = io.StringIO()
    gate.report_hex({'lib/leaky.js': [len(long_hex)]}, emit=lambda s: buf2.write(s + '\n'))
    out2 = buf2.getvalue()
    check('hex 报告不含片段', long_hex[:12] not in out2, out2[:200])
    check('hex 报告只给长度', str(len(long_hex)) in out2, out2[:200])

    # ── C. 正例：runtime 被接受 ──────────────────────────────────────────────
    make_runtime(pkg)
    packed = list(RUNTIME_FILES)
    lock = build_lock(pkg, RUNTIME_FILES)
    check('正例结构断言通过', gate.structure_problems(packed) == [], str(gate.structure_problems(packed)[:3]))
    check('正例 runtime 准入通过', gate.runtime_admission_problems(pkg, packed, lock) == [],
          str(gate.runtime_admission_problems(pkg, packed, lock)[:3]))
    exempt, extra = gate.asset_exemptions(packed, [], lock)
    check('冻结清单内文件算精确例外', sorted(exempt) == sorted(RUNTIME_FILES))
    check('例外之外没有多余未跟踪文件', extra == [], str(extra))

    # 普通源码仍然要查：未跟踪且不在清单里就不算例外
    ordinary = packed + ['pipeline/favorites.py']
    write(os.path.join(pkg, 'pipeline', 'favorites.py'), 'x = 1\n')
    _, extra2 = gate.asset_exemptions(ordinary, [], lock)
    check('普通源码仍在未跟踪名单里', extra2 == ['pipeline/favorites.py'], str(extra2))

    # ── D. 负例：未知 / 私有 / 库 / 篡改 / 缺失 / 越界 ────────────────────────
    write(os.path.join(pkg, 'runtime', 'win32-x64', 'python', 'evil.dll'), 'MZ')
    probs = gate.runtime_admission_problems(pkg, RUNTIME_FILES + ['runtime/win32-x64/python/evil.dll'], lock)
    check('未知 runtime 文件被拒', any('未知文件' in p for p in probs), str(probs[:3]))
    os.remove(os.path.join(pkg, 'runtime', 'win32-x64', 'python', 'evil.dll'))

    for bad_rel, why in (('runtime/win32-x64/.env', '禁入文件特征 .env'),
                         ('runtime/win32-x64/python/account_keys.json', '禁入文件特征 account_keys.json'),
                         ('runtime/win32-x64/python/x.db', '禁入文件特征 .db')):
        probs = gate.structure_problems([bad_rel])
        check('私有/库文件被结构断言拒绝（%s）' % bad_rel, any(why in p for p in probs), str(probs))
        probs = gate.runtime_admission_problems(pkg, RUNTIME_FILES + [bad_rel], lock)
        check('私有/库文件也不在冻结清单里（%s）' % bad_rel, any('未知文件' in p for p in probs), str(probs))

    probs = gate.structure_problems(['pipeline/output/x.json'])
    check('pipeline 私有目录仍禁入', any('禁入目录' in p for p in probs), str(probs))
    probs = gate.structure_problems(['scripts/tool.js'])
    check('顶层白名单外仍拒绝', any('顶层不在白名单' in p for p in probs), str(probs))

    target = os.path.join(pkg, 'runtime', 'win32-x64', 'python', 'python.exe')
    original = io.open(target, encoding='utf-8').read()
    write(target, original + 'tampered')
    probs = gate.runtime_admission_problems(pkg, RUNTIME_FILES, lock)
    check('篡改内容被拒', any('内容被改动' in p for p in probs), str(probs[:3]))
    write(target, original)

    probs = gate.runtime_admission_problems(pkg, [p for p in RUNTIME_FILES if not p.endswith('3.export.py')], lock)
    check('冻结文件缺失被拒', any('冻结文件缺失' in p for p in probs), str(probs[:3]))

    bad_manifest = json.loads(io.open(os.path.join(pkg, 'runtime', 'win32-x64', 'manifest.json'),
                                      encoding='utf-8').read())
    bad_manifest['python'] = '../python.exe'
    write(os.path.join(pkg, 'runtime', 'win32-x64', 'manifest.json'), json.dumps(bad_manifest))
    probs = gate.runtime_manifest_problems(pkg, lock)
    check('manifest 点点段被拒', any('点点段' in p for p in probs), str(probs[:3]))

    bad_manifest['python'] = 'python/python.exe'
    bad_manifest['tools'] = dict(bad_manifest.get('tools') or {})
    bad_manifest['tools']['extra'] = 'vendor/not-in-lock.py'
    write(os.path.join(pkg, 'runtime', 'win32-x64', 'manifest.json'), json.dumps(bad_manifest))
    probs = gate.runtime_manifest_problems(pkg, lock)
    check('manifest 指向清单外文件被拒', any('不在冻结清单' in p for p in probs), str(probs[:3]))
    make_runtime(pkg)

    # ── D2. 祖先目录被换成指向包外的联接：叶子 hash 相同也不许过 ──────────────
    esc_pkg = os.path.join(base, 'escape-pkg')
    outside = os.path.join(base, 'outside-python')
    write(os.path.join(outside, 'python.exe'), 'same-bytes-outside')
    write(os.path.join(esc_pkg, 'runtime', 'win32-x64', 'manifest.json'), json.dumps({
        'schemaVersion': 1, 'platform': 'win32', 'arch': 'x64', 'python': 'python/python.exe',
    }))
    link_dir = os.path.join(esc_pkg, 'runtime', 'win32-x64', 'python')
    os.makedirs(os.path.dirname(link_dir), exist_ok=True)
    linked = make_dir_link(link_dir, outside)
    check('能造出目录联接（祖先用例前提）', linked, '本机无法构造目录联接')
    if linked:
        esc_rel = ['runtime/win32-x64/manifest.json', 'runtime/win32-x64/python/python.exe']
        esc_lock = build_lock(esc_pkg, esc_rel)
        # 前提：链接指向的那份内容与冻结哈希确实一致（所以"同 hash"不是借口）
        check('联接外的文件确实同 hash',
              esc_lock['files'][1]['sha256'] == gate.sha256_file(os.path.join(outside, 'python.exe')))
        probs = gate.runtime_admission_problems(esc_pkg, esc_rel, esc_lock)
        check('祖先目录是联接时被拒', any('祖先目录是链接' in p for p in probs), str(probs[:3]))
        check('祖先联接没有被误报成哈希不符', not any('内容被改动' in p for p in probs), str(probs[:3]))
        os.rmdir(link_dir)
        shutil.copytree(outside, link_dir)
        check('换成真实目录后同 hash 通过',
              gate.runtime_admission_problems(esc_pkg, esc_rel, esc_lock) == [],
              str(gate.runtime_admission_problems(esc_pkg, esc_rel, esc_lock)[:3]))

    # ── E. 冻结清单加载器 ────────────────────────────────────────────────────
    good_lock_path = os.path.join(lock_root, gate.RUNTIME_LOCK_REL)
    write(good_lock_path, json.dumps(lock))
    loaded, err = gate.load_runtime_lock(lock_root)
    check('清单能加载', loaded is not None and err is None, str(err))
    broken = dict(lock)
    broken['files'] = [{'path': RUNTIME_FILES[0], 'sha256': 'not-a-hash'}]
    write(good_lock_path, json.dumps(broken))
    loaded2, err2 = gate.load_runtime_lock(lock_root)
    check('坏清单被拒', loaded2 is None and bool(err2), str(err2))

    # ── E2. 形状判据：UTF-16 文本照拦，例外只给冻结哈希证明过的具体文件 ─────
    user_dir = 'C:\\Users\\' + 'somebody' + '\\secret'
    session = 'session-' + '0123abcd' + '-0000'
    utf16_path = os.path.join(base, 'utf16-note.txt')
    with io.open(utf16_path, 'wb') as fh:
        fh.write(('见 %s 与 %s\n' % (user_dir, session)).encode('utf-16'))
    text16, enc16 = gate.read_any(utf16_path)
    check('UTF-16 文本确实按 utf-16 解码', text16 is not None and enc16 == 'utf-16', str(enc16))
    kinds = gate.shape_leak_problems('notes/utf16-note.txt', text16, set())
    check('UTF-16 文本里的用户目录仍被拦', '真实用户目录' in kinds, str(kinds))
    check('UTF-16 文本里的会话 ID 仍被拦', '真实会话 ID' in kinds, str(kinds))
    check('非 runtime 文件即使像二进制也照拦',
          gate.shape_leak_problems('lib/blob.bin', text16, set()) != [], '未拦')

    frozen = {'runtime/win32-x64/vendor/x/thing.pyd'}
    check('冻结过的官方 runtime 资产按文件豁免',
          gate.shape_leak_problems('runtime/win32-x64/vendor/x/thing.pyd', text16, frozen) == [])
    check('runtime 里没进冻结清单的文件不豁免',
          gate.shape_leak_problems('runtime/win32-x64/vendor/x/other.pyd', text16, frozen) != [])
    check('runtime 之外的文本不豁免',
          gate.shape_leak_problems('notes/utf16-note.txt', text16, frozen) != [])
    check('干净文本不误报',
          gate.shape_leak_problems('lib/clean.js', 'no paths here', frozen) == [])

    # ── F. tar 条目校验 ──────────────────────────────────────────────────────    check('普通条目放行', gate.tar_member_problems(['package/lib/plugin.js', 'package/README.md']) == [])
    for bad, why in ((['/etc/passwd'], '绝对路径'),
                     (['../evil'], '点点'),
                     (['package/../../evil'], '点点'),
                     (['C:/x'], '盘符'),
                     (['package/a\\b'], '反斜杠'),
                     (['package/CON.txt'], '保留设备名'),
                     (['package/a.'], '尾随点'),
                     (['package/a '], '尾随点或空格'),
                     (['package/a:b'], 'ADS'),
                     (['package/A.js', 'package/a.js'], '大小写冲突')):
        probs = gate.tar_member_problems(bad)
        check('危险 tar 条目被拒（%s）' % why, any(why in p for p in probs), str(probs))

    tar_dir = os.path.join(base, 'tars')
    os.makedirs(tar_dir, exist_ok=True)
    ok_tar = os.path.join(tar_dir, 'ok.tar')
    with tarfile.open(ok_tar, 'w') as t:
        info = tarfile.TarInfo('package/lib/plugin.js')
        payload = b'// x\n'
        info.size = len(payload)
        t.addfile(info, io.BytesIO(payload))
    dest = os.path.join(tar_dir, 'ok')
    check('安全 tar 能解', gate.extract_tar_safely(ok_tar, dest) == 1)
    check('安全 tar 解出文件', os.path.isfile(os.path.join(dest, 'package', 'lib', 'plugin.js')))

    evil_tar = os.path.join(tar_dir, 'evil.tar')
    with tarfile.open(evil_tar, 'w') as t:
        info = tarfile.TarInfo('../evil.txt')
        payload = b'x'
        info.size = len(payload)
        t.addfile(info, io.BytesIO(payload))
    try:
        gate.extract_tar_safely(evil_tar, os.path.join(tar_dir, 'evil'))
        check('点点 tar 被拒', False, '没有抛错')
    except ValueError:
        check('点点 tar 被拒', True)
    check('被拒的 tar 没有落地', not os.path.exists(os.path.join(base, 'evil.txt')))

    link_tar = os.path.join(tar_dir, 'link.tar')
    with tarfile.open(link_tar, 'w') as t:
        info = tarfile.TarInfo('package/link')
        info.type = tarfile.SYMTYPE
        info.linkname = '/etc/passwd'
        t.addfile(info)
    try:
        gate.extract_tar_safely(link_tar, os.path.join(tar_dir, 'link'))
        check('链接 tar 被拒', False, '没有抛错')
    except ValueError:
        check('链接 tar 被拒', True)

    # ── G. 临时根：唯一新建、不碰共享 cf-gate2 ───────────────────────────────
    shared = os.path.join(temp_base, 'cf-gate2')
    write(os.path.join(shared, 'old-report.txt'), 'do not delete me')
    r1 = gate.make_work_root(temp_base)
    r2 = gate.make_work_root(temp_base)
    check('临时根唯一', r1 != r2, r1 + ' vs ' + r2)
    check('临时根都在指定基目录下',
          os.path.dirname(r1) == temp_base and os.path.dirname(r2) == temp_base)
    check('临时根带前缀', os.path.basename(r1).startswith('cf-gate2-'))
    check('临时根不是共享的旧目录', os.path.realpath(r1) != os.path.realpath(shared))
    check('safe_rmtree 不删共享 cf-gate2', gate.safe_rmtree(shared, temp_base) is False)
    check('共享 cf-gate2 仍在', os.path.isfile(os.path.join(shared, 'old-report.txt')))
    check('safe_rmtree 不删基目录', gate.safe_rmtree(temp_base, temp_base) is False)
    check('safe_rmtree 拒绝基目录之外的路径', gate.safe_rmtree(r1, private) is False)
    check('safe_rmtree 删自己新建的', gate.safe_rmtree(r2, temp_base) is True)
    check('自己新建的确实没了', not os.path.exists(r2))

    # ── G2. 所有权：只认本轮登记过、且身份没被换掉的那个目录 ─────────────────
    sibling = os.path.join(temp_base, 'cf-gate2-sibling')
    write(os.path.join(sibling, 'keep.txt'), 'keep')
    check('同前缀但非本轮创建的兄弟目录不删', gate.safe_rmtree(sibling, temp_base) is False)
    check('兄弟目录仍在', os.path.isfile(os.path.join(sibling, 'keep.txt')))

    owned = gate.make_work_root(temp_base)
    alias = os.path.join(temp_base, 'cf-gate2-alias')
    alias_ok = make_dir_link(alias, owned)
    check('能造出指向本轮临时根的联接', alias_ok, '本机无法构造目录联接')
    if alias_ok:
        check('联接参数不被当作可删对象', gate.safe_rmtree(alias, temp_base) is False)
        check('联接目标没有借身份被删掉', os.path.isdir(owned))
        os.rmdir(alias)
    check('去掉联接后登记过的临时根能删', gate.safe_rmtree(owned, temp_base) is True)

    # 删除未完成不许谎报成功：把 rmtree 换成什么都不做的替身，函数必须自己复核
    owned2 = gate.make_work_root(temp_base)
    write(os.path.join(owned2, 'x.txt'), 'x')
    real_rmtree = shutil.rmtree
    shutil.rmtree = lambda p, *a, **k: None
    try:
        lied = gate.safe_rmtree(owned2, temp_base)
    finally:
        shutil.rmtree = real_rmtree
    check('删除未完成不谎报成功', lied is False)
    check('没删掉的目录仍在', os.path.isdir(owned2))
    check('真删时仍报成功', gate.safe_rmtree(owned2, temp_base) is True)

    # 真·删除受阻（Windows 上被打开的文件默认不许删）—— 本机允许删就记环境差异，不算失败
    owned3 = gate.make_work_root(temp_base)
    held = os.path.join(owned3, 'held.txt')
    write(held, 'held')
    fh = io.open(held, 'r')
    try:
        blocked = gate.safe_rmtree(owned3, temp_base)
    finally:
        fh.close()
    if blocked:
        check('本机允许删除被打开的文件（记环境差异，不计失败）', True)
    else:
        check('打开的文件让删除失败时如实返回 False', os.path.isdir(owned3))
    gate.safe_rmtree(owned3, temp_base)

    # ── H. 正式归档准入与私有冻结资产边界 ─────────────────────────────
    release_files = ['lib/plugin.js', 'pipeline/qq_decrypt_hex.py']
    packed = ['package.json', 'README.md', *release_files]
    check('公开归档只含声明文件及批准的隐式根文件', not gate.public_archive_problems(packed, release_files))
    check('额外根 README 被拒', bool(gate.public_archive_problems(packed + ['README.private.md'], release_files)))
    check('冻结资产不能通过正向清单重新准入',
          bool(gate.public_archive_problems(packed + RUNTIME_FILES, release_files + RUNTIME_FILES)))
    check('显式外置目录被拒',
          bool(gate.public_archive_problems(packed + ['pipeline/vendor/tool.py'],
                                            release_files + ['pipeline/vendor/tool.py'])))
    check('声明文件缺失被拒', bool(gate.public_archive_problems(packed[:-1], release_files)))

    # ── 收尾 ────────────────────────────────────────────────────────────────
    print('检查项 %d；失败 %d' % (CHECKS[0], len(FAILS)))
    for f in FAILS:
        print('  FAIL ' + f)
    return 0 if not FAILS else 1


if __name__ == '__main__':
    code = main()
    root_env = os.environ.get('CF_FIXTURE_ROOT')
    if code == 0 and root_env and os.path.isdir(root_env):
        root_real = os.path.realpath(root_env)
        if os.path.dirname(root_real) and os.path.basename(root_real).startswith('cf-admission-'):
            shutil.rmtree(root_real, ignore_errors=True)
    sys.exit(code)
