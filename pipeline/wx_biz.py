# -*- coding: utf-8 -*-
"""wx_biz.py — 提取微信公众号文章（biz_message_0）→ output/window/biz_articles.jsonl

用法: python wx_biz.py [--days N]
输出字段: ts / account / title / url / desc / type
"""
# ── 个人信息一律来自 pconf（<localDir>/pipeline.yaml）────────────────────────
# 这个文件里**不许写死任何路径 / 群名 / 账号**；缺键时 pconf 会打印缺哪个键、
# 去哪个文件填，并以退出码 2 结束。
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from pconf import C  # noqa: E402

WX_ACCOUNT_DIR = C.get("wx_account_dir")
WX_MSG_GLOB = C.get("wx_msg_glob")
WX_KEY_DIR = C.get("wx_key_dir")
QQ_DATA_DIR = C.get("qq_data_dir")
WORK_DIR = C.get("work_dir")
SELF_WXID = C.get("self_wxid")
MAIN_GROUP = C.get("main_group")

OUT_DIR = C.get("output_dir")
GROUPS = C.groups
# ────────────────────────────────────────────────────────────────────────────
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
from extract_window import decode_wx_content  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=8))
WX = os.path.join(HERE, "output", "wx")
BIZ = os.path.join(WX, "biz_message_0_plain.db")
OUT = os.path.join(HERE, "output", "window", "biz_articles.jsonl")

days = None
if "--days" in sys.argv:
    days = int(sys.argv[sys.argv.index("--days") + 1])
cut = int((dt.datetime.now(TZ) - dt.timedelta(days=days)).timestamp()) if days else 0

ct = sqlite3.connect(os.path.join(WX, "contact_plain.db"))
names = {r[0]: (r[1] or r[2] or r[0]) for r in ct.execute("SELECT username, remark, nick_name FROM contact")}
ct.close()


def biz_names():
    """`__biz` → **真号名**（来自 fetch_article.mjs 抓回的正文元数据）。

    2026-09-15 修 #27：`contact` 表里的 remark/nick_name 是他给这个号起的备注，会跟真号名不一致
    （实测：显示名与真实号名常不一致）→ **以抓回的元数据为准**
    （`output\\window\\articles\\*.md` 的 `- 公众号：X`；这张缓存由 3k-b 一起维护）。
    """
    m = {}
    adir = os.path.join(HERE, "output", "window", "articles")
    if not os.path.isdir(adir):
        return m
    for fn in os.listdir(adir):
        if not fn.endswith(".md"):
            continue
        try:
            with open(os.path.join(adir, fn), encoding="utf-8", errors="replace") as fh:
                head = fh.read()[:1500]
        except OSError:
            continue
        u = re.search(r"https?://mp\.weixin\.qq\.com/s\?[^\"<\s]+", head)
        b = re.search(r"__biz=([A-Za-z0-9=+/]+)", u.group(0)) if u else None
        acc = re.search(r"公众号[ \t]*[：:][ \t]*([^\n]+)", head)
        if b and acc and acc.group(1).strip() not in ("-", ""):
            m.setdefault(b.group(1), acc.group(1).strip())
    return m


BIZ2NAME = biz_names()
if BIZ2NAME:
    print("[wx_biz] 抓到 %d 个号的真实名（覆盖 contact 备注）" % len(BIZ2NAME))

con = sqlite3.connect(BIZ)
tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
arts, per = [], {}
for t in tabs:
    h = t[4:]
    chat = next((u for u in names if hashlib.md5(u.encode()).hexdigest() == h), None)
    acct = names.get(chat, chat or h)
    try:
        rows = con.execute('SELECT create_time, message_content, compress_content FROM "%s" WHERE create_time >= ? ORDER BY create_time DESC' % t, (cut,)).fetchall()
    except Exception:
        continue
    if not rows:
        continue
    per[acct] = len(rows)
    for ts, mc, cc in rows:
        dec = decode_wx_content(mc, cc)
        if not dec:
            continue
        title = re.search(r"<title>(?:<!\[CDATA\[)?(.{2,150}?)(?:\]\]>)?</title>", dec, re.S)
        url = re.search(r"<url>(?:<!\[CDATA\[)?(https?://[^<\]]+)", dec, re.S)
        desc = re.search(r"<des>(?:<!\[CDATA\[)?(.{2,200}?)(?:\]\]>)?</des>", dec, re.S)
        if title:
            u = (url.group(1).strip() if url else "")
            b = re.search(r"__biz=([A-Za-z0-9=+/]+)", u)
            acct_real = BIZ2NAME.get(b.group(1)) if b else None      # #27：抓回的真号名优先
            arts.append({"ts": ts, "account": (acct_real or acct),
                         "title": title.group(1).strip(),
                         "url": u,
                         "desc": (desc.group(1).strip() if desc else ""),
                         "src_account": (acct if acct_real else "")})
con.close()
arts.sort(key=lambda a: -a["ts"])
with open(OUT, "w", encoding="utf-8") as f:
    for a in arts:
        f.write(json.dumps(a, ensure_ascii=False) + "\n")
f2 = lambda ts: dt.datetime.fromtimestamp(ts, TZ).strftime("%m-%d %H:%M")
from collections import Counter as _C
print("公众号文章条目:", len(arts), "| 覆盖公众号:", len(per))
per_day = _C(dt.datetime.fromtimestamp(a["ts"], TZ).strftime("%m-%d") for a in arts)
print("\n=== 近 10 天每日文章数（用于自证某天确实是 0 篇） ===")
for _d, _n in sorted(per_day.items())[-10:]:
    print("   %s  %d" % (_d, _n))
print("\n=== 最近 20 篇 ===")
for a in arts[:20]:
    print("  [%s] %-16s %s" % (f2(a["ts"]), a["account"][:16], a["title"][:64]))
    if a["url"]:
        print("        %s" % a["url"][:110])
print("\n->", OUT)
with_url = sum(1 for a in arts if a["url"])
print("带链接的:", with_url, "/", len(arts))