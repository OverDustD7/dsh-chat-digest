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
