# -*- coding: utf-8 -*-
"""pconf 接收端的合成检查：包内 Python 模式（解释器 + vendor 工具定位）。

只用标准库。整个检查在一棵临时目录里搭 mini 包（复制公开 pconf.py），
假解释器与假工具都是普通文本/目录，从不执行；不读任何真实个人配置。
用法：python -B test/pconf-bundled-checks.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(HERE)
PCONF_SRC = os.path.join(PKG_ROOT, 'pipeline', 'pconf.py')
TMP_BASE = os.path.realpath(tempfile.gettempdir())

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

PASSED = []
FAILED = []
SKIPPED = []


def check(name, fn):
    try:
        fn()
        PASSED.append(name)
        sys.stdout.write('ok   %s\n' % name)
    except AssertionError as exc:
        FAILED.append(name)
        sys.stdout.write('FAIL %s :: %s\n' % (name, exc))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)


def seg_name():
    return 'win32-x64' if os.name == 'nt' else '%s-%s' % (sys.platform, 'x64')


def build_case(root, name, manifest=None, keep_manifest=True, keep_python=True,
               yaml_python='external', with_vendor=True, with_external=True):
    """搭一个 mini 包；返回各关键路径。"""
    case = os.path.join(root, name)
    pkg = os.path.join(case, 'pkg')
    profile = os.path.join(case, 'profile')
    ext_dir = os.path.join(case, 'external-tools')
    ext = os.path.join(case, 'external', 'python.exe')
    write(ext, 'fake external interpreter, never executed\n')
    if with_external:
        write(os.path.join(ext_dir, 'nt_msg_db_util', '3.export.py'), 'decoy export\n')
    os.makedirs(os.path.join(pkg, 'pipeline'), exist_ok=True)
    shutil.copyfile(PCONF_SRC, os.path.join(pkg, 'pipeline', 'pconf.py'))
    rt = os.path.join(pkg, 'runtime', seg_name())
    os.makedirs(os.path.join(rt, 'python'), exist_ok=True)
    fake_py = os.path.join(rt, 'python', 'python.exe')
    if keep_python:
        write(fake_py, 'fake bundled interpreter, never executed\n')
    elif os.path.exists(fake_py):
        os.remove(fake_py)
    if manifest is not None and keep_manifest:
        write(os.path.join(rt, 'manifest.json'), json.dumps(manifest))
    if with_vendor:
        write(os.path.join(rt, 'vendor', 'WeChatDataAnalysis', 'src',
                           'wechat_decrypt_tool', 'wechat_decrypt.py'), 'fake decryptor\n')
        write(os.path.join(rt, 'vendor', 'nt_msg_db_util', '3.export.py'), 'fake export\n')
    lines = []
    if yaml_python == 'external':
        lines.append("python: '%s'" % ext.replace('\\', '/'))
    elif yaml_python == 'missing':
        lines.append("python: '%s'" % os.path.join(case, 'gone', 'python.exe').replace('\\', '/'))
    if with_external:
        lines.append("external_dir: '%s'" % ext_dir.replace('\\', '/'))
    write(os.path.join(profile, 'pipeline.yaml'), '\n'.join(lines) + '\n')
    return {'case': case, 'pkg': pkg, 'profile': profile, 'rt': rt, 'ext': ext,
            'ext_dir': ext_dir, 'fake_py': fake_py}


def run_pconf(paths, expr='pconf.python_exe()', extra_env=None, drop_env=()):
    env = {k: v for k, v in os.environ.items() if not k.startswith('DSH_CHAT_FEED_')}
    env['DSH_CHAT_FEED_LOCAL'] = paths['profile']
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    for key in drop_env:
        env.pop(key, None)
    if extra_env:
        env.update(extra_env)
    runner = 'import sys\nimport pconf\nprint(%s)\n' % expr
    # runner 必须住在 pconf.py 同目录：Python 把脚本所在目录放进 sys.path，cwd 不作数
    runner_path = os.path.join(paths['pkg'], 'pipeline', '_runner.py')
    write(runner_path, runner)
    return subprocess.run([sys.executable, '-B', runner_path],
                          cwd=os.path.join(paths['pkg'], 'pipeline'),
                          env=env, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')


def bridge(root, py):
    return json.dumps({'schemaVersion': 1, 'root': root, 'python': py})


def norm(path):
    return os.path.normcase(os.path.realpath(path))


def make_dir_link(target, link):
    """建一个目录联接/符号链接；成功返回 None，失败返回异常对象（调用方如实 skip）。"""
    try:
        os.symlink(target, link, target_is_directory=True)
        return None
    except (OSError, NotImplementedError):
        pass
    if os.name == 'nt':
        # Windows 上 os.symlink 需要开发者模式；junction 不需要，用 PowerShell 建
        try:
            subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command',
                 "New-Item -ItemType Junction -Path '%s' -Target '%s' | Out-Null" % (link, target)],
                check=True, capture_output=True, text=True)
            return None if os.path.isdir(link) else OSError('junction not created')
        except Exception as exc:  # noqa: BLE001
            return exc
    return OSError('no link support')


# 创建后立刻捕获不可变规范根：清理时用它比对，而不是拿实时值和自己比
CREATED_ROOT = os.path.realpath(tempfile.mkdtemp(dir=TMP_BASE, prefix='dsh-chat-digest-pconf-'))
root = CREATED_ROOT

try:
    seg = seg_name()
    good_manifest = {'schemaVersion': 1, 'platform': seg.split('-')[0], 'arch': seg.split('-')[-1],
                     'python': 'python/python.exe'}

    # ── 解释器接收端（前轮已确认的边界，全部保留） ─────────────────────────
    def case_bundled_valid():
        paths = build_case(root, 'valid', manifest=good_manifest)
        result = run_pconf(paths, extra_env={
            'DSH_CHAT_FEED_BUNDLED_RUNTIME': bridge(paths['rt'], paths['fake_py']),
            'DSH_CHAT_FEED_PY': paths['ext'],
        })
        assert result.returncode == 0, 'rc=%s stderr=%s' % (result.returncode, result.stderr[-300:])
        assert norm(result.stdout.strip()) == norm(paths['fake_py']), 'stdout=%r' % result.stdout
        assert not os.path.exists(os.path.join(paths['case'], 'EXECUTED.marker')), '假解释器被执行了'

    def case_bundled_beats_yaml_and_env():
        paths = build_case(root, 'beats', manifest=good_manifest)
        result = run_pconf(paths, extra_env={
            'DSH_CHAT_FEED_BUNDLED_RUNTIME': bridge(paths['rt'], paths['fake_py']),
            'DSH_CHAT_FEED_PY': paths['ext'],
        })
        assert result.returncode == 0, result.stderr[-300:]
        chosen = norm(result.stdout.strip())
        assert chosen == norm(paths['fake_py']), 'selected=%r' % result.stdout
        assert chosen != norm(paths['ext']), '被外部解释器抢走了'

    def case_bad_json():
        paths = build_case(root, 'badjson', manifest=good_manifest)
        result = run_pconf(paths, extra_env={'DSH_CHAT_FEED_BUNDLED_RUNTIME': '{not json'})
        assert result.returncode != 0
        assert 'E_BUNDLED_JSON' in result.stderr, result.stderr[-200:]

    def case_empty_key():
        paths = build_case(root, 'emptykey', manifest=good_manifest)
        result = run_pconf(paths, extra_env={'DSH_CHAT_FEED_BUNDLED_RUNTIME': '   '})
        assert result.returncode != 0
        assert 'E_BUNDLED_EMPTY' in result.stderr, result.stderr[-200:]

    def case_escape_root():
        paths = build_case(root, 'escape-root', manifest=good_manifest)
        outside = os.path.join(paths['case'], 'outside-runtime')
        write(os.path.join(outside, 'python', 'python.exe'), 'outside fake\n')
        result = run_pconf(paths, extra_env={
            'DSH_CHAT_FEED_BUNDLED_RUNTIME': bridge(outside, os.path.join(outside, 'python', 'python.exe')),
        })
        assert result.returncode != 0
        assert 'E_BUNDLED_ESCAPE' in result.stderr, result.stderr[-200:]
        assert outside not in result.stderr, '错误里回显了外部路径'

    def case_missing_python():
        paths = build_case(root, 'missing-py', manifest=good_manifest, keep_python=False)
        result = run_pconf(paths, extra_env={
            'DSH_CHAT_FEED_BUNDLED_RUNTIME': bridge(paths['rt'], paths['fake_py']),
        })
        assert result.returncode != 0
        assert 'E_BUNDLED_MISSING' in result.stderr, result.stderr[-200:]

    def case_nul_in_python():
        paths = build_case(root, 'nul-py', manifest=good_manifest)
        result = run_pconf(paths, extra_env={
            'DSH_CHAT_FEED_BUNDLED_RUNTIME': bridge(paths['rt'], paths['fake_py'] + '\x00tail'),
        })
        assert result.returncode != 0
        assert 'E_BUNDLED_FIELD' in result.stderr and 'Traceback' not in result.stderr

    def case_bool_schema():
        paths = build_case(root, 'bool-schema', manifest=good_manifest)
        payload = json.dumps({'schemaVersion': True, 'root': paths['rt'], 'python': paths['fake_py']})
        result = run_pconf(paths, extra_env={'DSH_CHAT_FEED_BUNDLED_RUNTIME': payload})
        assert result.returncode != 0, 'schemaVersion=true 不能被当作 1'
        assert 'E_BUNDLED_SCHEMA' in result.stderr, result.stderr[-200:]

    def case_no_key_keeps_legacy_yaml():
        paths = build_case(root, 'legacy-yaml', manifest=good_manifest)
        result = run_pconf(paths, drop_env=('DSH_CHAT_FEED_BUNDLED_RUNTIME',))
        assert result.returncode == 0, result.stderr[-300:]
        assert norm(result.stdout.strip()) == norm(paths['ext']), 'stdout=%r' % result.stdout

    def case_no_key_missing_yaml_falls_back():
        paths = build_case(root, 'legacy-fallback', manifest=good_manifest, yaml_python='missing')
        result = run_pconf(paths, drop_env=('DSH_CHAT_FEED_BUNDLED_RUNTIME',))
        assert result.returncode == 0, result.stderr[-300:]
        assert norm(result.stdout.strip()) == norm(sys.executable), 'stdout=%r' % result.stdout

    def case_no_key_env_only():
        paths = build_case(root, 'legacy-env', manifest=good_manifest, yaml_python=None)
        result = run_pconf(paths, extra_env={'DSH_CHAT_FEED_PY': paths['ext']},
                           drop_env=('DSH_CHAT_FEED_BUNDLED_RUNTIME',))
        assert result.returncode == 0, result.stderr[-300:]
        assert norm(result.stdout.strip()) == norm(paths['ext']), 'stdout=%r' % result.stdout

    # ── vendor 工具定位 ────────────────────────────────────────────────────
    def case_vendor_qq_file():
        paths = build_case(root, 'vendor-qq', manifest=good_manifest)
        expect = os.path.join(paths['rt'], 'vendor', 'nt_msg_db_util', '3.export.py')
        result = run_pconf(paths, expr='pconf.external_tool("nt_msg_db_util", "3.export.py")',
                           extra_env={'DSH_CHAT_FEED_BUNDLED_RUNTIME': bridge(paths['rt'], paths['fake_py'])})
        assert result.returncode == 0, result.stderr[-300:]
        got = norm(result.stdout.strip())
        assert got == norm(expect), 'got=%r' % result.stdout
        assert got != norm(os.path.join(paths['ext_dir'], 'nt_msg_db_util', '3.export.py'))

    def case_vendor_wechat_dir():
        paths = build_case(root, 'vendor-wx', manifest=good_manifest)
        expect = os.path.join(paths['rt'], 'vendor', 'WeChatDataAnalysis')
        result = run_pconf(paths, expr='pconf.external_tool("WeChatDataAnalysis")',
                           extra_env={'DSH_CHAT_FEED_BUNDLED_RUNTIME': bridge(paths['rt'], paths['fake_py'])})
        assert result.returncode == 0, result.stderr[-300:]
        assert norm(result.stdout.strip()) == norm(expect), 'got=%r' % result.stdout

    def case_vendor_missing():
        paths = build_case(root, 'vendor-missing', manifest=good_manifest, with_vendor=False)
        result = run_pconf(paths, expr='pconf.external_tool("nt_msg_db_util", "3.export.py")',
                           extra_env={'DSH_CHAT_FEED_BUNDLED_RUNTIME': bridge(paths['rt'], paths['fake_py'])})
        assert result.returncode != 0, '缺工具时必须失败，不能回 private external_dir'
        assert 'E_VENDOR_MISSING' in result.stderr, result.stderr[-200:]

    def case_vendor_dotdot():
        paths = build_case(root, 'vendor-dotdot', manifest=good_manifest)
        result = run_pconf(paths, expr='pconf.external_tool("..", "outside")',
                           extra_env={'DSH_CHAT_FEED_BUNDLED_RUNTIME': bridge(paths['rt'], paths['fake_py'])})
        assert result.returncode != 0
        assert 'E_VENDOR_PARTS' in result.stderr, result.stderr[-200:]

    def case_vendor_junction_escape():
        paths = build_case(root, 'vendor-escape', manifest=good_manifest)
        target = os.path.join(paths['rt'], 'vendor', 'nt_msg_db_util')
        outside = os.path.join(paths['case'], 'outside-tools')
        write(os.path.join(outside, '3.export.py'), 'outside\n')
        shutil.rmtree(target)
        link_error = make_dir_link(outside, target)
        if link_error is not None:
            SKIPPED.append('vendor 联接逃逸（本机建不出目录联接：%s）' % link_error.__class__.__name__)
            return
        result = run_pconf(paths, expr='pconf.external_tool("nt_msg_db_util", "3.export.py")',
                           extra_env={'DSH_CHAT_FEED_BUNDLED_RUNTIME': bridge(paths['rt'], paths['fake_py'])})
        assert result.returncode != 0, '联接逃逸必须失败'
        assert 'E_VENDOR_ESCAPE' in result.stderr, result.stderr[-200:]
        assert outside not in result.stderr, '错误里回显了外部路径'

    def case_no_key_uses_external_dir():
        paths = build_case(root, 'legacy-external', manifest=good_manifest)
        expect = os.path.join(paths['ext_dir'], 'nt_msg_db_util', '3.export.py')
        result = run_pconf(paths, expr='pconf.external_tool("nt_msg_db_util", "3.export.py")',
                           drop_env=('DSH_CHAT_FEED_BUNDLED_RUNTIME',))
        assert result.returncode == 0, result.stderr[-300:]
        assert norm(result.stdout.strip()) == norm(expect), 'got=%r' % result.stdout

    for name, fn in [
        ('bundled 模式选包内解释器，且不执行它', case_bundled_valid),
        ('bundled 同时压过私人 YAML 与继承的环境变量', case_bundled_beats_yaml_and_env),
        ('内部键是坏 JSON：明确失败', case_bad_json),
        ('内部键为空：明确失败', case_empty_key),
        ('root 逃到包外：明确失败且不回显外部路径', case_escape_root),
        ('声明的解释器缺失：明确失败', case_missing_python),
        ('路径含 NUL：明确失败且不留 traceback', case_nul_in_python),
        ('schemaVersion 是布尔 true：不当成 1', case_bool_schema),
        ('没有内部键：私人 YAML 仍然生效', case_no_key_keeps_legacy_yaml),
        ('没有内部键：YAML 指向不存在时警告并回退', case_no_key_missing_yaml_falls_back),
        ('没有内部键：只有环境变量时照样生效', case_no_key_env_only),
        ('vendor 里的 QQ 导出脚本被选中（私人 external_dir 抢不走）', case_vendor_qq_file),
        ('vendor 里的 WeChat 目录被选中', case_vendor_wechat_dir),
        ('vendor 缺工具：明确失败', case_vendor_missing),
        ('vendor 的 parts 含点点段：拒绝', case_vendor_dotdot),
        ('vendor 目标经联接逃出 runtime：明确失败', case_vendor_junction_escape),
        ('没有内部键：external_dir 旧行为保持', case_no_key_uses_external_dir),
    ]:
        check(name, fn)
finally:
    # 只认创建时捕获的那个根：当前 realpath 必须仍等于它，且不是系统 temp 本身、不在其外
    try:
        current_real = os.path.realpath(CREATED_ROOT)
    except OSError:
        current_real = None
    if current_real == CREATED_ROOT and CREATED_ROOT != TMP_BASE \
            and CREATED_ROOT.startswith(TMP_BASE + os.sep) and not os.path.islink(CREATED_ROOT):
        shutil.rmtree(CREATED_ROOT, ignore_errors=True)
        sys.stdout.write('清理完成：%s\n' % ('仍存在' if os.path.exists(CREATED_ROOT) else '已删除'))
    else:
        sys.stdout.write('清理跳过：目标不是本次创建的唯一临时子目录\n')

sys.stdout.write('\n通过 %d / 失败 %d%s\n' % (len(PASSED), len(FAILED),
                                            (' / 跳过 %d' % len(SKIPPED)) if SKIPPED else ''))
for item in SKIPPED:
    sys.stdout.write('skip %s\n' % item)
raise SystemExit(1 if FAILED else 0)
