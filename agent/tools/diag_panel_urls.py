# -*- coding: utf-8 -*-
"""diag_panel_urls.py — 列出面板条目里出现的链接（只读，检查是否有被截断的垃圾链接）。"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
STATE = os.path.join(os.environ.get("TEMP", "."), "cfstate.json")
URL_RE = re.compile(r"https?://[^\s\)\]\"<>]+")
items = json.load(io.open(STATE, encoding="utf-8-sig"))["items"]
n = 0
for it in items:
    for u in URL_RE.findall(it.get("text") or ""):
        n += 1
        print("%-14s %-9s %s" % (it.get("id"), it.get("kind"), u[:110]))
print("total urls in panel items:", n)
