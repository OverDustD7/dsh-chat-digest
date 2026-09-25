# -*- coding: utf-8 -*-
"""day_brief.py <YYYY-MM-DD> — condensed per-chat brief (input for the summariser, not for the user)."""
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
import json
import os
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = dt.timezone(dt.timedelta(hours=8))
if len(sys.argv) < 2:
    raise SystemExit("day_brief.py: 缺日期参数（用法：day_brief.py YYYY-MM-DD）")
date = sys.argv[1]
try:
    __import__("datetime").datetime.strptime(date, "%Y-%m-%d")
except Exception:
    raise SystemExit("day_brief.py: 日期参数必须是 YYYY-MM-DD，收到 %r" % (date,))
SRC = os.path.join(HERE, "output", "days", "%s.jsonl" % date)
OUT = os.path.join(HERE, "output", "days", "%s_brief.md" % date)

rows = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
by = defaultdict(list)
for r in rows:
    by[(r["src"], r["chat_name"])].append(r)

NOISE = re.compile(r"^\s*$|^\[(表情|图片|视频|语音|系统|位置|名片)|^\[XML|^.{0,4}$")
KW = ("选课", "课程", "老师", "教材", "学分", "宿舍", "食堂", "社团", "比赛", "实习", "保研",
      "考试", "报到", "军训", "通知", "报名", "讲座", "资源", "经验", "建议", "提醒", "注意",
      "重要", "网址", "链接", "群文件", "领", "免", "免费", "申请", "安排", "时间", "地点")

out = ["# %s 精简提要（供提炼用）" % date, "",
       "总消息 %d 条，会话 %d 个" % (len(rows), len(by)), ""]
for (src, chat), items in sorted(by.items(), key=lambda kv: -len(kv[1])):
    items.sort(key=lambda r: r["ts"])
    times = [r["ts"] for r in items]
    out.append("\n## [%s] %s —— %d 条（%s ~ %s）" % (
        src, chat, len(items),
        dt.datetime.fromtimestamp(min(times), TZ).strftime("%H:%M"),
        dt.datetime.fromtimestamp(max(times), TZ).strftime("%H:%M")))
    # keep: keyword hits, long texts, or first/last of bursts
    keep, seen = [], set()
    for r in items:
        t = (r.get("text") or "").strip()
        if r.get("type") == "系统" or NOISE.match(t):
            continue
        score = 0
        if any(k in t for k in KW):
            score += 2
        if len(t) >= 25:
            score += 1
        if r.get("src") == "QQ" and "QQ1/" in (r.get("type") or ""):
            score += 1
        if score:
            key = t[:40]
            if key in seen:
                continue
            seen.add(key)
            keep.append((score, r))
    keep.sort(key=lambda x: -x[0])
    for score, r in keep[:22]:
        out.append("- [%s] %s: %s" % (dt.datetime.fromtimestamp(r["ts"], TZ).strftime("%H:%M"),
                                      r["sender_name"], (r.get("text") or "")[:220]))
    if not keep:
        out.append("- （仅闲聊/表情，无信息量）")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("wrote", OUT, os.path.getsize(OUT), "bytes,", len(out), "lines")
