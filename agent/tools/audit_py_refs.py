# -*- coding: utf-8 -*-
"""audit_py_refs.py — 审计"文档/编排里引用的 .py 是否真的存在"。

用户 2026-09-13 说"好像缺了什么 py" → 与其猜，不如把**引用点**全查一遍：
  ① daily_prep.py 里 run(...) 调用的脚本名
  ② WAKE_TEXT（chat-feed\\tools\\host-v34.body.txt）里提到的 .py
  ③ 任务书 / 手册 / INDEX 里提到的 .py
只读；输出写成 UTF-8 文件，避免控制台 GBK。
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # agent 根
CI = ROOT
CF = os.path.join(ROOT, "chat-feed")

import glob

SRC = []
# 代码/编排/prompt：这些地方引用缺失 = 真问题
SRC += [(os.path.join(CI, "scripts", "daily_prep.py"), r"[\w\\/\.]+\.py"),
        (os.path.join(CF, "tools", "host-v34.body.txt"), r"[\w\\/\.]+\.py")]
# 文档：全量扫（含 RESTART.md / STATUS.md / DEV_NOTES.md …）
for pat in (os.path.join(CI, "docs", "**", "*.md"), os.path.join(CF, "*.md"),
            os.path.join(CF, "tools", "*.md")):
    for p in glob.glob(pat, recursive=True):
        if os.sep + "archive" + os.sep in p:
            continue
        SRC.append((p, r"[\w\\/\.]+\.py"))
# 建**全仓文件名索引**（跳过大目录），只按 basename 判断"这个 .py 在不在"
SKIP = ("node_modules", ".git", "venv", ".venv", "__pycache__", "output", "archive")
INDEX = set()
for base, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in SKIP]
    for fn in files:
        if fn.endswith(".py"):
            INDEX.add(fn)
lines = []
miss = []
for path, pat in SRC:
    if not os.path.exists(path):
        lines.append("!! 审计源不存在: %s" % path)
        continue
    txt = io.open(path, encoding="utf-8", errors="replace").read()
    names = sorted(set(re.findall(pat, txt)))
    lines.append("\n### %s（%d 个引用）" % (os.path.relpath(path, ROOT), len(names)))
    for n in names:
        base = os.path.basename(n.replace("\\", "/"))
        if base in INDEX:
            lines.append("  ok   %s" % base)
        else:
            lines.append("  MISS %-28s (引用为 %s)" % (base, n))
            miss.append((os.path.relpath(path, ROOT), base))
lines.append("\n全仓 .py 文件数（跳过 %s）：%d" % (", ".join(SKIP), len(INDEX)))

out = os.path.join(CI, "output", "window", "_pyref_audit.txt")
io.open(out, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
print("审计源 %d 个 ｜ 缺失 %d 处 ｜ 明细 -> %s" % (len(SRC), len(miss), out))
for f, b in miss:
    print("   MISS %s   (from %s)" % (b, f))
