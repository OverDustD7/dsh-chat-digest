# -*- coding: utf-8 -*-
"""audit_refs.py — 找出"文档里写了、磁盘上不存在"的一切引用（精确到行），供逐个修。

用户 2026-09-14："文档里存在而实际不存在的东西还有哪些自己修，自己查错自己补。"
（已有先例：`fetch_page.mjs` 被多份文档引用却根本不存在；某个院系站点少了 `www.` 导致源失效。
 这类"文档承诺 > 现实"的缺口会让人（和主 agent）照着不存在的路走，必须清掉。）

范围：**权威/操作类文档**（排掉 archive 与叙事型 debug_*，那里出现历史一次性脚本是正常的）：
  · agent\\docs\**\*.md（去 archive、去 debug_*）
  · chat-feed\\*.md、chat-feed\\tools\\*.md
  · chat-feed\\tools\\host-v34.body.txt（主 agent 的 prompt）
存在性判定：**全仓文件名索引**（只比 basename，能容忍 `tools\\` / `scripts\\` 前缀差异）。
产出：output\\window\\_refs_audit.md（完整明细）＋ 控制台 ASCII 摘要。
"""
import io
import os
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # agent 根
CI = ROOT
CF = os.path.join(ROOT, "chat-feed")
SKIP_DIRS = ("node_modules", ".git", "venv", ".venv", "__pycache__", "archive", "_extracted")
EXTS = (".py", ".mjs", ".ps1")          # 只查"项目自己该有的脚本"（.json/.db/.xlsx 多是外部或数据，噪声大）
PREFIX = ("scripts", "tools", "lib", "docs", "src", "backend", "web")   # 引用需带这些目录前缀才算"文件路径"


def walk_sources():
    src = []
    for base, dirs, files in os.walk(os.path.join(CI, "docs")):
        dirs[:] = [d for d in dirs if d not in ("archive",)]
        for f in files:
            if f.endswith(".md") and not f.startswith("debug_"):
                src.append(os.path.join(base, f))
    for base, dirs, files in os.walk(CF):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".md") or f == "host-v34.body.txt":
                src.append(os.path.join(base, f))
    return src


INDEX = set()
for base, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for f in files:
        INDEX.add(f)

PAT = re.compile(r"([A-Za-z0-9_\u4e00-\u9fff\\/\.\-]{2,80}?(?:py|mjs|ps1))\b")

# 只关心"像文件/脚本名"的：含扩展名且不是纯网址
miss = defaultdict(list)
total = 0
for p in walk_sources():
    try:
        txt = io.open(p, encoding="utf-8", errors="replace").read()
    except Exception:
        continue
    for i, line in enumerate(txt.split("\n"), 1):
        if "http://" in line or "https://" in line:
            line2 = re.sub(r"https?://\S+", " ", line)
        else:
            line2 = line
        for m in PAT.finditer(line2):
            raw = m.group(1)
            name = raw.replace("\\", "/").split("/")[-1]
            if not name or name.startswith(".") or len(name) < 5:
                continue
            # 必须带目录前缀（scripts/x.py、tools/x.py…）或明确写成 <目录>\<文件>
            if not any(("/" + pre + "/") in raw.replace("\\", "/") or raw.replace("\\", "/").startswith(pre + "/")
                       for pre in PREFIX):
                continue
            if name.startswith("_") and name.endswith(".md"):      # <date>_timeline.md 这类后缀模板
                continue
            total += 1
            if name not in INDEX:
                miss[name].append((os.path.relpath(p, ROOT), i))

lines = ["# 引用审计：文档里写了、磁盘上不存在", "",
         "扫描源 %d 个 ｜ 引用 %d 处 ｜ **缺失 %d 个不同文件名 / %d 处引用**"
         % (len(walk_sources()), total, len(miss), sum(len(v) for v in miss.values())), ""]
for name in sorted(miss, key=lambda n: -len(miss[n])):
    lines.append("## %s（%d 处）" % (name, len(miss[name])))
    for f, ln in miss[name][:8]:
        lines.append("  - %s:%d" % (f.replace("\\", "/"), ln))
    lines.append("")
io.open(os.path.join(CI, "output", "window", "_refs_audit.md"), "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")

print("refs=%d  missing_names=%d  missing_refs=%d" % (total, len(miss), sum(len(v) for v in miss.values())))
for name in sorted(miss, key=lambda n: -len(miss[n]))[:40]:
    ascii_name = "".join(c if ord(c) < 128 else "?" for c in name)
    where = ";".join("%s:%d" % (f.replace("\\", "/").split("/")[-1], ln) for f, ln in miss[name][:2])
    print("  %-34s x%-2d  <- %s" % (ascii_name, len(miss[name]), where))
