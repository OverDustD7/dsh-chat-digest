# -*- coding: utf-8 -*-
"""find_msgs.py — 在当天产物里按关键词找原始消息（只读）。

用法: python tools\\find_msgs.py 2026-09-13 "算力券|限流|TPM" [最多条数] [每条字符数]
      python tools\\find_msgs.py 2026-09-12,2026-09-13 "算力券" 40
"""
import datetime as dt
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = dt.timezone(dt.timedelta(hours=8))

dates = (sys.argv[1] if len(sys.argv) > 1 else "").split(",")
pat = re.compile(sys.argv[2] if len(sys.argv) > 2 else ".")
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 60
width = int(sys.argv[4]) if len(sys.argv) > 4 else 500

shown = 0
for date in dates:
    p = os.path.join(HERE, "output", "days", "%s.jsonl" % date.strip())
    if not os.path.exists(p):
        print("（缺 %s）" % date)
        continue
    hits = 0
    for line in io.open(p, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        j = json.loads(line)
        blob = (j.get("text") or "") + " " + (j.get("raw") or "")
        # 也匹配会话名，便于"整群捞出"（如 find_msgs.py 2026-09-13 "AI创新大赛"）
        if not (pat.search(blob) or pat.search(j.get("chat_name") or "") or pat.search(str(j.get("chat") or ""))):
            continue
        hits += 1
        if shown >= limit:
            continue
        shown += 1
        ts = int(j.get("ts") or 0)
        hm = dt.datetime.fromtimestamp(ts, TZ).strftime("%m-%d %H:%M:%S") if ts else "?"
        txt = re.sub(r"\s+", " ", j.get("text") or "")
        if not txt.strip():
            txt = re.sub(r"\s+", " ", j.get("raw") or "")
        print("[%s] %-6s %-22s %-14s %s" % (hm, j.get("src"), (j.get("chat_name") or "")[:20],
                                            (j.get("sender_name") or j.get("sender") or "")[:12],
                                            txt[:width]))
    print("== %s 命中 %d 条（本脚本已打印 %d 条）==" % (date, hits, shown))
