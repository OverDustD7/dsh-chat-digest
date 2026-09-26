# -*- coding: utf-8 -*-
"""day_stats.py — 给一天的数据"量体裁衣"，决定怎么切分给子代理（只读）。

用法: python tools\\day_stats.py [YYYY-MM-DD]
输出：总量 / 各来源 / 按会话的"有效消息"量（过滤纯图片、表情、系统噪音）/ 图片与文件 / 链接
"""
import collections
import datetime as dt
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = dt.timezone(dt.timedelta(hours=8))
DATE = sys.argv[1] if len(sys.argv) > 1 else dt.datetime.now(TZ).strftime("%Y-%m-%d")

NOISE = re.compile(r"^(\[[^\]]{0,12}\]|<?(img|sysmsg|appmsg|emoji|revokemsg)|<sysmsg|$)")
PURE_MEDIA = re.compile(r"^\s*(\[[^\]]{0,16}\]|\[图片[^\]]*\]|\[表情[^\]]*\]|\[动画表情\]|\[视频\]|\[语音\]|\[文件\])[\s]*$")


def hm(ts):
    return dt.datetime.fromtimestamp(int(ts), TZ).strftime("%m-%d %H:%M")


rows = []
for line in io.open(os.path.join(HERE, "output", "days", "%s.jsonl" % DATE),
                    encoding="utf-8", errors="replace"):
    line = line.strip()
    if line:
        rows.append(json.loads(line))

print("日期 %s ｜ 总行数 %d" % (DATE, len(rows)))
print("按来源:", dict(collections.Counter(r.get("src") for r in rows)))

by = collections.defaultdict(lambda: {"all": 0, "eff": 0, "chars": 0, "min": None, "max": 0,
                                      "media": 0, "url": 0, "who": collections.Counter()})
url_re = re.compile(r"https?://")
for r in rows:
    name = (r.get("chat_name") or r.get("chat") or "?").strip()
    t = r.get("text") or ""
    b = by[name]
    b["all"] += 1
    ts = int(r.get("ts") or 0)
    b["min"] = ts if b["min"] is None else min(b["min"], ts)
    b["max"] = max(b["max"], ts)
    if PURE_MEDIA.match(t):
        b["media"] += 1
    elif not NOISE.match(t) and len(t) > 10:
        b["eff"] += 1
        b["chars"] += len(t)
        b["who"][r.get("sender_name") or r.get("sender") or "?"] += 1
    if url_re.search(t) or url_re.search(r.get("raw") or ""):
        b["url"] += 1

print("\n%-34s %6s %6s %8s %6s %5s  %s" % ("会话", "总", "有效", "有效字数", "图/媒", "带链", "时段"))
for name, b in sorted(by.items(), key=lambda kv: -kv[1]["eff"]):
    if b["eff"] == 0 and b["all"] < 20:
        continue
    print("%-34s %6d %6d %8d %6d %5d  %s~%s" % (
        name[:32], b["all"], b["eff"], b["chars"], b["media"], b["url"],
        hm(b["min"]) if b["min"] else "?", hm(b["max"])))

tot_eff = sum(b["eff"] for b in by.values())
print("\n合计有效消息 %d 条（%d 个会话）｜ 按 300–350 条/组 → 约 %d 组"
      % (tot_eff, len(by), max(1, round(tot_eff / 325))))

img = os.path.join(HERE, "output", "days", "%s_images.json" % DATE)
if os.path.exists(img):
    j = json.load(io.open(img, encoding="utf-8"))
    n = len(j) if isinstance(j, list) else len(j.get("items") or j.get("images") or [])
    print("图片索引条目 %d" % n)
