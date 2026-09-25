# -*- coding: utf-8 -*-
"""favorites.py — 完整解析微信收藏（favorite.db）→ docs/knowledge/collections.md

收藏 = 用户主动存下的东西 = 最可靠的"他关心什么"信号。
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
import os
import re
import sqlite3
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = r"WORK_DIR"
WX = os.path.join(HERE, "output", "wx")
TZ = dt.timezone(dt.timedelta(hours=8))
OUT = os.path.join(HERE, "docs", "knowledge", "collections.md")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
TYPE = {1: "文字", 2: "图片", 3: "视频", 4: "音频", 5: "链接/文章", 6: "位置", 7: "文件", 8: "文件",
        14: "聊天记录", 16: "小程序", 18: "视频号"}

con = sqlite3.connect(os.path.join(WX, "favorite_plain.db"))
con.text_factory = lambda b: b.decode("utf-8", "replace")
cn = sqlite3.connect(os.path.join(WX, "contact_plain.db"))
cn.text_factory = lambda b: b.decode("utf-8", "replace")
names = {r[0]: (r[1] or r[2] or r[0]) for r in cn.execute("SELECT username, remark, nick_name FROM contact")}
cn.close()

rows = list(con.execute("SELECT local_id, type, update_time, content, fromusr, realchatname FROM fav_db_item"))
con.close()

def wx_title(biz, mid, idx="1", share=None):
    """抓公众号文章标题/号名（本机直连）。

    2026-09-15 修：原先只拼 `__biz&mid&idx` **最小链接** → 微信不认（缺 `sn`），
    于是收藏里 6 篇文章的号名一直是 `?`（`official_accounts.md` 的待办①卡了很久）。
    实测：`fav_db_item.content` 里**本来就有带 `sn&chksm` 的完整链接**，直接用它即可。
    """
    url = share or "https://mp.weixin.qq.com/s?__biz=%s&mid=%s&idx=%s" % (biz, mid, idx)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
        acc = re.search(r'id="js_name"[^>]*>\s*([^<]{1,40})', html)
        ttl = (re.search(r"var\s+msg_title\s*=\s*'([^']{2,120})'", html)
               or re.search(r'<h1[^>]*id="activity-name"[^>]*>\s*([^<]{2,120})', html)
               or re.search(r"<title[^>]*>([^<]{2,120})</title>", html))
        return (acc.group(1).strip() if acc else ""), (ttl.group(1).strip() if ttl else ""), url
    except Exception as e:  # noqa: BLE001
        return "", "", url

lines = ["# 微信收藏（= 用户主动存下的东西，最可靠的兴趣信号）", "",
         "> 来源：`favorite.db`（`fav_db_item` 表，%d 条）。**收藏比聊天更准**——这是他主动标记「有用」的东西。" % len(rows), "",
         "| # | 类型 | 内容 | 收藏时间 | 收藏来源 |", "|---|---|---|---|---|"]
detail = []
for lid, typ, ut, content, fromusr, realchat in sorted(rows, key=lambda r: -(r[2] or 0)):
    c = content or ""
    t = TYPE.get(typ, "type%s" % typ)
    desc = re.search(r"<desc>(?:<!\[CDATA\[)?(.{1,160}?)(?:\]\]>)?</desc>", c, re.S)
    title = re.search(r"<title>(?:<!\[CDATA\[)?(.{1,160}?)(?:\]\]>)?</title>", c, re.S)
    biz = re.search(r"__biz=([A-Za-z0-9=+/]+)", c)
    mid = re.search(r"mid=(\d+)", c)
    idx = re.search(r"idx=(\d+)", c)
    src = re.search(r'<source[^>]*sourceid="([^"]{1,200})"', c)
    plain = re.sub(r"<[^>]+>", " ", c)
    plain = re.sub(r"\s+", " ", plain).strip()
    label = (title.group(1) if title else (desc.group(1) if desc else plain[:120]))
    who = names.get(fromusr or "", fromusr or "")
    if fromusr == SELF_WXID:
        who = "**他自己收藏的**"
    elif (fromusr or "").endswith("@chatroom"):
        who = "群：" + who + ("（%s 发）" % names.get(realchat or "", realchat) if realchat else "")
    when = dt.datetime.fromtimestamp(ut, TZ).strftime("%m-%d %H:%M") if ut else "?"
    extra = ""
    if biz and mid:
        # 优先用原始 content 里的完整分享链接（带 sn&chksm，微信才认）
        _full = re.search(r"https?://mp\.weixin\.qq\.com/s\?[^\"<\s]+", c)
        _share = _full.group(0).replace("&amp;", "&") if _full else None
        acc, ttl, url = wx_title(biz.group(1), mid.group(1), idx.group(1) if idx else "1", _share)
        extra = "｜公众号 **%s**：%s" % (acc or "?", ttl or "?")
        detail.append("- [%s] %s ｜ %s ｜ %s\n    %s" % (when, t, label[:80], extra, url))
    else:
        link = (src.group(1) if src else "")
        detail.append("- [%s] %s ｜ %s%s%s" % (when, t, label[:100], (" ｜ " + link[:90]) if link else "", ""))
    lines.append("| %d | %s | %s%s | %s | %s |" % (lid, t, label[:70].replace("|", "／"), extra, when, who))
lines += ["", "## 逐条明细（含解析出的公众号/链接）", ""] + detail
lines += ["", "## 这份收藏说明了什么（提炼时当作「他关心什么」的硬证据）", "",
    # （原来这里写死了"作者本人收藏夹的结论"—— 对别人不成立，已删）
          "- 收藏来源既有「他自己存的」，也有**别人在群里发的**（说明这些群/人发的这类内容他认可）。"]
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w", encoding="utf-8").write("\n".join(lines))
print("收藏条数:", len(rows), "->", OUT)
for l in lines[:20]:
    print(l[:180])