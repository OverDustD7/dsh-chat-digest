# -*- coding: utf-8 -*-
"""diag_url_escape.py — 量化链接正则被 JSON 转义符 `\\/` 截断的规模（只读）。"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL_RE = re.compile(r"https?://[^\s\"'<>\\）)】]+")
SKIP = ("tianquan.gtimg.cn", "zb.vip.qq.com")

p = os.path.join(HERE, "output", "window", "all_urls.jsonl")
urls = {json.loads(l)["url"] for l in io.open(p, encoding="utf-8") if l.strip()}
pref = sorted(u for u in urls if any(v != u and v.startswith(u) for v in urls))

dayp = os.path.join(HERE, "output", "days", "2026-09-12.jsonl")
esc_hits = 0
field_hits = {"text": 0, "raw": 0}
for line in io.open(dayp, encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line:
        continue
    j = json.loads(line)
    for fld in ("text", "raw"):
        b = j.get(fld) or ""
        if "\\/" in b and "http" in b:
            field_hits[fld] += 1
        if "\\/" in b:
            esc_hits += 1
print("unique urls in all_urls.jsonl:", len(urls))
print("prefix-truncated (garbage)      :", len(pref))
for u in pref[:12]:
    print("    -", u)
print("day rows containing literal backslash-slash:", esc_hits, field_hits)
