# -*- coding: utf-8 -*-
"""管线读「个人信息」的唯一入口。

**这个包里不许再写死任何群名 / 路径 / 账号** —— 一律从这里取。个人信息放在
`<localDir>/pipeline.yaml`；`localDir` 的解析顺序与插件一致：
`$DSH_CHAT_FEED_LOCAL` → `$DSH_HOME/dsh-chat-digest`。

别人用 `pipeline/pipeline.example.yaml` 复制一份填自己的值即可；缺键时
`req()` 会打印「缺哪个键、去哪个文件填」并以退出码 2 结束。

用法：
    from pconf import C
    C.get("wx_account_dir")                  # 取不到就是空串
    C.req("wx_account_dir", "微信账号目录")   # 缺了就报错退出
    C.groups                                 # 群名列表
"""
import io
import json
import os
import sys

_ENV = "DSH_CHAT_FEED_LOCAL"
#: 宿主 Node 半在**包内 Python 模式**下写进来的选择桥（只在这一进程族里用，不落盘）：
#: {"schemaVersion":1,"root":"<pkg>/runtime/<platform>-<arch>","python":"<该目录下的解释器>"}
_ENV_BUNDLED = "DSH_CHAT_FEED_BUNDLED_RUNTIME"
EXTERNAL_TOOL_UNAVAILABLE = 78


def local_dir():
    """与宿主一致：显式目录优先，否则用 DSH_HOME 下的稳定私人目录。"""
    d = os.environ.get(_ENV) or ""
    home = os.environ.get("DSH_HOME") or (
        os.path.join(os.environ["USERPROFILE"], ".dsh")
        if os.environ.get("USERPROFILE") else "")
    appdata = os.environ.get("LOCALAPPDATA") or (
        os.path.join(os.environ["USERPROFILE"], "AppData", "Local")
        if os.environ.get("USERPROFILE") else "")
    selected = d or (os.path.join(home, "dsh-chat-digest") if home else "") or (
        os.path.join(appdata, "dsh-chat-digest") if appdata else "")
    if not selected or not os.path.isabs(selected):
        raise SystemExit("[pconf] 私人 profile 需要绝对路径：请设置 DSH_CHAT_FEED_LOCAL 或 DSH_HOME")
    return selected


def profile():
    """**个人 profile 目录**：提示词 / 私人值 / 知识库 / 每日产物 全住这里（＝ local_dir 同一个目录）。

    与"通用代码"的分界：`lib/ pipeline/ tools/ docs/` 是通用的、随包发布；
    profile 目录里的一切都是**某个人的**，重装插件也不该丢 —— 所以它能用 config.localDir /
    `$DSH_CHAT_FEED_LOCAL` 指到包外面（宿主挂载时会把解析到的值导出到这个环境变量）。
    """
    return os.path.realpath(local_dir())


def p(*parts):
    """拼 profile 下的路径：`p("output", "days")` → `<profile>/output/days`。

    工具的规矩：**通用代码用包内相对路径，个人数据一律走这里** ——
    不要再出现 `HERE + "output"` 这种把个人数据塞进代码目录的写法。
    """
    return os.path.join(profile(), *parts)


#: 第三方微信工具的状态目录命名空间（相对 profile）。
_TOOL_STATE_PARTS = ("tool-state", "wechat")


def private_tool_state():
    """把第三方微信工具的**私有**状态目录钉在个人 profile 内，并写进本进程环境。

    为什么要有它：供应商的 `app_paths.get_data_dir()` 读 `WECHAT_TOOL_DATA_DIR`，没设就退到
    `Path.cwd()`；`get_output_dir()` 读 `WECHAT_TOOL_OUTPUT_DIR`，没设就跟着 data 走 —— 日志与
    `account_keys.json` 都落在 output 下面。进程 cwd 一旦在包内代码目录（独立调用脚本、
    或某些失败路径），这些东西就会写进包里。

    这里只做四件事：profile 不许在包内；两个目标 realpath 后必须在 profile 内、且不在包内
    （已存在的联接逃逸会在这里被拒）；只改**本进程**环境变量；**不创建目录**（第三方真要写时才建）。
    外部的同名环境变量一律覆盖，不让残留值把日志/密钥带回公共目录。
    """
    prof = _norm(profile(), 'profile')
    pkg = _norm(pkg_dir(), 'package')
    if _under(pkg, prof):
        sys.stderr.write('[pconf][E_TOOL_STATE_PROFILE] 私人 profile 落在插件包内，拒绝设置工具状态目录\n')
        raise SystemExit(2)
    base = os.path.join(prof, *_TOOL_STATE_PARTS)
    targets = (('WECHAT_TOOL_DATA_DIR', base),
               ('WECHAT_TOOL_OUTPUT_DIR', os.path.join(base, 'output')))
    for name, target in targets:
        try:
            real = os.path.normcase(os.path.realpath(target))
        except (OSError, ValueError):
            sys.stderr.write('[pconf][E_TOOL_STATE_ESCAPE] 工具状态目录无法规范化\n')
            raise SystemExit(2)
        if not _under(prof, real) or _under(pkg, real):
            sys.stderr.write('[pconf][E_TOOL_STATE_ESCAPE] 工具状态目录不在私人 profile 内\n')
            raise SystemExit(2)
        os.environ[name] = real
    return base


def _strip(v):
    v = v.split("#")[0].strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1]
    return v


def _load(path):
    """读 yaml。装了 pyyaml 就用它；没有则退化成极简解析（key: value、- 列表项、# 注释）。"""
    if not os.path.isfile(path):
        return {}
    try:
        import yaml  # noqa
        with io.open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        pass
    out = {}
    key = None
    with io.open(path, encoding="utf-8") as f:
        for raw in f:
            st = raw.strip()
            if not st or st.startswith("#"):
                continue
            if st.startswith("- ") and key:
                out.setdefault(key, []).append(_strip(st[2:]))
                continue
            if ":" in st:
                k, v = st.split(":", 1)
                k = _strip(k)
                v = _strip(v)
                if v:
                    out[k] = v
                    key = None
                else:
                    key = k
                    out.setdefault(k, [])
    return out


class _Conf(object):
    def __init__(self):
        self.path = os.path.join(local_dir(), "pipeline.yaml")
        self.d = _load(self.path) or {}

    def get(self, key, default=""):
        v = self.d.get(key, default)
        return default if v is None else v

    def req(self, key, what=""):
        v = self.get(key, "")
        if not v:
            tip = ("（" + what + "）") if what else ""
            sys.stderr.write("[pconf] 缺 %s%s —— 请在 %s 里填好；模板见 pipeline/pipeline.example.yaml\n"
                             % (key, tip, self.path))
            raise SystemExit(2)
        return v

    @property
    def groups(self):
        g = self.d.get("groups") or []
        if isinstance(g, list):
            return [str(x) for x in g if str(x).strip()]
        return [str(g)]


C = _Conf()


# ── 包内路径解析（A35，2026-09-27）：**插件目录之外一律不碰** ──────────────────
#   为什么要有这几条：管线脚本原来假设"工作区＝<插件目录>"、脚本在 `<工作区>/scripts`、
#   解释器在 `<插件目录>/../venv`、包外工具在 `<插件目录>/../WeChatDataAnalysis` ——
#   换成 npm 安装后这些全都指到了包外（甚至 node_modules），也就是"还在依赖本机文件"。
def pkg_dir():
    """插件目录（<pkg>）：本文件住在 <pkg>/pipeline/ 下。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def agent_root():
    """数据工作区＝私人 profile 的物理路径；写入不经包内 junction。"""
    return profile()


def scripts_dir():
    """取数脚本自己所在目录＝<插件目录>/pipeline。"""
    return os.path.join(pkg_dir(), 'pipeline')


def work_dir():
    """管线读写的工作区根：**缺省＝profile()（私人文件夹）**。
    `pipeline.yaml` 的 `work_dir` 只在把产物放到别处时才填。"""
    v = (_Conf_get('work_dir') or '').strip()
    return v if v else profile()


class _BridgeError(Exception):
    """桥载荷校验失败：带一个稳定错误码，消息里不带原始路径。"""

    def __init__(self, code, what):
        Exception.__init__(self, what)
        self.code = code
        self.what = what


def _norm(p, field):
    """规范路径 + 平台大小写规则；Windows 上大小写不敏感的比较靠它。

    NUL 字符与"规范化过程本身失败"（OSError / ValueError）都要归成有码的失败：
    直接让 realpath 抛出去会变成没有错误码的 traceback，还可能把原始路径写进回溯。
    """
    if '\x00' in p:
        raise _BridgeError('E_BUNDLED_FIELD', '%s 含 NUL 字符' % field)
    try:
        return os.path.normcase(os.path.realpath(p))
    except (OSError, ValueError):
        raise _BridgeError('E_BUNDLED_FIELD', '%s 无法规范化' % field)


def _under(root, target):
    """target 是否在 root 内（含相等）。跨盘时 relpath 抛 ValueError —— 一律当"不在"。"""
    try:
        rel = os.path.relpath(target, root)
    except ValueError:
        return False
    if rel == os.curdir:
        return True
    return not (rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel))


def _bundled_runtime():
    """内部桥的**共用**校验：返回 {'root': 真实root, 'python': 真实python} 或 None。

    `python_exe()` 与 `external_tool()` 都走这里 —— 只校验一次、口径只有一份，
    不再各自写一套宽松读取绕过校验。键不存在时返回 None，调用方走旧行为。
    """
    raw = os.environ.get(_ENV_BUNDLED)
    if raw is None:
        return None
    try:
        payload = _bundled_payload_strict(raw)
    except _BridgeError as exc:
        sys.stderr.write('[pconf][%s] %s —— 包内模式不回落到包外路径或私人配置\n'
                         % (exc.code, exc.what))
        raise SystemExit(2)
    return payload


def _bundled_payload_strict(raw):
    fail = _BridgeError

    if not raw.strip():
        raise fail('E_BUNDLED_EMPTY', 'DSH_CHAT_FEED_BUNDLED_RUNTIME 是空值')
    try:
        payload = json.loads(raw)
    except Exception:
        raise fail('E_BUNDLED_JSON', 'DSH_CHAT_FEED_BUNDLED_RUNTIME 不是合法 JSON')
    if not isinstance(payload, dict):
        raise fail('E_BUNDLED_SCHEMA', '载荷不是对象')
    # 注意 bool 是 int 的子类：True == 1，不能当合法的 schemaVersion
    version = payload.get('schemaVersion')
    if type(version) is not int or version != 1:
        raise fail('E_BUNDLED_SCHEMA', 'schemaVersion 不是整数 1')
    root = payload.get('root')
    py = payload.get('python')
    for name, value in (('root', root), ('python', py)):
        if not isinstance(value, str) or not value.strip():
            raise fail('E_BUNDLED_FIELD', '%s 必须是非空字符串' % name)
        if '\x00' in value:
            raise fail('E_BUNDLED_FIELD', '%s 含 NUL 字符' % name)
        if not os.path.isabs(value):
            raise fail('E_BUNDLED_FIELD', '%s 必须是绝对路径' % name)

    real_root = _norm(root, 'root')
    real_py = _norm(py, 'python')
    pkg = _norm(pkg_dir(), 'package')
    if not _under(pkg, real_root):
        raise fail('E_BUNDLED_ESCAPE', 'root 不在当前包内')
    if not _under(real_root, real_py):
        raise fail('E_BUNDLED_ESCAPE', 'python 不在 root 内')
    if not os.path.isdir(real_root):
        raise fail('E_BUNDLED_MISSING', 'runtime 目录不存在')
    if not os.path.exists(real_py):
        raise fail('E_BUNDLED_MISSING', '声明的解释器不存在')
    if not os.path.isfile(real_py):
        raise fail('E_BUNDLED_TYPE', '声明的解释器不是普通文件')
    return {'root': real_root, 'python': real_py}


def python_exe():
    """用哪个解释器跑管线。

    包内 Python 模式（内部键存在）优先且**严格**：只认它声明的那个文件，坏了就退出（见
    `_bundled_runtime`）。该键不存在时维持原优先级：`pipeline.yaml:python` → 环境变量
    `DSH_CHAT_FEED_PY`（宿主把插件配置里的 `python` 导出到这里）→ 当前解释器；
    配的那个路径不存在就警告并退回当前解释器。"""
    info = _bundled_runtime()
    if info is not None:
        return info['python']
    v = (_Conf_get('python') or os.environ.get('DSH_CHAT_FEED_PY') or '').strip()
    if v and not os.path.isfile(v):
        sys.stderr.write('[pconf] 配的 python 不存在：%s —— 改用当前解释器 %s\n' % (v, sys.executable))
        v = ''
    return v if v else (sys.executable or 'python')


def ensure_utf8_stdio():
    """把**本进程**的 stdout/stderr 切到 UTF-8（幂等，失败不致命）。

    为什么需要：嵌入分发的 `._pth` 让解释器处于 isolated + ignore_environment，
    `PYTHONIOENCODING` / `PYTHONUTF8` 这类环境变量**不生效**，控制台是 GBK 时
    print 中文以外的字符（emoji）会直接 UnicodeEncodeError。直接在进程里 reconfigure
    才是这个分发形态下唯一可靠的写法。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _is_package_python(path):
    """解释器是不是包内自带的那一个。判据只看位置，不看环境桥在不在。

    为什么不能看桥：用户直接 `python daily_prep.py` 时没有桥（只有 Node 半挂载才写桥），
    但解释器仍是包内那一个 —— 那种情况下同样必须补开关，否则按 GBK 输出。
    """
    try:
        p = os.path.normcase(os.path.abspath(str(path)))
        pkg = os.path.normcase(os.path.abspath(pkg_dir()))
    except (OSError, ValueError):
        return False
    return p == pkg or p.startswith(pkg + os.sep)


def python_flags(python_path=None):
    """包内解释器要补的命令行开关；外部解释器返回空表（不改变它的行为）。

    只用 `-X utf8`：它是命令行开关，不受 `ignore_environment` 影响，也不会开 site、
    不改解释器二进制。**开关不进 `python_exe()` 的返回值** —— 那仍然是纯解释器路径。
    """
    exe = python_path if python_path else python_exe()
    return ["-X", "utf8"] if _is_package_python(exe) else []


def python_argv(argv, python_path=None):
    """给「解释器 + 脚本 …」形式的 argv 补上 `python_flags()`。

    只认 argv[0] 就是解释器、argv[1] 是 .py/.pyw 的情形；node 等非 Python 调用、
    已经自带开关的调用一律原样返回，给所有 argv 盲加 Python 开关是不允许的。
    """
    argv = list(argv)
    if len(argv) < 2 or str(argv[1]).startswith("-"):
        return argv
    exe = python_path if python_path else python_exe()
    try:
        same = (os.path.normcase(os.path.abspath(str(argv[0])))
                == os.path.normcase(os.path.abspath(str(exe))))
    except (OSError, ValueError):
        return argv
    if not same:
        return argv
    if not str(argv[1]).lower().endswith((".py", ".pyw")):
        return argv
    return [argv[0]] + python_flags(argv[0]) + argv[1:]


def _vendor_tool(root_real, parts):
    """包内模式的工具定位：只从 `<runtime root>/vendor/<parts>` 取，返回**现存**文件或目录。

    两种已知用法都要支持：目录（`WeChatDataAnalysis`）与文件（`nt_msg_db_util/3.export.py`），
    所以这里不预设类型，只要求"存在且是文件或目录"。任何越界、缺失、访问失败都抛有码错误，
    不回落私人 `external_dir`、包内 `vendor/` 或系统安装路径。
    """
    for part in parts:
        if not isinstance(part, str) or not part.strip():
            raise _BridgeError('E_VENDOR_PARTS', '工具名必须是非空字符串')
        if '\x00' in part:
            raise _BridgeError('E_VENDOR_PARTS', '工具名含 NUL 字符')
        text = part.replace('\\', '/')
        if text.startswith('/') or (len(text) >= 2 and text[1] == ':'):
            raise _BridgeError('E_VENDOR_PARTS', '工具名不许是绝对路径或带盘符')
        for segment in text.split('/'):
            if segment in ('', '.', '..'):
                raise _BridgeError('E_VENDOR_PARTS', '工具名含空段或点点段')
    target = os.path.join(root_real, 'vendor', *[p.replace('\\', os.sep) for p in parts])
    real = _norm(target, 'vendor target')
    if not _under(root_real, real):
        raise _BridgeError('E_VENDOR_ESCAPE', '工具路径逃出了当前 runtime')
    try:
        info = os.stat(real)
    except FileNotFoundError:
        raise _BridgeError('E_VENDOR_MISSING', 'runtime/vendor 里没有这个工具')
    except OSError:
        raise _BridgeError('E_VENDOR_UNREADABLE', 'runtime/vendor 里的工具无法访问')
    if not (os.path.isfile(real) or os.path.isdir(real)):
        raise _BridgeError('E_VENDOR_TYPE', 'runtime/vendor 里的工具既不是文件也不是目录')
    return real


def external_tool(*parts, required_file=False):
    """定位兼容工具路径；导入入口用 required_file 要求存在的文件。"""
    info = _bundled_runtime()
    if info is not None:
        try:
            target = _vendor_tool(info['root'], parts)
            if required_file and not os.path.isfile(target):
                raise _BridgeError('E_VENDOR_TYPE', '工具入口不是文件')
            return target
        except _BridgeError as exc:
            sys.stderr.write('[pconf][%s] %s —— 包内模式不回落到 external_dir 或包外路径\n'
                             % (exc.code, exc.what))
            raise SystemExit(2)
    configured = _Conf_get('external_dir')
    base = configured.strip() if isinstance(configured, str) else ''
    if not required_file:
        return os.path.join(base or os.path.join(pkg_dir(), 'vendor'), *parts)
    want = '/'.join(parts)
    tried = []
    try:
        if base and os.path.isabs(base) and '\x00' not in base:
            root = os.path.realpath(base)
            target = os.path.realpath(os.path.join(root, *parts))
            if (_under(root, target) and not _under(os.path.realpath(pkg_dir()), target)
                    and os.path.isfile(target)):
                return target
            tried.append(want)
            # ① 配置映射：external_tool_map 里显式给出这个工具的真实位置
            override = _tool_override(parts)
            if override:
                cand = os.path.realpath(override if os.path.isabs(override) else os.path.join(root, override))
                if (_under(root, cand) and not _under(os.path.realpath(pkg_dir()), cand)
                        and os.path.isfile(cand)):
                    sys.stderr.write('[pconf] 工具 %s 走 external_tool_map → %s\n'
                                     % (want, os.path.relpath(cand, root)))
                    return cand
                tried.append('external_tool_map')
            # ② 有限深度按文件名找同名文件（外部工具常放在自己的子目录里，例如 */scripts/那个）
            hits = _search_tool(root, parts)
            exact = [h for h in hits if os.path.normcase(h).endswith(os.path.normcase(os.sep + want.replace('/', os.sep)))]
            pick = exact[0] if exact else (hits[0] if len(hits) == 1 else '')
            if pick:
                sys.stderr.write('[pconf] 工具 %s 按文件名在 external_dir 内找到 → %s\n'
                                 % (want, os.path.relpath(pick, root)))
                return pick
            if len(hits) > 1:
                tried.append('%s（同名 %d 个，无法确定）' % (want, len(hits)))
    except (OSError, ValueError):
        pass
    sys.stderr.write('[pconf][E_EXTERNAL_TOOL_REQUIRED] 在私人 pipeline.yaml 的 external_dir 中'
                     '配置包外工具文件 %s（已试：%s）；也可用 external_tool_map 指到真实位置\n'
                     % (want, ', '.join(tried) or want))
    raise SystemExit(EXTERNAL_TOOL_UNAVAILABLE)


def _tool_override(parts):
    """external_tool_map：键为 `工具/文件` 或只写文件名，值为相对/绝对路径。"""
    mapping = _Conf_get('external_tool_map')
    if not isinstance(mapping, dict):
        return ''
    for key in ('/'.join(parts), parts[-1]):
        v = mapping.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ''


def _search_tool(base, parts, max_depth=3):
    """在 external_dir 下有限深度内找同名文件；返回绝对路径列表。"""
    name = parts[-1]
    hits = []
    root = os.path.realpath(base)
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == '.' else rel.count(os.sep) + 1
        if depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if d not in ('.git', '__pycache__')]
        if name in filenames:
            hits.append(os.path.join(dirpath, name))
    return hits


def _Conf_get(key):
    return C.get(key)


def out_dir():
    """产物根：**缺省＝<私人文件夹>/output**（`pipeline.yaml` 的 `output_dir` 只在放别处时才填）。"""
    v = (_Conf_get('output_dir') or '').strip()
    return v if v else os.path.join(profile(), 'output')
