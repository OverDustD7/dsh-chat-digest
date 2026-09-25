# -*- coding: utf-8 -*-
"""Batch-transcode .wxgf -> .jpg for images referenced by the window index, then update index.json.

Pure Python (PyAV). Keeps original .wxgf; writes sibling .jpg and appends it to index paths.
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
import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(HERE, "output", "window", "images")
IDX = os.path.join(IMG, "index.json")
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 0  # 0 = all

import av  # noqa: E402


def decode(path):
    with open(path, "rb") as f:
        blob = f.read()
    i = blob.find(b"\x00\x00\x00\x01")
    if i < 0:
        i = blob.find(b"\x00\x00\x01")
    if i < 0:
        return None
    try:
        container = av.open(io.BytesIO(blob[i:]), format="hevc")
        for frame in container.decode(video=0):
            return frame.to_image()
    except Exception:
        return None
    return None


index = json.load(open(IDX, encoding="utf-8"))
# collect wxgf references from index
refs = []
for rec in index:
    for p in rec.get("path") or []:
        if p.lower().endswith(".wxgf"):
            refs.append(p)
refs = list(dict.fromkeys(refs))
print("wxgf referenced by index.json:", len(refs))

done, fail = 0, 0
mapping = {}
targets = refs if LIMIT <= 0 else refs[:LIMIT]
for rel in targets:
    src = os.path.join(IMG, rel.replace("/", os.sep))
    dst = os.path.splitext(src)[0] + ".jpg"
    relj = os.path.splitext(rel)[0] + ".jpg"
    if os.path.exists(dst):
        mapping[rel] = relj
        done += 1
        continue
    img = decode(src)
    if img is None:
        fail += 1
        continue
    img.convert("RGB").save(dst, quality=92)
    mapping[rel] = relj
    done += 1
print("transcoded:", done, "failed:", fail)

# update index.json: append jpg path + mark transcode
changed = 0
for rec in index:
    paths = rec.get("path") or []
    add = [mapping[p] for p in paths if p in mapping and mapping[p] not in paths]
    if add:
        rec["path"] = paths + add
        rec["transcoded"] = "wxgf->jpg (PyAV)"
        changed += 1
json.dump(index, open(IDX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("index entries updated:", changed, "->", IDX)