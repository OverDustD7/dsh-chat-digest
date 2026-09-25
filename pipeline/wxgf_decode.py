# -*- coding: utf-8 -*-
"""Decode WeChat .wxgf (wrapped HEVC) to JPG using PyAV — pure Python, no external binaries.

.wxgf = 4-byte magic 'wxgf' + small header + HEVC Annex-B stream (+ optional trailer).
Strategy: locate the first HEVC start code, hand the remainder to PyAV's raw hevc demuxer.
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
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = r"WORK_DIR"
OUTDIR = os.path.join(HERE, "output", "window", "_wxgf_test")
os.makedirs(OUTDIR, exist_ok=True)


def find_start(blob):
    i = blob.find(b"\x00\x00\x00\x01")
    if i < 0:
        i = blob.find(b"\x00\x00\x01")
    return i


def decode_wxgf(blob):
    off = find_start(blob)
    if off < 0:
        return None, "no HEVC start code"
    stream = blob[off:]
    import av
    for fmt in ("hevc", "h265", None):
        try:
            buf = io.BytesIO(stream)
            container = av.open(buf, format=fmt) if fmt else av.open(buf)
            for frame in container.decode(video=0):
                img = frame.to_image()
                return img, "fmt=%s nals_offset=%d" % (fmt, off)
        except Exception as e:  # noqa: BLE001
            last = "%s: %s" % (fmt, type(e).__name__)
            continue
    return None, "decode failed (%s)" % last


files = sorted(glob.glob(os.path.join(HERE, "output", "window", "images", "**", "*.wxgf"), recursive=True))
print("wxgf total:", len(files))
sample = files[:6]
ok = 0
for p in sample:
    with open(p, "rb") as f:
        blob = f.read()
    img, info = decode_wxgf(blob)
    if img is None:
        print("  FAIL %-56s %s" % (os.path.basename(p), info))
        continue
    ok += 1
    dst = os.path.join(OUTDIR, os.path.splitext(os.path.basename(p))[0] + ".jpg")
    img.convert("RGB").save(dst, quality=92)
    print("  OK   %-56s %sx%s %s -> %s" % (os.path.basename(p), img.width, img.height, info, os.path.basename(dst)))
print("decoded %d/%d" % (ok, len(sample)))