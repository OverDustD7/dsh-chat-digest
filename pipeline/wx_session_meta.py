# -*- coding: utf-8 -*-
"""Export per-chat notification metadata: mute level (extra_buffer field 11) + unread.

mute field 11 semantics (2026-09-12, reverse-engineered against user-confirmed anchors):
  1 = 正常提醒 (confirmed: 主群)
  2 = 免打扰   (confirmed: 另两个群)
  3 = 待确认   (用户说这个群没静音，但值是 3)
Output: output/window/session_meta.json
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
import json
import os
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "output", "window", "session_meta.json")
# ⚠ 2026-09-14 修正：原表是 {1:"免打扰", 0:"正常"}，与实测取值完全错位
# （脚本自己 docstring 写的是 1=正常/2=免打扰/3=待确认，代码却把 1 标成免打扰）。
# 注意：这个字段本身的结论已被推翻 —— 见 DEV_NOTES「免打扰不在这些字段里」，
# 判断免打扰请用 docs/knowledge/channels.md 的人工清单。
MUTE_LABEL = {0: "正常", 1: "正常", 2: "免打扰", 3: "待确认"}


def parse_pb(buf):
    out = defaultdict(list)
    i, n = 0, len(buf)
    while i < n:
        shift = key = 0
        while i < n:
            b = buf[i]; i += 1
            key |= (b & 0x7F) << shift; shift += 7
            if not (b & 0x80):
                break
        fno, wt = key >> 3, key & 7
        if wt == 0:
            shift = val = 0
            while i < n:
                b = buf[i]; i += 1
                val |= (b & 0x7F) << shift; shift += 7
                if not (b & 0x80):
                    break
            out[fno].append(val)
        elif wt == 2:
            shift = ln = 0
            while i < n:
                b = buf[i]; i += 1
                ln |= (b & 0x7F) << shift; shift += 7
                if not (b & 0x80):
                    break
            out[fno].append(buf[i:i + ln]); i += ln
        elif wt == 5:
            i += 4
        elif wt == 1:
            i += 8
        else:
            break
    return out


con = sqlite3.connect(os.path.join(HERE, "output", "wx", "contact_plain.db"))
names, mute = {}, {}
for u, rem, nick, ex in con.execute(
        "SELECT username, remark, nick_name, extra_buffer FROM contact"):
    if not u:
        continue
    names[u] = rem or nick or u
    if isinstance(ex, (bytes, bytearray)) and ex:
        pb = parse_pb(bytes(ex))
        # field 12 = 免打扰标志：1 = 免打扰，0 = 正常
        # (field 11 is NOT mute — verified 2026-09-12 against 6 user-confirmed anchors)
        f = pb.get(12)
        if f:
            mute[u] = f[0]
con.close()

unread = {}
con = sqlite3.connect(os.path.join(HERE, "output", "wx", "session_plain.db"))
for u, n, lt in con.execute("SELECT username, unread_count, last_timestamp FROM SessionTable"):
    unread[u] = {"unread": n, "last_ts": lt}
con.close()

meta = {}
for u in set(list(names) + list(unread)):
    m = mute.get(u)
    meta[u] = {
        "name": names.get(u, u),
        "mute": m,
        "mute_label": MUTE_LABEL.get(m, "未知"),
        "unread": (unread.get(u) or {}).get("unread"),
        "last_ts": (unread.get(u) or {}).get("last_ts"),
        "is_chatroom": u.endswith("@chatroom"),
    }
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=1)
print("wrote", OUT, "chats:", len(meta))

from collections import Counter
c = Counter(v["mute_label"] for v in meta.values() if v["is_chatroom"])
print("chatroom mute distribution:", dict(c))
print("\n=== 免打扰(2) 群清单 ===")
for u, v in sorted(meta.items()):
    if v["is_chatroom"] and v["mute"] == 2:
        print("   %-36s %s" % (u, v["name"]))
print("\n=== 正常(1) 群清单 ===")
for u, v in sorted(meta.items()):
    if v["is_chatroom"] and v["mute"] == 1:
        print("   %-36s %s" % (u, v["name"]))