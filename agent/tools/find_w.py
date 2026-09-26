# -*- coding: utf-8 -*-
"""find_w.py — 在最近被写过的会话里找字面 "W" 的异常堆积（只读）。

用法: python tools\\find_w.py [最近 N 分钟，默认 60]
"""
import datetime as dt
import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DSH = os.path.join(os.environ.get("USERPROFILE", ""), ".dsh", "sessions")
TZ = dt.timezone(dt.timedelta(hours=8))
MINS = float(sys.argv[1]) if len(sys.argv) > 1 else 60
try:
    from compression import zstd as _zstd
except Exception:  # noqa: BLE001
    _zstd = None

# 连续 3 个以上 W；或一行里独立 W 出现 6 次以上
PAT1 = re.compile(r"W{3,}")
PAT2 = re.compile(r"(?:\bW\b[^\w]{0,4}){6,}")

cut = dt.datetime.now().timestamp() - MINS * 60
files = [p for p in glob.glob(os.path.join(DSH, "*", "*", "session.v3.jsonl.zstd"))
         if os.path.getmtime(p) >= cut]
print("扫最近 %.0f 分钟内的 %d 个会话（按改动时间）" % (MINS, len(files)))
hits = 0
for p in sorted(files, key=os.path.getmtime):
    sid = os.path.basename(os.path.dirname(p))
    when = dt.datetime.fromtimestamp(os.path.getmtime(p), TZ).strftime("%H:%M:%S")
    try:
        data = _zstd.decompress(io.open(p, "rb").read()).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print("!! %s %s" % (sid[:12], e))
        continue
    n1, n2 = len(PAT1.findall(data)), len(PAT2.findall(data))
    if n1 or n2:
        hits += 1
        print("-" * 110)
        print("会话 %s (%s) ｜ W{3,} ×%d ｜ 独立W连发 ×%d ｜ %d 字节" % (sid[:12], when, n1, n2, len(data)))
        for m in list(PAT1.finditer(data))[:3]:
            print("    …%s…" % data[max(0, m.start() - 80):m.start() + 80].replace("\n", " ⏎ ")[:200])
        for m in list(PAT2.finditer(data))[:2]:
            print("    ~…%s…" % data[max(0, m.start() - 80):m.start() + 120].replace("\n", " ⏎ ")[:220])
print("命中会话：%d" % hits)
