# -*- coding: utf-8 -*-
"""Filter QQ water-group messages to information-bearing candidates.

Fix: QQ export leaves `text` empty for non-text messages; the real payload is in
`content` (JSON). Reuse extract_window.qq_content_summary() to render readable text.
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
import json
import os
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
from extract_window import qq_content_summary  # noqa: E402  (reuse parser)

TZ = dt.timezone(dt.timedelta(hours=8))
CUT = int(dt.datetime(2026, 9, 11, 0, 0, 0, tzinfo=TZ).timestamp())
OUT = os.path.join(HERE, "output", "qq", "qq_candidates.txt")
OUTJ = os.path.join(HERE, "output", "qq", "qq_candidates.jsonl")
SELF_QQ = C.req("self_qq", "你的 QQ 号")

KW = ("选课", "课程", "老师", "教材", "学分", "绩点", "宿舍", "食堂", "社团", "比赛", "实习",
      "保研", "考试", "作业", "选专业", "分流", "奖学金", "四六级", "托福", "雅思", "驾照",
      "电脑", "显示器", "二手", "拼车", "机票", "火车票", "医院", "体检", "军训", "录取",
      "通知书", "导员", "辅导员", "书院", "志愿", "社工", "图书馆", "导师", "报名", "讲座",
      "宣讲", "招聘", "机会", "资源", "经验", "建议", "提醒", "注意", "重要", "群文件",
      "攻略", "指南", "时间表", "课程表", "培养方案", "转专业", "双学位", "辅修", "交换",
      "答疑", "新生", "报到", "入住", "快递", "外卖", "校车", "医保", "户口", "档案", "军训")
URL_RE = re.compile(r"https?://[^\s\"'<>\\]+")

gname = {}
try:
    g2 = sqlite3.connect(os.path.join(HERE, "output", "qq", "raw", "group_info.db"))
    for r in g2.execute('SELECT "60001", "60007" FROM group_detail_info_ver1'):
        gname[str(r[0])] = r[1]
    g2.close()
except Exception as e:
    print("group names:", e)

con = sqlite3.connect(os.path.join(HERE, "output", "qq", "nt_msg_export.db"))
rows = con.execute(
    "SELECT group_id, timestamp, sender_uid, sender_qq, msg_type, content_type, text, content "
    "FROM group_messages WHERE timestamp >= ? ORDER BY timestamp", (CUT,)).fetchall()
con.close()
print("total rows in window:", len(rows))

cands = []
reasons = {}
for gid, ts, suid, sqq, mt, ct, text, content in rows:
    text = (text or "").strip()
    summary = text or qq_content_summary(content, text) or ""
    summary = re.sub(r"\s+", " ", str(summary)).strip()
    content_s = content or ""
    # drop un-rendered JSON repr and bare image placeholders (water-group noise)
    if ("'segments'" in summary and summary.startswith("{")) or re.fullmatch(r"\[图片[:：].*\]", summary):
        summary = ""
    why = []
    if len(summary) >= 40:
        why.append("long")
    if URL_RE.search(summary) or URL_RE.search(content_s):
        why.append("url")
    if any(k in summary for k in KW):
        why.append("kw")
    if "所有人" in summary:
        why.append("atall")
    docs = [x for x in re.findall(r'"fileName"\s*:\s*"([^"]+)"', content_s, re.I)
            if not re.search(r"\.(jpg|jpeg|png|gif|webp|bmp|dat|amr|sil|silk)$", x, re.I)]
    if docs:
        why.append("file")
        if not summary:
            summary = "[文件] " + "; ".join(docs[:3])
    if not summary:
        urls = list(dict.fromkeys(URL_RE.findall(content_s)))
        if urls:
            summary = "[链接] " + "; ".join(urls)[:400]
    if not why:
        continue
    if not summary:
        summary = "(无可读文本)"
    for w in why:
        reasons[w] = reasons.get(w, 0) + 1
    cands.append({
        "group_id": str(gid), "group_name": gname.get(str(gid), "?"), "ts": ts,
        "time": dt.datetime.fromtimestamp(ts, TZ).strftime("%m-%d %H:%M:%S"),
        "sender_qq": str(sqq or ""), "sender_uid": str(suid or ""),
        "is_self": str(sqq) == SELF_QQ, "reasons": why,
        "text": summary[:2000],
    })

print("reasons:", reasons)
print("candidates(raw):", len(cands), "/", len(rows))

# dedupe identical content within a group (water groups get spammed with repeats)
seen = set()
uniq = []
for c in cands:
    key = (c["group_id"], c["text"][:160])
    if key in seen:
        continue
    seen.add(key)
    uniq.append(c)
cands = uniq
print("candidates(dedup):", len(cands))

with open(OUTJ, "w", encoding="utf-8") as f:
    for c in cands:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("QQ 候选信息（09-11 00:00 ~ now）共 %d 条 / 总 %d 条\n" % (len(cands), len(rows)))
    f.write("筛选理由计数: %s\n\n" % reasons)
    cur = None
    for c in cands:
        if c["group_id"] != cur:
            cur = c["group_id"]
            f.write("\n" + "=" * 90 + "\n群: %s (%s)\n" % (c["group_name"], cur))
        f.write("[%s] %s%s | %s\n" % (c["time"], "我 " if c["is_self"] else "",
                                     c["sender_qq"][:12], ",".join(c["reasons"])))
        f.write("   " + c["text"][:600] + "\n")
print("wrote", OUT)