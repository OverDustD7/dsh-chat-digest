# -*- coding: utf-8 -*-
"""diag_url30.py — 量化 KNOWN_ISSUES #30：step 6 链接提取到底漏了多少。

对比三个来源（同一天）：
  A. 现行 step 6 产物      output/window/all_urls.jsonl      （窗口快照，只到 09-12 14:22）
  B. 当天全量产物          output/days/<date>.jsonl          （text/raw 有截断：2000/6000）
  C. 数据库当天全量        QQ 直接查 nt_msg_export.db（不截断）+ WX 用 B
只读，不写任何产物。
"""
import datetime as dt
import io
import json
import os
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
from extract_window import qq_content_summary  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=8))
DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-09-12"
y, m, d = (int(x) for x in DATE.split("-"))
START = int(dt.datetime(y, m, d, 0, 0, 0, tzinfo=TZ).timestamp())
END = START + 86400

URL_RE = re.compile(r"https?://[^\s\"'<>\\）)】]+")
HOST_SKIP = ("tianquan.gtimg.cn", "zb.vip.qq.com")


def fmt(ts):
    if not ts:
        return "?"
    return dt.datetime.fromtimestamp(ts, TZ).strftime("%m-%d %H:%M:%S")


def urls_of(blob, out):
    for u in URL_RE.findall(blob or ""):
        if any(x in u for x in HOST_SKIP):
            continue
        out.add(u)


# ---------- A. 现行产物 ----------
cur = os.path.join(HERE, "output", "window", "all_urls.jsonl")
a_rows = []
if os.path.exists(cur):
    with io.open(cur, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                a_rows.append(json.loads(line))
a_ts = [int(r["ts"]) for r in a_rows if r.get("ts")]
a_on_day = [r for r in a_rows if r.get("ts") and START <= int(r["ts"]) < END]
print("A 现行产物 all_urls.jsonl")
print("   行数=%d  唯一URL=%d" % (len(a_rows), len({r["url"] for r in a_rows})))
print("   时间跨度=%s ~ %s" % (fmt(min(a_ts)) if a_ts else "?", fmt(max(a_ts)) if a_ts else "?"))
print("   落在 %s 当天=%d 行，唯一URL=%d" % (DATE, len(a_on_day), len({r["url"] for r in a_on_day})))
print("   当天最大 ts=%s" % (fmt(max((int(r['ts']) for r in a_on_day), default=0))))

# ---------- B. 当天 jsonl ----------
dayp = os.path.join(HERE, "output", "days", "%s.jsonl" % DATE)
b_urls, b_msgs, b_min, b_max, b_src = set(), 0, None, 0, {}
for line in io.open(dayp, encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line:
        continue
    j = json.loads(line)
    ts = int(j.get("ts") or 0)
    if not (START <= ts < END):
        continue
    b_msgs += 1
    b_src[j.get("src")] = b_src.get(j.get("src"), 0) + 1
    b_min = ts if b_min is None else min(b_min, ts)
    b_max = max(b_max, ts)
    urls_of(j.get("text"), b_urls)
    urls_of(j.get("raw"), b_urls)
print("B 当天产物 days/%s.jsonl" % DATE)
print("   当天消息=%d  %s" % (b_msgs, b_src))
print("   时间跨度=%s ~ %s" % (fmt(b_min), fmt(b_max)))
print("   唯一URL=%d（text/raw 截断：2000/6000）" % len(b_urls))

# ---------- C. QQ 库当天全量（不截断） ----------
c_urls = set(b_urls)
con = sqlite3.connect(os.path.join(HERE, "output", "qq", "nt_msg_export.db"))
n_qq = 0
for text, content in con.execute(
        "SELECT text, content FROM group_messages WHERE timestamp >= ? AND timestamp < ?",
        (START, END)):
    n_qq += 1
    s = (text or "").strip() or str(qq_content_summary(content, text) or "")
    urls_of(s, c_urls)
    urls_of(content, c_urls)
con.close()
print("C QQ库当天全量（不截断）")
print("   QQ消息=%d" % n_qq)
print("   唯一URL=%d" % len(c_urls))

# ---------- 差异 ----------
only_c = c_urls - b_urls
print("")
print("== 差异 ==")
print("B 相对 A（当天全量 vs 现行产物）新增 URL：%d" % len(b_urls - {r["url"] for r in a_rows}))
print("C 相对 B（不截断还多出）：%d" % len(only_c))
for u in list(only_c)[:10]:
    print("     + %s" % u[:120])
print("结论：现行产物当天唯一URL=%d，当天应有=%d（A→B 漏 %d 条）"
      % (len({r['url'] for r in a_on_day}), len(b_urls), len(b_urls) - len({r['url'] for r in a_on_day})))
