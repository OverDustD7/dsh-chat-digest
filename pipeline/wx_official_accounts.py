# -*- coding: utf-8 -*-
"""wx_official_accounts.py — 盘点微信公众号：关注列表 + 聊天记录里的推送量 + 出现过的文章作者。

输出：docs/knowledge/official_accounts.md
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
import glob
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(HERE, "docs", "knowledge")
TZ = dt.timezone(dt.timedelta(hours=8))
OUT = os.path.join(DOCS, "official_accounts.md")

# 1) 关注列表
con = sqlite3.connect(os.path.join(HERE, "output", "wx", "contact_plain.db"))
followed = {}
for u, rem, nick in con.execute("SELECT username, remark, nick_name FROM contact WHERE username LIKE 'gh_%'"):
    followed[u] = rem or nick or u
con.close()
print("关注/在录的公众号数:", len(followed))

# 2) 聊天记录里这些号的推送量（窗口 + 按天）
msgs = Counter()
first_ts, last_ts = {}, {}
mydays = set()
srcs = [os.path.join(HERE, "output", "window", "wx_raw.jsonl")]
srcs += sorted(glob.glob(os.path.join(HERE, "output", "days", "*.jsonl")))
for p in srcs:
    if not os.path.exists(p) or p.endswith("_images.json"):
        continue
    try:
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            j = json.loads(line)
            if j.get("src") not in (None, "WX"):
                continue
            chat = j.get("chat") or ""
            if not chat.startswith("gh_"):
                continue
            msgs[chat] += 1
            ts = j.get("ts") or 0
            first_ts[chat] = min(first_ts.get(chat, ts), ts) if chat in first_ts else ts
            last_ts[chat] = max(last_ts.get(chat, ts), ts) if chat in last_ts else ts
    except Exception as e:
        print("  skip", os.path.basename(p), e)

# 3) 聊天里出现过的公众号文章链接（找 __biz / 标题）
biz = Counter()
art = []
for p in srcs:
    if not os.path.exists(p):
        continue
    try:
        for line in open(p, encoding="utf-8"):
            j = json.loads(line)
            blob = (j.get("raw") or "") + " " + (j.get("text") or "")
            for m in re.finditer(r'mp\.weixin\.qq\.com/s\?[^"\'<>\s]+', blob):
                url = m.group(0).replace("&amp;", "&")
                b = re.search(r"__biz=([^&]+)", url)
                biz[b.group(1) if b else "?"] += 1
                t = re.search(r"<title>([^<]{2,80})</title>", blob)
                art.append((j.get("chat_name") or j.get("chat") or "?", t.group(1) if t else "", url[:120]))
    except Exception:
        pass

f = lambda ts: dt.datetime.fromtimestamp(ts, TZ).strftime("%m-%d %H:%M") if ts else "?"

lines = ["# 微信公众号盘点（关注列表 · 推送量 · 文章线索）", "",
         "> 由 `scripts/wx_official_accounts.py` 生成；**每日子代理应扫描 `gh_*` 会话的新推送**（当天的公众号文章就在这里）。", "",
         "## 一、在录公众号（contact 表 `gh_*`）按推送量排序", "",
         "| # | 公众号 | 推送条数 | 时间范围 |", "|---|---|---|---|"]
rank = sorted(followed, key=lambda u: -msgs.get(u, 0))
for i, u in enumerate(rank[:40], 1):
    lines.append("| %d | %s | %d | %s ~ %s |" % (i, followed[u], msgs.get(u, 0),
                                                  f(first_ts.get(u)), f(last_ts.get(u))))
lines += ["", "## 二、聊天里出现过的文章链接（按 biz 去重，供识别高价值作者）", ""]
for k, v in biz.most_common(30):
    lines.append("- `__biz=%s` × %d" % (k, v))
lines += ["", "## 三、出现过的文章标题样本", ""]
seen = set()
for chat, title, url in art:
    if title and title not in seen:
        seen.add(title)
        lines.append("- %s ｜ %s ｜ %s" % (chat, title[:60], url[:90]))
os.makedirs(DOCS, exist_ok=True)
open(OUT, "w", encoding="utf-8").write("\n".join(lines))
print("推送过的公众号:", sum(1 for u in followed if msgs.get(u)))
print("文章链接条数:", len(art), "| 不同 biz:", len(biz))
print("->", OUT)