# -*- coding: utf-8 -*-
"""scan_repeat.py — 在所有会话记录里找"同一个字符连续重复"的退化输出（只读）。

用法: python tools\\scan_repeat.py [最少连续个数，默认 30] [只扫这个工作区名]
例:   python tools\\scan_repeat.py 30 <关键词>
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
MINRUN = int(sys.argv[1]) if len(sys.argv) > 1 else 30
FILTER = sys.argv[2] if len(sys.argv) > 2 else ""

try:
    from compression import zstd as _zstd
except Exception:  # noqa: BLE001
    _zstd = None

RUN = re.compile(r"(.)\1{%d,}" % (MINRUN - 1), re.S)


def load(path):
    raw = io.open(path, "rb").read()
    data = _zstd.decompress(raw)
    out = []
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                pass
    return out


def walk_strings(o, path=""):
    if isinstance(o, str):
        yield path, o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from walk_strings(v, path + "." + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk_strings(v, path + "[%d]" % i)


files = sorted(glob.glob(os.path.join(DSH, "*", "*", "session.v3.jsonl.zstd")),
               key=os.path.getmtime)
hits = []
for p in files:
    if FILTER and FILTER not in p:
        continue
    mtime = dt.datetime.fromtimestamp(os.path.getmtime(p), TZ).strftime("%m-%d %H:%M:%S")
    try:
        evs = load(p)
    except Exception as e:  # noqa: BLE001
        print("!! 读不了 %s: %s" % (p, e))
        continue
    for i, ev in enumerate(evs):
        for path, s in walk_strings(ev):
            if len(s) < MINRUN:
                continue
            m = RUN.search(s)
            if not m:
                continue
            ch = m.group(1)
            run = len(m.group(0))
            hits.append((run, mtime, os.path.basename(os.path.dirname(p)), ev.get("type"),
                         path, ch, len(s), s[max(0, m.start() - 40):m.start() + 40]))
hits.sort(reverse=True)
print("扫了 %d 个会话文件 ｜ 连续重复 >= %d 的字符串 %d 处" % (len(files), MINRUN, len(hits)))
for run, mtime, sid, typ, path, ch, ln, sample in hits[:25]:
    print("-" * 110)
    print("最长连续 %d 个 %r ｜ 会话 %s (%s) ｜ 事件 %s%s ｜ 字段 %d 字"
          % (run, ch, sid[:20], mtime, typ, path[:40], ln))
    print("    …%s…" % sample.replace("\n", " ⏎ ")[:170])
