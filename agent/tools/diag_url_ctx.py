# -*- coding: utf-8 -*-
"""diag_url_ctx.py — 打印某个链接残片在当天产物里的原始上下文（只读）。"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEEDLE = sys.argv[1] if len(sys.argv) > 1 else "http://mmbiz.qpi"
DAY = sys.argv[2] if len(sys.argv) > 2 else "2026-09-12"

p = os.path.join(HERE, "output", "days", "%s.jsonl" % DAY)
shown = 0
for line in io.open(p, encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line or NEEDLE not in line:
        continue
    j = json.loads(line)
    for fld in ("text", "raw"):
        b = j.get(fld) or ""
        i = b.find(NEEDLE)
        if i < 0:
            continue
        shown += 1
        seg = b[i:i + 90]
        print("--- row src=%s chat=%s ts=%s field=%s len=%d at=%d"
              % (j.get("src"), j.get("chat"), j.get("ts"), fld, len(b), i))
        print("    " + repr(seg))
    if shown >= 6:
        break
print("shown:", shown)
