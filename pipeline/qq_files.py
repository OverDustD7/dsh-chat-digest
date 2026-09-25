# -*- coding: utf-8 -*-
"""List every file-type message in QQ groups (by filename pattern), since files aren't local."""
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
TZ = dt.timezone(dt.timedelta(hours=8))
OUT = os.path.join(HERE, "output", "qq", "qq_file_msgs.md")

gname = {}
g2 = sqlite3.connect(os.path.join(HERE, "output", "qq", "raw", "group_info.db"))
for r in g2.execute('SELECT "60001", "60007" FROM group_detail_info_ver1'):
    gname[str(r[0])] = r[1]
g2.close()

FN = re.compile(r"([\w\u4e00-\u9fa5][\w\u4e00-\u9fa5\.\-\(\)（）\[\] ]{1,90}\.(?:zip|rar|7z|pdf|doc|docx|xlsx?|pptx?|txt|md|csv|apk|exe|mp4|mp3|jpg|jpeg|png))", re.I)

con = sqlite3.connect(os.path.join(HERE, "output", "qq", "nt_msg_export.db"))
rows = []
for gid, ts, sqq, text, content in con.execute(
        "SELECT group_id, timestamp, sender_qq, text, content FROM group_messages ORDER BY timestamp"):
    blob = (text or "") + " " + (content or "")
    names = [n for n in dict.fromkeys(FN.findall(blob)) if len(n) > 3]
    if not names:
        continue
    size = re.search(r'"fileSize"\s*:\s*"?(\d{3,})', content or "")
    rows.append({"gid": str(gid), "g": gname.get(str(gid), "?"), "ts": ts,
                 "who": str(sqq or ""), "names": names[:4],
                 "size": int(size.group(1)) if size else None,
                 "text": re.sub(r"\s+", " ", (text or ""))[:160]})
con.close()

print("file-type messages:", len(rows))
with open(OUT, "w", encoding="utf-8") as f:
    f.write("# QQ 群里的文件类消息（文件本体基本未下载到本地，需在 QQ 客户端「群文件」里找）\n\n")
    f.write("共 %d 条\n\n" % len(rows))
    cur = None
    for r in sorted(rows, key=lambda x: x["ts"]):
        if r["g"] != cur:
            cur = r["g"]
            f.write("\n## %s\n" % cur)
        t = dt.datetime.fromtimestamp(r["ts"], TZ).strftime("%m-%d %H:%M")
        sz = ("  %.1f MB" % (r["size"] / 1048576)) if r["size"] else ""
        f.write("- [%s] %s\n" % (t, " / ".join(r["names"]) + sz))
        if r["text"]:
            f.write("    %s\n" % r["text"][:120])

# focus: the math-textbook zip
print("\n=== 含“数学教材”/zip 的条目 ===")
for r in rows:
    if any(("数学教材" in n) or n.lower().endswith((".zip", ".rar", ".7z")) for n in r["names"]):
        t = dt.datetime.fromtimestamp(r["ts"], TZ).strftime("%m-%d %H:%M")
        print("  [%s] %s %s %s" % (t, r["g"][:16], r["names"], r["text"][:80]))
print("\nwrote", OUT)