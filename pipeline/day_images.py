# -*- coding: utf-8 -*-
"""day_images.py <YYYY-MM-DD> — per-day image index (reuses wx_images internals).

Because wx_images.py only indexes the "current window", this script indexes ONE day:
  output/days/<date>.jsonl  ->  output/days/<date>_images.json
Output rows: {chat, chat_name, ts, sender, md5, thumb_len, anchor, path:[...]}
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
import hashlib
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import wx_images as W  # noqa: E402  (reuse key resolution / decryption / format detection)

if len(sys.argv) < 2:
    raise SystemExit("day_images.py: 缺日期参数（用法：day_images.py YYYY-MM-DD）")
date = sys.argv[1]
try:
    __import__("datetime").datetime.strptime(date, "%Y-%m-%d")
except Exception:
    raise SystemExit("day_images.py: 日期参数必须是 YYYY-MM-DD，收到 %r" % (date,))
SRC = os.path.join(HERE, "output", "days", "%s.jsonl" % date)
OUTP = os.path.join(HERE, "output", "days", "%s_images.json" % date)
STATUS_P = os.path.join(HERE, "output", "days", "%s_images.status.json" % date)
#: 专属退出码：解不出图片密钥（最常见原因＝微信未登录）——调用方据此标「待微信登录」而不是 FAILED。
EXIT_NO_KEY = 3
rows = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]

# ---- collect image messages of that day ----
img_msgs = []
for r in rows:
    blob = (r.get("raw") or "") or (r.get("text") or "")
    m = (re.findall(r'<img\b[^>]*?\bmd5="([0-9a-f]{32})"', blob, re.I | re.S)
         or W.MD5_RE.findall(blob))
    if not m:
        continue
    tl = re.search(r'cdnthumblength="(\d+)"', blob, re.I)
    img_msgs.append({"chat": r["chat"], "chat_name": r["chat_name"], "ts": r["ts"],
                     "sender": r["sender_name"], "md5": m[0].lower(),
                     "thumb_len": int(tl.group(1)) if tl else None})
print("image msgs on %s: %d" % (date, len(img_msgs)))
if not img_msgs:
    json.dump([], open(OUTP, "w", encoding="utf-8"))
    print("->", OUTP)
    sys.exit(0)

kv = W.find_kvcomm()
keys = W.resolve_key(kv) if kv else None
if not keys:
    # 2026-09-15：这里以前只打一行 "[ERR] image key unresolved" 然后 exit 1，
    # 结果"微信未登录"这种**上游前置条件缺失**被显示成"第 4 步 FAILED"，看着像脚本坏了。
    # 现在：写明原因 + 落一份机器可读的状态文件 + 用**专属退出码 3**（EXIT_NO_KEY），
    # 让 daily_prep.py 把它标成「待微信登录」而不是 FAILED。
    reason = W.LAST_KEY_REASON or "图片密钥解析失败（原因未知）"
    login = W.wx_login_state(kv) if kv else {}
    print("[ERR] image key unresolved: %s" % reason)
    try:
        json.dump({"ok": False, "date": date, "reason": reason,
                   "loggedIn": login.get("loggedIn"),
                   "codeNegotiated": login.get("codeNegotiated"),
                   "lastUin": login.get("lastUin", ""),
                   "kvcomm": kv or "",
                   "at": __import__("time").strftime("%Y-%m-%d %H:%M:%S")},
                  open(STATUS_P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except OSError as e:
        print("  (状态文件写失败：%s)" % e)
    sys.exit(EXIT_NO_KEY)
xor_key, aes_key = keys
login_ok = W.wx_login_state(kv)
try:
    json.dump({"ok": True, "date": date, "keySource": W.LAST_KEY_SOURCE or "?",
               "codeNegotiated": login_ok.get("codeNegotiated"),
               "note": ("" if login_ok.get("codeNegotiated") else
                        "微信客户端没协商出密钥（kvcomm 只有 code=0 占位）：本日索引仍已生成"
                        "（用已验证的本机 code 兜底），但登录前不会有新图片进来"),
               "at": __import__("time").strftime("%Y-%m-%d %H:%M:%S")},
              open(STATUS_P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
except OSError:
    pass

# chat -> display name (from the day's rows)
chat_md5, chat_name = {}, {}
for r in rows:
    c = r.get("chat") or ""
    if c:
        chat_md5.setdefault(c, hashlib.md5(c.encode("utf-8")).hexdigest())
        chat_name.setdefault(c, r.get("chat_name") or c)
md5_to_chat = {v: k for k, v in chat_md5.items()}

# ---- scan library once, build content-md5 index + thumb-length index ----
attach = os.path.join(W.WX_ROOT, "msg", "attach")
content_index, thumb_index = {}, {}
CACHE_P = os.path.join(HERE, "output", "window", "_images_scan_cache.json")
cache = {}
if os.path.exists(CACHE_P):
    try:
        with open(CACHE_P, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
cache0 = len(cache)
scanned = ok = 0
cache_hits = 0
for d, dirs, files in os.walk(attach):
    parts = d.replace(attach, "").lstrip("\\/").split("\\")
    chat_hash = parts[0] if parts else ""
    if not re.fullmatch(r"[0-9a-f]{32}", chat_hash or ""):
        continue
    chat = md5_to_chat.get(chat_hash)
    if chat is None:
        continue  # only care about chats present that day
    disp = chat_name.get(chat, chat_hash)
    rec_img = os.path.basename(d) == "Img" and "Rec" in parts
    for fn in files:
        base_md5, kind, low = None, "o", fn.lower()
        if low.endswith(".dat"):
            m = re.match(r"(?i)^([0-9a-f]{32})(?:[._]([thbc]))?\.dat$", fn)
            if m:
                base_md5, kind = m.group(1).lower(), m.group(2) or "o"
        elif rec_img:
            m = re.match(r"(?i)^(\d+)(_t|_h|_b|_c)?$", fn)
            if m:
                base_md5 = "rec%s-%s" % (parts[-2] if len(parts) >= 2 else "rec", m.group(1))
                kind = (m.group(2) or "o").lstrip("_")
        if base_md5 is None:
            continue
        scanned += 1
        p = os.path.join(d, fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        # #26（2026-09-15 修）：加"文件 size + mtime"缓存 —— 附件库基本不变，命中就跳过读文件/解密/格式检测，
        #   实测原来每天要扫+解密 7,106 个候选 ≈3 分钟，命中后只剩 stat。
        ck = (st.st_size, int(st.st_mtime))
        hit = cache.get(p)
        plain = None
        if hit and hit[0] == ck[0] and hit[1] == ck[1]:
            orig_md5, orig_len, fmt = hit[2], hit[3], hit[4]
            cache_hits += 1
        else:
            try:
                with open(p, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            plain = W.decrypt_v4(data, xor_key, aes_key)
            if plain is None:
                continue
            orig_md5, orig_len = hashlib.md5(plain).hexdigest(), len(plain)
            fmt = W.detect_format(plain)
            if fmt == "wxgf":
                cand = os.path.join(W.OUT_IMG, disp, "%s%s.jpg" % (base_md5, "_" + kind if kind != "o" else ""))
                if os.path.exists(cand):
                    with open(cand, "rb") as f:
                        plain = f.read()
                    fmt = "jpg"
                else:
                    conv = W.wxgf_to_jpg(plain)
                    if conv is not None:
                        plain, fmt = conv, "jpg"
            if fmt is None:
                continue
            cache[p] = [ck[0], ck[1], orig_md5, orig_len, fmt]
        ok += 1
        out_dir = os.path.join(W.OUT_IMG, disp)
        os.makedirs(out_dir, exist_ok=True)
        out_name = "%s%s.%s" % (base_md5, "_" + kind if kind != "o" else "", fmt)
        out_path = os.path.join(out_dir, out_name)
        if not os.path.exists(out_path) and plain is not None:
            with open(out_path, "wb") as f:
                f.write(plain)
        rel = os.path.relpath(out_path, W.OUT_IMG).replace("\\", "/")
        content_index.setdefault(orig_md5, []).append(rel)
        if kind == "t":
            thumb_index.setdefault((chat_hash, orig_len), []).append(rel)

print("scanned %d, resolved %d（其中缓存命中 %d、真解密 %d）, unique content %d（缓存 %d → %d）"
      % (scanned, ok, cache_hits, ok - cache_hits, len(content_index), cache0, len(cache)))
try:
    with open(CACHE_P, "w", encoding="utf-8") as f:
        json.dump(cache, f)
except OSError:
    pass

# ---- match ----
out = []
matched = 0
for r in img_msgs:
    files = content_index.get(r["md5"], [])
    anchor, conf = (None, 0.0)
    if files:
        anchor, conf, matched = "content_md5", 1.0, matched + 1
    else:
        ch = chat_md5.get(r["chat"], "")
        cand = thumb_index.get((ch, r["thumb_len"]), []) if r.get("thumb_len") else []
        if cand:
            files, anchor, conf = cand, "thumb_length", 0.8
            matched += 1
    rec = dict(r)
    rec["anchor"], rec["confidence"], rec["path"] = anchor, conf, files
    out.append(rec)
json.dump(out, open(OUTP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("matched %d/%d -> %s" % (matched, len(img_msgs), OUTP))
