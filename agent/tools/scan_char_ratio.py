# -*- coding: utf-8 -*-
"""scan_char_ratio.py — 找"某字符占比异常高"的文本（对付 W W W / W\\nW\\n 这种不连续刷屏）。

用法: python tools\\scan_char_ratio.py [只扫最近 N 分钟，默认 30]
"""
import collections
import datetime as dt
import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DSH = os.path.join(os.environ.get("USERPROFILE", ""), ".dsh", "sessions")
TZ = dt.timezone(dt.timedelta(hours=8))
MINS = float(sys.argv[1]) if len(sys.argv) > 1 else 30
try:
    from compression import zstd as _zstd
except Exception:  # noqa: BLE001
    _zstd = None


def load(path):
    data = _zstd.decompress(io.open(path, "rb").read())
    out = []
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                pass
    return out


def strings(o, path=""):
    if isinstance(o, str):
        yield path, o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from strings(v, path + "." + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from strings(v, path + "[%d]" % i)


cut = dt.datetime.now().timestamp() - MINS * 60
files = [p for p in glob.glob(os.path.join(DSH, "*", "*", "session.v3.jsonl.zstd"))
         if os.path.getmtime(p) >= cut]
print("扫最近 %.0f 分钟内的 %d 个会话" % (MINS, len(files)))
tot = 0
for p in sorted(files, key=os.path.getmtime):
    sid = os.path.basename(os.path.dirname(p))
    when = dt.datetime.fromtimestamp(os.path.getmtime(p), TZ).strftime("%H:%M:%S")
    try:
        evs = load(p)
    except Exception as e:  # noqa: BLE001
        print("!! %s %s" % (sid[:12], e))
        continue
    for i, ev in enumerate(evs):
        for path, s in strings(ev):
            if len(s) < 400:
                continue
            c = collections.Counter(s)
            ch, n = c.most_common(1)[0]
            r = n / len(s)
            if r > 0.30:
                tot += 1
                head = s[:60].replace("\n", " ")
                tail = s[-60:].replace("\n", " ")
                print("-" * 110)
                print("会话 %s (%s) 事件[%d] %s%s" % (sid[:12], when, i, ev.get("type"), path[:40]))
                print("  最长字符 %r 占 %.0f%%（%d/%d）｜ 头：%s ｜ 尾：%s" % (ch, r * 100, n, len(s), head, tail))
print("命中 >30%% 的字段：%d" % tot)
