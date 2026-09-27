# -*- coding: utf-8 -*-
"""boundary-checks.py — 拆分布局之后**每一条隐式前提**都变成边界判据；这里把四类做成可跑的断言。

为什么要有它（2026-09-27 用户："原来还不是一个文件夹的时候屁问题没有，现在出来一堆问题"）：
单根布局下，"脚本目录可写 / 路径常量是本机真值 / 提示词与数据同处 / 会话说 cwd 就是数据根"
这些前提**自动成立**；拆成"包（只读）＋私人夹（可写）＋运行时联接"之后，每条都成了必须显式满足的
边界，而旧代码没写任何断言 ⇒ 一个接一个在真机上炸。这个文件就是那批断言的落点。

用法：python test/boundary-checks.py    （只读；用安装副本做运行时断言）
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DSH_HOME = os.environ.get("DSH_HOME") or os.path.join(os.environ.get("USERPROFILE", "C:"), ".dsh")
INST = os.path.join(DSH_HOME, "profiles", "web", "node_modules", "dsh-chat-digest")
PRIV = os.path.join(DSH_HOME, "dsh-chat-digest")
results = []


def rec(cid, ok, detail=""):
    results.append((cid, bool(ok), detail))
    print("%-6s %-46s %s" % ("ok" if ok else "FAIL", cid, detail))


# ── B01：包内不许出现本机绝对路径 / 占位符字面量（脱敏把配置值换成字面量那类） ────────────
ABS = re.compile(r"""['"]r?[A-Za-z]:[\\/]""")
PLACE = re.compile(r"""r?['"](WX_ACCOUNT_DIR|OUT_DIR|WORK_DIR|WX_KEY_DIR|QQ_DATA_DIR|WX_MSG_GLOB)[\\/]""")
hits = []
for base in ("pipeline", os.path.join("agent", "tools")) if False else ("pipeline", "agent/tools"):
    d = os.path.join(ROOT, base)
    for dirpath, dirnames, filenames in os.walk(d):
        dirnames[:] = [x for x in dirnames if x != "__pycache__"]
        for n in filenames:
            if not n.endswith((".py", ".mjs")):
                continue
            p = os.path.join(dirpath, n)
            for i, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
                s = line.strip()
                if s.startswith("#"):
                    continue
                if ABS.search(s) or PLACE.search(s):
                    hits.append("%s:%d" % (os.path.relpath(p, ROOT), i))
rec("B01_no_literal_paths_in_package", not hits, ("命中 %d 处: %s" % (len(hits), hits[:5])) if hits else "0 处")


# ── B02：管线每步的 cwd 必须是可写私人根；裸脚本名必须绝对化 ────────────────────────────
src = open(os.path.join(ROOT, "pipeline", "daily_prep.py"), encoding="utf-8").read()
ok = ("cwd=work" in src) and ("os.path.isabs(argv[1])" in src) and ("cwd=SCRIPTS" not in src)
rec("B02_steps_run_in_writable_cwd", ok,
    "cwd=SCRIPTS 已消失" if ok else "仍把 cwd 指向包内脚本目录")


# ── B03/B04：运行时断言（用安装副本，读真实私人根） ───────────────────────────────────
try:
    sys.path.insert(0, os.path.join(INST, "pipeline"))
    os.environ["DSH_CHAT_FEED_LOCAL"] = PRIV
    import pconf  # noqa: E402

    local = os.path.realpath(pconf.local_dir())
    outd = os.path.realpath(pconf.out_dir())
    scripts = os.path.realpath(pconf.scripts_dir())
    inside = outd == local or outd.startswith(local + os.sep)
    rec("B03_out_dir_inside_profile", inside, "out_dir=%s" % outd)
    rec("B04_scripts_outside_profile", not (scripts == local or scripts.startswith(local + os.sep)),
        "scripts_dir=%s" % scripts)
except Exception as e:  # noqa: BLE001
    rec("B03_out_dir_inside_profile", False, "无法解析 pconf: %s" % e)
    rec("B04_scripts_outside_profile", False, "同上")


# ── B05：私人夹顶层白名单 + output/ 之外不许出现脚本（历史上攒了 215 个） ────────────────
ALLOW = {"archive", "docs", "inbox", "knowledge", "output", "workspace",
         "prompt.md", "round.md", "panel.json", "pipeline.json", "pipeline.yaml",
         "profile.md", "state.json", "state.json.bak", "personal-tokens.txt"}
extra = []
if os.path.isdir(PRIV):
    for n in os.listdir(PRIV):
        if n in ALLOW or n.startswith("."):
            continue
        extra.append(n)
rec("B05_private_root_whitelist", not extra, ("多余 %d 项: %s" % (len(extra), extra[:6])) if extra else "0 项")

stray = []
if os.path.isdir(PRIV):
    for dirpath, dirnames, filenames in os.walk(PRIV):
        dirnames[:] = [x for x in dirnames if x != "__pycache__"]
        rel = os.path.relpath(dirpath, PRIV)
        if rel.split(os.sep)[0] == "output":
            continue
        for n in filenames:
            if n.endswith((".py", ".mjs", ".js", ".ps1")):
                stray.append(os.path.join(rel, n))
rec("B06_no_scripts_outside_output", not stray, ("%d 个: %s" % (len(stray), stray[:5])) if stray else "0 个")

fails = [r for r in results if not r[1]]
print("\n%d/%d 通过 ｜ FAILS: %d" % (len(results) - len(fails), len(results), len(fails)))
sys.exit(1 if fails else 0)
