# -*- coding: utf-8 -*-
"""shrink_md_images.py — 检查 md 引用图的像素尺寸；超过阈值就生成小图副本并把引用改成小图。

用 Markdown 原生可见性 + 小文件体积：md 引用 <base>_s.jpg（宽 ≤480），原图保留不删。
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
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from PIL import Image  # noqa: E402
Image.MAX_IMAGE_PIXELS = None

ROOT = r"WORK_DIR"
D = os.path.join(ROOT, "docs")
IMG = re.compile(r'<img\b[^>]*src="([^"]+)"[^>]*>')
MAXW = 480

for f in sorted(os.listdir(D)):
    if not f.endswith(".md"):
        continue
    p = os.path.join(D, f)
    t = io.open(p, encoding="utf-8").read()
    hits = [s for s in IMG.findall(t) if not s.endswith("...") and "<会话>" not in s and "..." not in s]
    if not hits:
        continue
    changed = 0
    for src in hits:
        real = os.path.normpath(os.path.join(D, src))
        if not os.path.exists(real) or os.path.getsize(real) == 0:
            print("  [缺] %s -> %s" % (f, src[:60]))
            continue
        try:
            with Image.open(real) as im:
                w, h = im.size
                fmt = im.format
        except Exception as e:  # noqa: BLE001
            print("  [坏] %s -> %s (%s)" % (f, src[:50], e))
            continue
        need = w > MAXW
        small = os.path.splitext(real)[0] + "_s.jpg"
        print("  %-26s %5dx%-5d %8d B  %s" % (os.path.basename(real)[:24], w, h,
                                              os.path.getsize(real), "→ 生成小图" if need else "尺寸OK"))
        if need:
            if not os.path.exists(small):
                with Image.open(real) as im:
                    im = im.convert("RGB")
                    nh = max(1, int(h * MAXW / w))
                    im.resize((MAXW, nh), Image.LANCZOS).save(small, "JPEG", quality=86)
            rel_small = os.path.relpath(small, D).replace("\\", "/")
            t = t.replace(src, rel_small)
            changed += 1
    if changed:
        io.open(p, "w", encoding="utf-8").write(t)
        print("  -> %s：%d 处引用改为小图" % (f, changed))
