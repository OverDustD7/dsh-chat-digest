# -*- coding: utf-8 -*-
"""Storage scan: WeChat + QQ local data — sizes by category, biggest files, junk candidates."""
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
import os
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
WX = r"WX_ACCOUNT_DIR"
QQ = os.path.join(QQ_DATA_DIR, SELF_QQ)
OUT = r"OUT_DIR\window\storage_scan.md"

MB = 1024.0 * 1024

# 已知无价值/占空间的目录特征
JUNK_DIR_HINTS = ("cache", "temp", "Emoticon", "Emoji", "Thumb")
VAL_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md", ".csv"}


def scan(root, label):
    cat = defaultdict(lambda: [0, 0])   # rel-top -> [bytes, count]
    ext = Counter()
    ext_sz = defaultdict(int)
    big = []
    junk = []
    total = 0
    for d, dirs, fs in os.walk(root):
        rel = os.path.relpath(d, root)
        top = rel.split(os.sep)[0] if rel != "." else "(root)"
        for f in fs:
            p = os.path.join(d, f)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            total += sz
            cat[top][0] += sz
            cat[top][1] += 1
            e = os.path.splitext(f)[1].lower()
            ext[e] += 1
            ext_sz[e] += sz
            if sz >= 5 * MB:
                big.append((sz, p))
            if any(h.lower() in d.lower() for h in JUNK_DIR_HINTS) and sz >= 1 * MB:
                junk.append((sz, p, "junk-dir"))
    big.sort(reverse=True)
    junk.sort(reverse=True)
    return {"label": label, "total": total, "cat": cat, "ext": ext, "ext_sz": ext_sz, "big": big, "junk": junk}


res = [scan(WX, "微信"), scan(QQ, "QQ")]
lines = ["# 本地聊天数据占用扫描\n"]
allbig = []
alljunk = []
for r in res:
    lines.append("\n## %s：总计 %.1f MB" % (r["label"], r["total"] / MB))
    lines.append("\n| 子目录 | 占用 | 文件数 |\n|---|---|---|")
    for k, (b, n) in sorted(r["cat"].items(), key=lambda kv: -kv[1][0])[:14]:
        lines.append("| %s | %.1f MB | %d |" % (k, b / MB, n))
    lines.append("\n按扩展名（占用 top10）：")
    for e, b in sorted(r["ext_sz"].items(), key=lambda kv: -kv[1])[:10]:
        lines.append("- `%s` — %.1f MB（%d 个）" % (e or "(无扩展名)", b / MB, r["ext"].get(e, 0)))
    lines.append("\n大文件（≥5MB）:")
    for sz, p in r["big"][:15]:
        lines.append("- %.1f MB — `%s`" % (sz / MB, p))
        allbig.append((sz, p, r["label"]))
    if r["junk"]:
        lines.append("\n疑似无用目录（cache/temp/表情/缩略图，且单文件 ≥1MB）:")
        for sz, p, why in r["junk"][:15]:
            lines.append("- %.1f MB — `%s`" % (sz / MB, p))
            alljunk.append((sz, p))
    lines.append("")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

for r in res:
    print("%s 总计 %.1f MB" % (r["label"], r["total"] / MB))
    print("   top dirs:", [(k, "%.0fMB" % (v[0] / MB)) for k, v in sorted(r["cat"].items(), key=lambda kv: -kv[1][0])[:6]])
    print("   big files:", len(r["big"]), "| junk-candidates:", len(r["junk"]))
print("\n=== 全局大文件 TOP15 ===")
for sz, p, lab in sorted(allbig, reverse=True)[:15]:
    print("  %8.1f MB [%s] %s" % (sz / MB, lab, p))
print("\nwrote", OUT)