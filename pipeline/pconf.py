# -*- coding: utf-8 -*-
"""管线读「个人信息」的唯一入口。

**这个包里不许再写死任何群名 / 路径 / 账号** —— 一律从这里取。个人信息放在
`<localDir>/pipeline.yaml`；`localDir` 的解析顺序与插件一致：
`$DSH_CHAT_FEED_LOCAL` → 包旁的 `local/`。

别人用 `pipeline/pipeline.example.yaml` 复制一份填自己的值即可；缺键时
`req()` 会打印「缺哪个键、去哪个文件填」并以退出码 2 结束。

用法：
    from pconf import C
    C.get("wx_account_dir")                  # 取不到就是空串
    C.req("wx_account_dir", "微信账号目录")   # 缺了就报错退出
    C.groups                                 # 群名列表
"""
import io
import os
import sys

_ENV = "DSH_CHAT_FEED_LOCAL"


def local_dir():
    """和插件加载器同一套解析顺序。"""
    d = os.environ.get(_ENV) or ""
    if d and os.path.isdir(d):
        return d
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(os.path.dirname(here), "local"), os.path.join(here, "local")):
        if os.path.isdir(cand):
            return cand
    return d or os.path.join(os.path.dirname(here), "local")


def profile():
    """**个人 profile 目录**：提示词 / 私人值 / 知识库 / 每日产物 全住这里（＝ local_dir 同一个目录）。

    与"通用代码"的分界：`lib/ pipeline/ tools/ docs/` 是通用的、随包发布；
    profile 目录里的一切都是**某个人的**，重装插件也不该丢 —— 所以它能用 config.localDir /
    `$DSH_CHAT_FEED_LOCAL` 指到包外面（宿主挂载时会把解析到的值导出到这个环境变量）。
    """
    return local_dir()


def p(*parts):
    """拼 profile 下的路径：`p("output", "days")` → `<profile>/output/days`。

    工具的规矩：**通用代码用包内相对路径，个人数据一律走这里** ——
    不要再出现 `HERE + "output"` 这种把个人数据塞进代码目录的写法。
    """
    return os.path.join(profile(), *parts)


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
    """主 agent 的工作区＝<插件目录>/agent（说明书、工具箱、产物与个人数据都在这一棵树里）。
    插件目录其余部分只读；插件目录之外不写任何东西。"""
    return os.path.join(pkg_dir(), 'agent')


def scripts_dir():
    """取数脚本自己所在目录＝<插件目录>/pipeline。"""
    return os.path.join(pkg_dir(), 'pipeline')


def work_dir():
    """管线读写的工作区根：**缺省＝agent_root()**（不填就是"全在插件目录里"）。
    `pipeline.yaml` 的 `work_dir` 只在把产物放到别处时才填。"""
    v = (_Conf_get('work_dir') or '').strip()
    return v if v else agent_root()


def python_exe():
    """用哪个解释器跑管线：`pipeline.yaml:python` → 环境变量 `DSH_CHAT_FEED_PY`
    （宿主会把插件配置里的 `python` 导出到这里）→ 当前解释器。缺省不依赖任何固定路径。"""
    v = (_Conf_get('python') or os.environ.get('DSH_CHAT_FEED_PY') or '').strip()
    return v if v else (sys.executable or 'python')


def external_tool(*parts):
    """包外工具（WeChatDataAnalysis / nt_msg_db_util 之类）的定位：
    **缺省不依赖包外** —— 把它们放进插件目录就什么都不用配；要用包外那份，
    在 `pipeline.yaml` 里给 `external_dir`。"""
    base = (_Conf_get('external_dir') or '').strip()
    if not base:
        sys.stderr.write('[pconf] 这一步需要包外工具 %s：把它放进插件目录，'
                         '或在 pipeline.yaml 里给 external_dir\n' % os.path.join(*parts))
        return os.path.join(pkg_dir(), 'vendor', *parts)
    return os.path.join(base, *parts)


def _Conf_get(key):
    return C.get(key)


def out_dir():
    """产物根：**缺省＝<插件目录>/agent/output**（`pipeline.yaml` 的 `output_dir` 只在放别处时才填）。"""
    v = (_Conf_get('output_dir') or '').strip()
    return v if v else os.path.join(agent_root(), 'output')
