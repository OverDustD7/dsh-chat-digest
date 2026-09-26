# -*- coding: utf-8 -*-
r"""imgmap.py —— 把一篇已抓文章的 md 里 [图片] 占位映射到 article_imgs 落盘的 imgNN 文件。
用法: python tools\imgmap.py <article.md> [关键词]
"""
import io
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
path = sys.argv[1]
kw = sys.argv[2] if len(sys.argv) > 2 else ""
lines = io.open(path, encoding="utf-8").read().split("\n")
idx = 0
for i, ln in enumerate(lines):
    for _ in re.finditer(r"\[图片\]", ln):
        idx += 1
        tags = []
        if kw and kw in ln:
            tags.append("KW-SAME-LINE")
        print("L%-4d img%02d  %s %s" % (i + 1, idx, ln.strip()[:40], " ".join(tags)))
hit = False
for i, ln in enumerate(lines):
    if kw and kw in ln:
        hit = True
        print("--- 关键词命中 line %d: %s" % (i + 1, ln.strip()[:60]))
if kw and not hit:
    print("--- 关键词未命中:", kw)
