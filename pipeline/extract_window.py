# -*- coding: utf-8 -*-
"""
Extract window messages (2026-09-10 00:00 CST -> now) from decrypted QQ + WeChat DBs.
Outputs:
  output/window/qq_groups.txt      readable per-group timelines
  output/window/qq_c2c.txt         private-chat messages
  output/window/wx_chats.txt       readable per-chat timelines
  output/window/wx_raw.jsonl       structured rows (for further analysis)
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
import base64
import datetime as dt
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import zstandard as zstd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(os.path.dirname(HERE), "output", "window")
QQEXP = os.path.join(os.path.dirname(HERE), "output", "qq", "nt_msg_export.db")
QQRAW = os.path.join(os.path.dirname(HERE), "output", "qq", "raw")
WXOUT = os.path.join(os.path.dirname(HERE), "output", "wx")
SELF_WX = SELF_WXID

TZ = dt.timezone(dt.timedelta(hours=8))
# default window: 2026-09-10 00:00 CST -> now
# override: python extract_window.py <start_epoch> [out_tag]
CUT = int(dt.datetime(2026, 9, 10, 0, 0, 0, tzinfo=TZ).timestamp())
NOW = int(time.time())
TAG = ""
if len(sys.argv) > 1:
    try:            # tolerate being imported as a module (argv then holds the caller's args)
        CUT = int(sys.argv[1])
    except ValueError:
        pass
if len(sys.argv) > 2:
    TAG = sys.argv[2]


def fmt_ts(ts):
    try:
        return dt.datetime.fromtimestamp(int(ts), TZ).strftime("%m-%d %H:%M:%S")
    except Exception:
        return "?"


def fmt_ts_short(ts):
    try:
        return dt.datetime.fromtimestamp(int(ts), TZ).strftime("%m-%d %H:%M")
    except Exception:
        return "?"


def decode_wx_content(mc, cc):
    """Return (text, kind) for WeChat message payload."""
    def try_blob(raw):
        if raw and raw[:4] == b"\x28\xb5\x2f\xfd":
            try:
                d = zstd.ZstdDecompressor().decompress(raw, max_output_size=16 * 1024 * 1024)
                return d.decode("utf-8", errors="ignore")
            except Exception:
                return None
        return None

    def from_str(s):
        s = s.strip()
        if not s:
            return None
        if len(s) >= 16 and len(s) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", s):
            try:
                b = bytes.fromhex(s)
            except Exception:
                return None
            d = try_blob(b)
            if d is not None:
                return d
            return b.decode("utf-8", errors="ignore")
        if re.fullmatch(r"[A-Za-z0-9+/=]{16,}", s):
            try:
                b = base64.b64decode(s)
            except Exception:
                return None
            d = try_blob(b)
            if d is not None:
                return d
            return b.decode("utf-8", errors="ignore")
        return s

    for v in (mc, cc):
        if v is None:
            continue
        if isinstance(v, str):
            r = from_str(v)
            if r:
                return r
        elif isinstance(v, (bytes, bytearray, memoryview)):
            b = bytes(v)
            d = try_blob(b)
            if d is not None:
                return d
            r = b.decode("utf-8", errors="ignore")
            if r.strip():
                return r
    return None


WX_TYPE = {1: "文本", 3: "图片", 34: "语音", 43: "视频", 47: "表情", 49: "卡片", 50: "语音通话", 10000: "系统", 10002: "系统"}
WX_USER_TYPES = {"wxid_", "@chatroom", "gh_"}


def wx_type_label(t):
    if isinstance(t, int) and t > 0x10000:
        t = t & 0xFFFF
    return WX_TYPE.get(t, "类型%d" % t)


def wx_text_summary(decoded):
    """Extract readable text from decoded XML or plain text."""
    if decoded is None:
        return ""
    s = decoded.strip()
    if s.startswith("<"):
        out = []
        for tag in ("title", "des", "content"):
            m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), s, re.S)
            if m:
                t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if t:
                    out.append(t)
        if out:
            return " | ".join(out)
        # maybe plain text inside <msg> without title
        m = re.match(r"<\?xml.*?>\s*<msg>(.*)</msg>", s, re.S)
        if m:
            body = re.sub(r"<[^>]+>", " ", m.group(1))
            body = re.sub(r"\s+", " ", body).strip()
            if body:
                return body[:500]
        if "<img" in s:
            return "[图片消息]"
        return "[XML: %s...]" % s[:80]
    return s[:800]


def qq_content_summary(content_json, text_field):
    """Return readable summary from QQ exported content JSON."""
    if text_field:
        return str(text_field)
    try:
        j = json.loads(content_json)
    except Exception:
        return str(content_json)[:300]
    if isinstance(j, dict) and j.get("type") == "msg_body":
        segs = j.get("segments", [])
        parts = []
        for s in segs:
            ct = s.get("content_type")
            if ct == 1 and s.get("text"):
                parts.append(str(s["text"]))
            elif ct == 2 and s.get("filename"):
                parts.append("[图片:%s]" % s["filename"])
            elif ct == 3 and s.get("text"):
                parts.append("[语音]")
            elif ct == 4 and s.get("text"):
                parts.append("[视频:%s]" % s.get("filename", ""))
            elif ct == 6 and s.get("text"):
                parts.append("[文件:%s]" % s.get("filename", ""))
            elif ct == 10:
                fm = s.get("fwd_meta", "")
                parts.append("[转发]%s" % str(fm)[:200])
            elif ct == 11 and s.get("text"):
                parts.append("[贴图]")
            elif ct == 12 and s.get("text"):
                parts.append("[链接:%s]" % str(s.get("text"))[:200])
            elif ct == 14 and s.get("text"):
                parts.append("[动画表情]")
            else:
                t = s.get("text")
                if t:
                    parts.append("[%s:%s]" % (ct, str(t)[:150]))
        return " ".join(parts) if parts else str(j)[:300]
    if isinstance(j, dict) and "meta" in j:
        # template message (public account): meta.meta.<app>.<fields>
        def deep(d, depth=0):
            if depth > 6 or not isinstance(d, dict):
                return ""
            for k in ("title", "subTitle", "content", "text"):
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            for k, v in d.items():
                if k in ("app", "type", "msgId", "templateId", "version", "source"):
                    continue
                r = deep(v, depth + 1)
                if r:
                    return r
            return ""

        m = j.get("meta", {})
        s = deep(m)
        return "【模板消息】%s" % s[:300] if s.strip() else str(m)[:300]
    return str(j)[:300]


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    stats = {}

    # ================= QQ =================
    print("[QQ] loading group names / members...")
    gi = sqlite3.connect(os.path.join(QQRAW, "group_info.db"))
    group_name = {}
    for r in gi.execute('SELECT "60001", "60007" FROM group_detail_info_ver1'):
        group_name[str(r[0])] = r[1]
    member_name = {}  # (group_id, uid) -> name
    try:
        for r in gi.execute("SELECT 60001, 1000, 20002, 64003 FROM group_member3"):
            gid, uid, nick, card = str(r[0]), r[1], r[2], r[3]
            name = (card or "").strip() if isinstance(card, str) else ""
            if not name:
                name = (nick or "").strip() if isinstance(nick, str) else ""
            if uid:
                member_name[(gid, str(uid))] = name
    except Exception as e:
        print("  group_member3 partial:", e)
    gi.close()

    qq = sqlite3.connect(QQEXP)
    groups = {}
    c2c = []
    for r in qq.execute(
        "SELECT group_id, timestamp, direction, sender_uid, sender_qq, msg_type, content_type, text, content FROM group_messages WHERE timestamp >= ? AND timestamp <= ?",
        (CUT, NOW),
    ):
        gid, ts, dire, suid, sqq, mtype, ctype, text, content = r
        gid = str(gid or "0")
        groups.setdefault(gid, []).append((ts, dire, suid, sqq, mtype, ctype, text, content))
    for r in qq.execute(
        "SELECT timestamp, direction, sender_uid, sender_qq, peer_uid, peer_qq, msg_type, content_type, text, content FROM c2c_messages WHERE timestamp >= ? AND timestamp <= ?",
        (CUT, NOW),
    ):
        c2c.append(r)
    qq.close()

    print("[QQ] writing...")
    with open(os.path.join(OUTDIR, "qq_groups%s.txt" % TAG), "w", encoding="utf-8") as f:
        for gid in sorted(groups, key=lambda g: -len(groups[g])):
            msgs = sorted(groups[gid])
            name = group_name.get(gid, gid)
            f.write("=" * 70 + "\n")
            f.write("群: %s (群号 %s)  消息 %d 条  %s ~ %s\n" % (name, gid, len(msgs), fmt_ts_short(msgs[0][0]), fmt_ts_short(msgs[-1][0])))
            for ts, dire, suid, sqq, mtype, ctype, text, content in msgs:
                nm = ""
                if suid:
                    nm = member_name.get((gid, suid)) or str(suid)
                elif sqq:
                    nm = member_name.get((gid, str(sqq))) or str(sqq)
                if not nm:
                    nm = "未知成员"
                line = "%s  %s: %s" % (fmt_ts(ts), nm, qq_content_summary(content, text) or "[空]")
                f.write(line + "\n")
    with open(os.path.join(OUTDIR, "qq_c2c%s.txt" % TAG), "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n私聊消息窗口内 %d 条\n" % len(c2c))
        for r in sorted(c2c):
            ts, dire, suid, sqq, puid, pqq, mtype, ctype, text, content = r
            f.write("%s  %s: %s\n" % (fmt_ts(ts), ("我->" if dire else "") + str(pqq), qq_content_summary(content, text) or "[空]"))
    stats["qq"] = {"groups": {g: len(v) for g, v in groups.items()}, "c2c": len(c2c)}

    # ================= WeChat =================
    print("[WX] loading contacts...")
    conn = sqlite3.connect(os.path.join(WXOUT, "contact_plain.db"))
    contact = {}  # username -> display name (remark > nick > username)
    for r in conn.execute("SELECT username, remark, nick_name FROM contact"):
        u, rem, nick = r
        if not u:
            continue
        contact[u] = rem or nick or u
    conn.close()

    print("[WX] scanning message DBs...")
    chats = {}  # username -> list of (ts, sender_name, type_label, text, is_self)
    for db in sorted(glob.glob(os.path.join(WXOUT, "message_*_plain.db"))):
        conn = sqlite3.connect(db)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        n2u = {}
        for r in conn.execute("SELECT rowid, user_name FROM Name2Id"):
            n2u[r[0]] = r[1]
        for t in tables:
            if not t.startswith("Msg_"):
                continue
            u = n2u.get(int(t[4:], 16) if False else 0)  # placeholder
            # resolve username via md5: table name = Msg_<md5(username)>
            rows = conn.execute(
                'SELECT real_sender_id, create_time, local_type, message_content, compress_content FROM "%s" WHERE create_time >= ? AND create_time <= ?' % t,
                (CUT, NOW),
            ).fetchall()
            if not rows:
                continue
            username = "unknown:" + t[4:]
            for r in conn.execute("SELECT user_name FROM Name2Id"):  # fallback: find by md5
                if hashlib.md5((r[0] or "").encode()).hexdigest() == t[4:]:
                    username = r[0]
                    break
            chat = chats.setdefault(username, [])
            for sid, ts, lt, mc, cc in rows:
                dec = decode_wx_content(mc, cc)
                txt = wx_text_summary(dec)
                sender_u = n2u.get(sid) or str(sid)
                is_self = sender_u == SELF_WX
                sender_name = "我" if is_self else (contact.get(sender_u) or sender_u)
                raw = (dec or "").strip()
                if len(raw) > 20000:
                    raw = raw[:20000]
                chat.append((ts, sender_name, wx_type_label(lt), txt, is_self, sender_u, raw))
        conn.close()

    with open(os.path.join(OUTDIR, "wx_raw%s.jsonl" % TAG), "w", encoding="utf-8") as f:
        for u, msgs in chats.items():
            for ts, sn, tl, txt, is_self, su, raw in sorted(msgs):
                f.write(json.dumps({"chat": u, "chat_name": contact.get(u, u), "ts": ts, "sender": su, "sender_name": sn, "type": tl, "text": txt, "raw": raw}, ensure_ascii=False) + "\n")

    with open(os.path.join(OUTDIR, "wx_chats%s.txt" % TAG), "w", encoding="utf-8") as f:
        for u in sorted(chats, key=lambda x: -len(chats[x])):
            msgs = sorted(chats[u])
            f.write("=" * 70 + "\n")
            f.write("会话: %s (%s)  消息 %d 条  %s ~ %s\n" % (contact.get(u, u), u, len(msgs), fmt_ts_short(msgs[0][0]), fmt_ts_short(msgs[-1][0])))
            for ts, sn, tl, txt, is_self, su, raw in msgs:
                if tl != "文本":
                    line = "%s  %s(%s): [%s] %s" % (fmt_ts(ts), sn, su, tl, txt[:300])
                else:
                    line = "%s  %s: %s" % (fmt_ts(ts), sn, txt[:500])
                f.write(line + "\n")
    stats["wx"] = {u: len(v) for u, v in chats.items()}

    print(json.dumps(stats, ensure_ascii=False, indent=1))
    print("[done] outputs in", OUTDIR)


if __name__ == "__main__":
    main()