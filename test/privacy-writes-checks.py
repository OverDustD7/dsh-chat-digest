# -*- coding: utf-8 -*-
"""隐私写入与打包排除的合成检查。

三件事，各在一个临时 mini 包里跑，绝不执行真实第三方模块/假解释器/解密工具：

1. `daily_prep.run` 在私有工作目录建不出来时：不调用 subprocess、返回失败结果、保留 critical；
   以及正常步骤里已知解密 key 不进标题/尾部回显。
2. 两个微信包装脚本的**初始化前缀**（截到 importlib 供应商导入之前）：公共 cwd 与外部诱饵
   env 都不能改变私有 tool-state，profile 在包内或联接逃逸必须明确拒绝。
3. 复制真实的 package.json `files` 到 mini 包，用 npm pack --dry-run 证明公共源码保留、
   私有产物被排除；npm 的用户/全局配置与缓存全部指向临时空文件/目录。

用法：python -B test/privacy-writes-checks.py
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(HERE)
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
    with io.open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)


def norm(path):
    return os.path.normcase(os.path.realpath(path))


def make_dir_link(target, link):
    try:
        os.symlink(target, link, target_is_directory=True)
        return None
    except (OSError, NotImplementedError):
        pass
    if os.name == 'nt':
        try:
            subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                            "New-Item -ItemType Junction -Path '%s' -Target '%s' | Out-Null"
                            % (link, target)], check=True, capture_output=True, text=True)
            return None if os.path.isdir(link) else OSError('junction not created')
        except Exception as exc:  # noqa: BLE001
            return exc
    return OSError('no link support')


CREATED_ROOT = os.path.realpath(tempfile.mkdtemp(dir=TMP_BASE, prefix='dsh-chat-digest-privacy-'))
root = CREATED_ROOT


def make_mini_pkg(name, profile_yaml_extra=''):
    """建一个 mini 包：复制 pconf.py / daily_prep.py / 两个 wx 包装 + 合成 profile。"""
    pkg = os.path.join(root, name, 'pkg')
    profile = os.path.join(root, name, 'profile')
    os.makedirs(os.path.join(pkg, 'pipeline'), exist_ok=True)
    for src in ('pconf.py', 'daily_prep.py', 'wx_decrypt3.py', 'wx_decrypt_more.py'):
        shutil.copyfile(os.path.join(PKG_ROOT, 'pipeline', src), os.path.join(pkg, 'pipeline', src))
    write(os.path.join(profile, 'pipeline.yaml'),
          "self_qq: '10001'\n"
          "wx_key: 'synthetic-wx-key-for-import-only'\n"
          "qq_key: 'synthetic-qq-key-for-import-only'\n"
          "external_dir: '%s'\n"
          "qq_data_dir: '%s'\n%s"
          % (os.path.join(root, name, 'external').replace('\\', '/'),
             os.path.join(root, name, 'qq').replace('\\', '/'),
             profile_yaml_extra))
    return {'pkg': pkg, 'profile': profile, 'pipeline': os.path.join(pkg, 'pipeline')}


def base_env(profile, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DSH_CHAT_FEED_', 'WECHAT_TOOL_'))}
    env['DSH_CHAT_FEED_LOCAL'] = profile
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    env.update(extra)
    return env


# ── 1. daily_prep.run ────────────────────────────────────────────────────────
RUNNER_DAILY = r'''
import json, os, sys
sys.path.insert(0, PIPE)
import daily_prep as dp

calls = []
def fake_run(*a, **k):
    calls.append(1)
    raise AssertionError('subprocess must not run when the work dir is unavailable')

def boom(*a, **k):
    raise OSError(13, 'synthetic mkdir failure')

dp.subprocess.run = fake_run
dp.os.makedirs = boom
res_fail = dp.run('1-合成步骤', [sys.executable, 'fake_script.py', 'SECRETKEY0123456789'],
                  critical=True)
print('RESULT:' + json.dumps({'fail': res_fail, 'calls': len(calls)}))
'''

RUNNER_KEY = r'''
import json, os, sys
sys.path.insert(0, PIPE)
import daily_prep as dp

class FakeProc:
    returncode = 0
    stdout = 'line one\nseen key SECRETKEY0123456789 here\n'
    stderr = ''

dp.subprocess.run = lambda *a, **k: FakeProc()
res = dp.run('2-合成步骤', [sys.executable, 'wx_decrypt3.py', 'SECRETKEY0123456789'],
             critical=False)
print('RESULT:' + json.dumps({'ok': res}))
'''


def case_workdir_unavailable():
    m = make_mini_pkg('daily-fail')
    runner = os.path.join(m['pipeline'], '_runner_daily.py')
    write(runner, 'PIPE = %r\n' % m['pipeline'] + RUNNER_DAILY)
    out = subprocess.run([sys.executable, '-B', runner], cwd=m['pipeline'],
                         env=base_env(m['profile']), capture_output=True, text=True,
                         encoding='utf-8', errors='replace')
    assert out.returncode == 0, out.stderr[-400:]
    payload = json.loads([l for l in out.stdout.splitlines() if l.startswith('RESULT:')][0][7:])
    assert payload['calls'] == 0, 'subprocess 被调用了 %d 次' % payload['calls']
    assert payload['fail']['status'] == 'WORKDIR-UNAVAILABLE', payload['fail']['status']
    assert payload['fail']['critical'] is True, 'critical 标记丢了'
    assert 'cwd 不回落到包内代码目录' in ' '.join(payload['fail']['notes'])
    assert 'SECRETKEY0123456789' not in out.stdout, 'key 出现在输出里'


def case_key_not_echoed():
    m = make_mini_pkg('daily-key')
    runner = os.path.join(m['pipeline'], '_runner_key.py')
    write(runner, 'PIPE = %r\n' % m['pipeline'] + RUNNER_KEY)
    out = subprocess.run([sys.executable, '-B', runner], cwd=m['pipeline'],
                         env=base_env(m['profile']), capture_output=True, text=True,
                         encoding='utf-8', errors='replace')
    assert out.returncode == 0, out.stderr[-400:]
    assert 'SECRETKEY0123456789' not in out.stdout, 'key 出现在步骤输出里'
    assert '<redacted-key>' in out.stdout, '尾部没有掩码'
    payload = json.loads([l for l in out.stdout.splitlines() if l.startswith('RESULT:')][0][7:])
    assert payload['ok']['status'] == 'ok', payload['ok']['status']
    # 标题只留解释器 + 脚本名
    titles = [l for l in out.stdout.splitlines() if l.startswith('=== [')]
    assert titles and titles[0].endswith('wx_decrypt3.py'), titles


# ── 2. 两个 wx 包装的初始化前缀 ──────────────────────────────────────────────
RUNNER_WX = r'''
import io, json, os, sys
wrapper = WRAPPER
src = io.open(wrapper, encoding='utf-8').read().splitlines()
cut = next(i for i, line in enumerate(src) if 'importlib.import_module(' in line)
prefix = '\n'.join(src[:cut])
ns = {'__name__': '__main__', '__file__': wrapper}
try:
    exec(compile(prefix, wrapper, 'exec'), ns)
except SystemExit as exc:
    print('EXIT:' + json.dumps({'code': int(exc.code or 0)}))
    raise SystemExit(0)
print('ENV:' + json.dumps({
    'data': os.environ.get('WECHAT_TOOL_DATA_DIR'),
    'output': os.environ.get('WECHAT_TOOL_OUTPUT_DIR'),
}))
'''


def run_wx_prefix(m, wrapper_name, profile=None, cwd=None, extra_env=None):
    runner = os.path.join(m['pipeline'], '_runner_wx_%s.py' % os.path.basename(wrapper_name))
    write(runner, 'WRAPPER = %r\n' % os.path.join(m['pipeline'], wrapper_name) + RUNNER_WX)
    env = base_env(profile or m['profile'], **(extra_env or {}))
    return subprocess.run([sys.executable, '-B', runner], cwd=cwd or m['pipeline'], env=env,
                          capture_output=True, text=True, encoding='utf-8', errors='replace')


def case_wx_private_state():
    for wrapper in ('wx_decrypt3.py', 'wx_decrypt_more.py'):
        m = make_mini_pkg('wx-' + wrapper.split('.')[0])
        decoy = os.path.join(m['pkg'], 'pipeline', 'leaked-state')
        out = run_wx_prefix(m, wrapper, extra_env={
            'WECHAT_TOOL_DATA_DIR': decoy,
            'WECHAT_TOOL_OUTPUT_DIR': os.path.join(decoy, 'output'),
        })
        assert out.returncode == 0, out.stderr[-400:]
        env = json.loads([l for l in out.stdout.splitlines() if l.startswith('ENV:')][0][4:])
        expect_data = os.path.join(m['profile'], 'tool-state', 'wechat')
        assert norm(env['data']) == norm(expect_data), '%s data=%r' % (wrapper, env['data'])
        assert norm(env['output']) == norm(os.path.join(expect_data, 'output')), env['output']
        assert not norm(env['data']).startswith(norm(m['pkg'])), '状态目录落在包里了'
        assert not os.path.isdir(expect_data), 'helper 不应创建状态目录'


def case_wx_profile_inside_package():
    m = make_mini_pkg('wx-inpkg')
    inside = os.path.join(m['pkg'], 'private-inside')
    os.makedirs(inside, exist_ok=True)
    out = run_wx_prefix(m, 'wx_decrypt3.py', profile=inside)
    assert out.returncode == 0, out.stderr[-300:]
    assert 'E_TOOL_STATE_PROFILE' in out.stderr, out.stderr[-300:]


def case_wx_state_escape():
    m = make_mini_pkg('wx-escape')
    outside = os.path.join(root, 'wx-escape', 'outside-state')
    os.makedirs(outside, exist_ok=True)
    link = os.path.join(m['profile'], 'tool-state')
    err = make_dir_link(outside, link)
    if err is not None:
        SKIPPED.append('tool-state 联接逃逸（本机建不出目录联接：%s）' % err.__class__.__name__)
        return
    out = run_wx_prefix(m, 'wx_decrypt3.py')
    assert out.returncode == 0, out.stderr[-300:]
    assert 'E_TOOL_STATE_ESCAPE' in out.stderr, out.stderr[-300:]


# ── 3. package.files 与 npm pack --dry-run ───────────────────────────────────
def build_pack_fixture():
    base = os.path.join(root, 'pack')
    real = json.load(io.open(os.path.join(PKG_ROOT, 'package.json'), encoding='utf-8'))
    pkg = {
        'name': 'dsh-chat-digest-files-probe',
        'version': '0.0.0',
        'files': real['files'],
    }
    write(os.path.join(base, 'package.json'), json.dumps(pkg, ensure_ascii=False, indent=2))
    write(os.path.join(base, 'README.md'), 'probe\n')
    write(os.path.join(base, 'LICENSE'), 'MIT\n')
    write(os.path.join(base, 'lib', 'public.py'), 'print(1)\n')
    write(os.path.join(base, 'pipeline', 'public_step.py'), 'print(2)\n')
    # 私有产物：都应该被排除
    write(os.path.join(base, 'pipeline', 'output', 'leak.txt'), 'x\n')
    write(os.path.join(base, 'pipeline', 'logs', 'run.log'), 'x\n')
    write(os.path.join(base, 'pipeline', 'account_keys.json'), '{}\n')
    write(os.path.join(base, 'pipeline', '.env'), 'A=1\n')
    write(os.path.join(base, 'pipeline', 'cache', 'tmp.bin'), 'x\n')
    write(os.path.join(base, 'pipeline', 'data', 'q.db'), 'x\n')
    return base


def case_npm_files_rules():
    node = shutil.which('node')
    cli = None
    if node:
        cand = os.path.join(os.path.dirname(node), 'node_modules', 'npm', 'bin', 'npm-cli.js')
        if os.path.isfile(cand):
            cli = cand
    if not node or not cli:
        SKIPPED.append('npm pack 文件清单（本机找不到 node 内置 npm-cli.js）')
        return
    base = build_pack_fixture()
    cfg_dir = os.path.join(root, 'npmcfg')
    os.makedirs(cfg_dir, exist_ok=True)
    user_rc = os.path.join(cfg_dir, 'user.npmrc')
    glob_rc = os.path.join(cfg_dir, 'global.npmrc')
    write(user_rc, '')
    write(glob_rc, '')
    cache = os.path.join(cfg_dir, 'cache')
    os.makedirs(cache, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.lower().startswith('npm_config_')}
    env.update({
        'npm_config_userconfig': user_rc,
        'npm_config_globalconfig': glob_rc,
        'npm_config_cache': cache,
        'npm_config_offline': 'true',
        'npm_config_ignore_scripts': 'true',
        'npm_config_audit': 'false',
        'npm_config_fund': 'false',
        'npm_config_update_notifier': 'false',
    })
    out = subprocess.run([node, cli, 'pack', '--dry-run', '--ignore-scripts', '--offline', '--json'],
                         cwd=base, env=env, capture_output=True, text=True,
                         encoding='utf-8', errors='replace', timeout=180)
    assert out.returncode == 0, (out.stdout[-400:], out.stderr[-400:])
    data = json.loads(out.stdout)
    files = [f['path'] for f in data[0]['files']]
    joined = '\n'.join(files)
    assert 'lib/public.py' in joined, files
    assert 'pipeline/public_step.py' in joined, files
    for bad in ('pipeline/output/leak.txt', 'pipeline/logs/run.log',
                'pipeline/account_keys.json', 'pipeline/.env',
                'pipeline/cache/tmp.bin', 'pipeline/data/q.db'):
        assert bad not in joined, '私有文件被打进包：' + bad
    assert not os.path.exists(os.path.join(base, 'dsh-chat-digest-files-probe-0.0.0.tgz')), 'dry-run 不该产出 tgz'


for name, fn in [
    ('work 目录不可用：不调 subprocess、返回失败、保留 critical', case_workdir_unavailable),
    ('已知解密 key 不进标题与尾部回显', case_key_not_echoed),
    ('两个 wx 包装把私有状态钉在 profile 内（外部 env 与公共 cwd 无效）', case_wx_private_state),
    ('profile 落在包内：拒绝', case_wx_profile_inside_package),
    ('tool-state 经联接逃出 profile：拒绝', case_wx_state_escape),
    ('package.files：公共源码保留、私有产物排除（npm pack dry-run）', case_npm_files_rules),
]:
    check(name, fn)

# 清理：只认创建时捕获的那个根
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
