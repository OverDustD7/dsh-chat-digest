# -*- coding: utf-8 -*-
"""extract_day.py <YYYY-MM-DD> — extract one day's messages (WeChat + QQ) into a readable file.

Outputs:
  output/days/<date>.jsonl   full structured rows (chat/ts/sender/type/text/raw)
  output/days/<date>.txt     readable, noise-filtered digest for reading

2026-09-20 审计修复：
  A02  私聊漏接 —— 旧版只 `SELECT … FROM group_messages`，而导出库里 397 条私聊
       （`c2c_messages`）一条都没进日提取。现在**群聊与私聊都收**，`src` 都是 `QQ`，
       `chat_kind` 区分 group/c2c。
  A12  原始层不再截断（`raw` 去掉 `[:6000]`）、QQ 正文不再 `re.sub(r"\\s+", " ")`
       压平换行（"12，31 是班级编号不是题号"那次事故就是压平换行读成一句话导致的）；
       新增**稳定消息身份** `msg_id`（跨重跑去重的键）与来源 `src_db`/`src_table`。
       列名用 `PRAGMA table_info` 自省，兼容真实导出库与合成测试库的形状差异。
"""
import datetime as dt
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
from extract_window import decode_wx_content, wx_text_summary, wx_type_label  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=8))
WX = os.path.join(HERE, "output", "wx")
QQ = os.environ.get("QQ_EXPORT") or os.path.join(HERE, "output", "qq", "nt_msg_export.db")
OUTD = os.path.join(HERE, "output", "days")
os.makedirs(OUTD, exist_ok=True)
SELF_WX = "<your-wxid>"
SELF_QQ = C.req("self_qq", "你的 QQ 号")

if len(sys.argv) < 2:
    raise SystemExit("extract_day.py: 缺日期参数（用法：extract_day.py YYYY-MM-DD）")
date = sys.argv[1]
try:
    __import__("datetime").datetime.strptime(date, "%Y-%m-%d")
except Exception:
    raise SystemExit("extract_day.py: 日期参数必须是 YYYY-MM-DD，收到 %r" % (date,))
y, m, d = (int(x) for x in date.split("-"))
lo = int(dt.datetime(y, m, d, 0, 0, 0, tzinfo=TZ).timestamp())
hi = lo + 86400
print("day %s  epoch %d..%d" % (date, lo, hi))

# ---- WeChat ----
con = sqlite3.connect(os.path.join(WX, "contact_plain.db"))
contact = {}
for u, rem, nick in con.execute("SELECT username, remark, nick_name FROM contact"):
    if u:
        contact[u] = rem or nick or u
con.close()

rows = []
for db in sorted(glob.glob(os.path.join(WX, "message_[0-9]_plain.db"))):
    con = sqlite3.connect(db)
    tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
    if not tabs:
        con.close()
        continue
    try:
        n2u = {r[0]: r[1] for r in con.execute("SELECT rowid, user_name FROM Name2Id")}
    except sqlite3.OperationalError:
        n2u = {}
        print("  [warn] %s has no Name2Id table -> sender ids unresolved" % os.path.basename(db))
    for t in tabs:
        try:
            data = con.execute('SELECT local_id, server_id, real_sender_id, create_time, local_type, '
                               'message_content, compress_content '
                               'FROM "%s" WHERE create_time >= ? AND create_time < ?' % t, (lo, hi)).fetchall()
        except Exception:
            continue
        if not data:
            continue
        username = "unknown:" + t[4:]
        for u in n2u.values():
            if hashlib.md5((u or "").encode()).hexdigest() == t[4:]:
                username = u
                break
        for lid, svid, sid, ts, lt, mc, cc in data:
            dec = decode_wx_content(mc, cc)
            sender_u = n2u.get(sid) or str(sid)
            rows.append({"src": "WX", "chat": username, "chat_name": contact.get(username, username),
                         "ts": ts, "sender": sender_u,
                         "sender_name": "我" if sender_u == SELF_WX else (contact.get(sender_u) or sender_u),
                         "type": wx_type_label(lt), "text": wx_text_summary(dec), "raw": dec or "",
                         # A12：稳定身份 —— local_id 在同一会话表内单调且跨重跑不变
                         "msg_id": "WX:%s:%s" % (username, lid), "server_id": svid,
                         "src_db": os.path.basename(db), "src_table": t, "chat_kind": "wx"})
    con.close()

# ---- QQ ----
# A02：群聊 + 私聊。真实导出库两张表的列不同（group_messages 有 group_id，
# c2c_messages 有 peer_uid/peer_qq），合成测试库又是另一套 → 一律自省列名后再拼 SQL。
from extract_window import qq_content_summary  # noqa: E402


def qq_table_cols(conn, table):
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)]
    except Exception:
        return []


def qq_extract(conn, table, kind, gname):
    cols = qq_table_cols(conn, table)
    if not cols:
        return []
    def pick(*names):
        for n in names:
            if n in cols:
                return n
        return None
    c_ts = pick("timestamp")
    if not c_ts:
        return []
    if kind == "group":
        c_chat = pick("group_id", "group_qq")
    else:
        c_chat = pick("peer_qq", "peer_uid", "group_id")
    c_sender = pick("sender_qq", "sender_uid")
    c_mid, c_text, c_cont = pick("msg_id"), pick("text"), pick("content")
    c_mt, c_ct = pick("msg_type"), pick("content_type")
    want = [x for x in (c_mid, c_ts, c_chat, c_sender, c_mt, c_ct, c_text, c_cont) if x]
    out = []
    for rec in conn.execute("SELECT %s FROM %s WHERE %s >= ? AND %s < ?"
                            % (", ".join(want), table, c_ts, c_ts), (lo, hi)):
        g = dict(zip(want, rec))
        s = (g.get(c_text) or "").strip() if c_text else ""
        if not s and c_cont:
            s = str(qq_content_summary(g.get(c_cont), g.get(c_text)) or "")
        chat = str(g.get(c_chat) or "")
        sqq = str(g.get(c_sender) or "")
        name = gname.get(chat, chat) if kind == "group" else chat
        out.append({"src": "QQ", "chat": chat, "chat_name": name, "ts": g.get(c_ts),
                    "sender": sqq,
                    "sender_name": "我" if sqq == SELF_QQ else sqq,
                    # A12：不再压平换行（压平会把两段读成一句）；raw 不截断
                    "type": ("QQ%d/%s" % (g.get(c_mt) or 0, g.get(c_ct)) if kind == "group"
                             else "QQ私聊%d/%s" % (g.get(c_mt) or 0, g.get(c_ct))),
                    "text": s, "raw": (g.get(c_cont) or ""),
                    "msg_id": "QQ:%s:%s:%s" % (kind, chat, g.get(c_mid) if c_mid else "?"),
                    "src_db": os.path.basename(QQ), "src_table": table, "chat_kind": kind})
    return out


if os.path.exists(QQ):
    gname = {}
    try:
        g2 = sqlite3.connect(os.path.join(HERE, "output", "qq", "raw", "group_info.db"))
        for r in g2.execute('SELECT "60001", "60007" FROM group_detail_info_ver1'):
            gname[str(r[0])] = r[1]
        g2.close()
    except Exception:
        pass
    con = sqlite3.connect(QQ)
    rows += qq_extract(con, "group_messages", "group", gname)
    c2c = qq_extract(con, "c2c_messages", "c2c", gname)
    if c2c:
        print("  QQ 私聊 %d 条（A02：旧版完全没接）" % len(c2c))
    rows += c2c
    con.close()
else:
    print("  [warn] QQ 导出库不存在，跳过 QQ：%s" % QQ)

rows.sort(key=lambda r: r["ts"])
with open(os.path.join(OUTD, "%s.jsonl" % date), "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# noise-filtered readable digest（**展示层**：这里的截断带显式标记，原始层在 jsonl 里）
NOISE = re.compile(r"^\s*$|^\[(表情|图片|视频|语音|系统|位置|名片)|^\[XML|^\[卡片\]\s*$|^.{0,3}$")
DISP_MAX = 300
by_chat = {}
for r in rows:
    by_chat.setdefault(r["chat_name"], []).append(r)
kept = 0
with open(os.path.join(OUTD, "%s.txt" % date), "w", encoding="utf-8") as f:
    f.write("=== %s 微信 %d 条 + QQ %d 条（其中私聊 %d 条），共 %d 条 ===\n\n" % (
        date, sum(1 for r in rows if r["src"] == "WX"), sum(1 for r in rows if r["src"] == "QQ"),
        sum(1 for r in rows if r.get("chat_kind") == "c2c"), len(rows)))
    for chat, items in sorted(by_chat.items(), key=lambda kv: -len(kv[1])):
        f.write("\n" + "=" * 88 + "\n会话: %s（%d 条）\n" % (chat, len(items)))
        for r in items:
            t = r["text"]
            if r["type"] == "系统" or NOISE.match(t):
                continue
            kept += 1
            # 换行写成可见的 ⏎（不要压成空格：会把两段读成一句 —— 见 KNOWN_ISSUES 的"12，31"事故）
            disp = t.replace("\r", "").replace("\n", " ⏎ ")
            mark = ""
            if len(disp) > DISP_MAX:
                mark = " …[+%d字，原文见 jsonl 的 raw]" % (len(disp) - DISP_MAX)
                disp = disp[:DISP_MAX]
            f.write("[%s] %s: %s%s\n" % (dt.datetime.fromtimestamp(r["ts"], TZ).strftime("%H:%M:%S"),
                                         r["sender_name"], disp, mark))
print("rows:", len(rows), "| digest lines kept:", kept)
print("->", os.path.join(OUTD, "%s.txt" % date))
