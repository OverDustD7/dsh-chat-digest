# -*- coding: utf-8 -*-
"""
wx_images.py : WeChat 4.x image extraction & message mapping (v2).

Pipeline:
  1. Resolve image key (kvcomm code + wxid -> AES-16 + XOR), verified against
     a local *_t.dat V2 template (AES-ECB first block -> image magic).
  2. Scan msg\\attach\\<chatmd5>\\YYYY-MM\\**\\*.dat, decrypt V4 dat ->
     plain JPEG/PNG/WebP/GIF, write to output\\window\\images\\<会话名>\\
     (all variants kept; no overwrite across chats).
  3. Match: decrypted content md5 == message XML md5 attr -> index.json
     (chat / chat_name / ts / sender / md5 / path).
  4. Unmatched in-window image messages -> pending.txt: open those chats in
     the WeChat client so WeChat downloads the originals, then re-run.

Usage: python wx_images.py
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
import hashlib
import json
import os
import re
import struct
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 工作区
OUT_IMG = os.path.join(HERE, "output", "window", "images")
WX_ROOT = r"WX_ACCOUNT_DIR"
WXID = SELF_WXID
KVCOMM_GUESS = [
    r"WX_KEY_DIR",
]
MSG_JSONL = os.path.join(HERE, "output", "window", "wx_raw.jsonl")

KVCOMM_RE = re.compile(r"^key_(\d+)_.+\.statistic$", re.I)
KVCOMM_ANY = re.compile(r"^key_(\d+)_", re.I)
KEY_CACHE_P = os.path.join(HERE, "output", "window", "_image_key.json")
MD5_RE = re.compile(r'md5="([0-9a-f]{32})"', re.I)
V2_MAGIC = bytes((0x07, 0x08, 0x56, 0x32, 0x08, 0x07))
IMPORTANT_DIRS = ("Img", "thumb", "emoticon", "image")

#: 最近一次 resolve_key 失败的原因（给调用方原样回报用）。空串＝没失败过。
LAST_KEY_REASON = ""

#: 最近一次 resolve_key 成功时用的是哪一级候选（cached / kvcomm / historical）。
LAST_KEY_SOURCE = ""

#: 本机历史上**验证通过**过的 code（不随登录态变化，但一律要再验一次才采用）。
#: 4074513727：2026-09-11 首次打通图片链路时验证（`docs\README.md` 第 90/107 行），
#: 2026-09-15 复验仍然能解开当天最新与 07 月最早的 `_t.dat`。
#: 为什么需要这一级：微信未登录时 kvcomm 里只剩 `key_0_<版本号>_…` 这种**占位**
#: （code 段是 0，`4065598732` 其实是 idkey_clientversion），此时纯靠扫 kvcomm
#: 会得出"解不出密钥"的假结论，而图片线其实完全能跑。
HISTORICAL_CODES = (4074513727,)


def find_kvcomm():
    for p in KVCOMM_GUESS:
        if os.path.isdir(p):
            return p
    base = os.path.join(os.environ.get("APPDATA", ""), "Tencent", "xwechat")
    for d, dirs, files in os.walk(base):
        if os.path.basename(d) == "kvcomm":
            return d
    return None


def wx_login_state(kvcomm=None):
    """微信在线/可用状态（**2026-09-15 晚修正过一次，别再用单信号**）。

    事实（同一天实测到的两段对照，非常关键）：
      · 19:32 未登录：kvcomm 只有 `key_0_4065598732_1_<epoch>_…statistic`
        —— **code 段是 0（占位）**，`4065598732` 是 `idkey_clientversion`（客户端版本号，不是密钥）。
      · 20:02 已登录：出现 `4074513727_4065598732_1_<epoch>_…`、
        `key_4074513727_4065598732_1_…_ready.statistic` —— **code 段是真实 code**，
        同时附件库活动从 15:44 恢复到 19:52。
      · **但 `config.ini` 的 `last_uin=` 在"已登录"时依然是空的**（20:02 那次读到的就是空）。
      ⇒ **`last_uin` 不是登录判据**。第一版我只看它，是从一次观察下的结论，已被上面这个反例证伪。

    现在的判据（多信号，且以"图片线能不能跑"为准）：
      `codeNegotiated` = kvcomm 的 `key*` 文件名里**存在非 0 的 code 段** ← 主信号（客户端已协商出密钥）
      `lastUin`       = 参考值，**空不代表未登录**（保留只为排查）
      `loggedIn`      = `bool(last_uin) or codeNegotiated`；两者都判不出来才是 None
    """
    kvcomm = kvcomm or find_kvcomm()
    info = {"loggedIn": None, "lastUin": "", "idkeyClientVersion": "", "kvClientVersion": "",
            "source": "", "codeNegotiated": False, "codes": []}
    if not kvcomm:
        return info
    info["codes"] = enumerate_codes(kvcomm)
    info["codeNegotiated"] = any(c for c in info["codes"])
    p = os.path.join(kvcomm, "config.ini")
    if os.path.isfile(p):
        info["source"] = p
        try:
            with open(p, "rb") as f:
                txt = f.read().decode("utf-8", "replace")
        except OSError:
            txt = ""
        for line in txt.splitlines():
            k, _, v = line.partition("=")
            k, v = k.strip().lower(), v.strip()
            if k == "last_uin":
                info["lastUin"] = v
            elif k == "idkey_clientversion":
                info["idkeyClientVersion"] = v
            elif k == "kv_clientversion":
                info["kvClientVersion"] = v
    info["loggedIn"] = bool(info["lastUin"]) or info["codeNegotiated"]
    return info


def enumerate_codes(kvcomm):
    """候选 code 列表 —— **只产候选，能不能用交给 resolve_key 对真实 *_t.dat 验证**。

    2026-09-15 为什么改：微信改了 kvcomm 命名。旧格式 `key_4074513727_…statistic`
    （正则吃第一段数字就对），新格式 `key_0_4065598732_1_1789471930_24218_3600_input.statistic`
    —— 第一段是 `0`（未登录时的 code 占位），`4065598732` 是 `idkey_clientversion`。
    所以不再只吃第一段：把 `key*` / `*.statistic` / `*.monitor` 文件里**每个 >=6 位的数字段**都当候选，
    由 resolve_key 逐个试解验证（候选里有版本号也无所谓，验不过就被丢掉）。
    `0` 直接排除（占位，永远不是真 code）。
    """
    cands, primary = set(), []
    try:
        names = os.listdir(kvcomm)
    except OSError:
        return []
    for fn in names:
        m = KVCOMM_ANY.match(fn)
        if m:
            primary.append(int(m.group(1)))
        if fn.lower().startswith("key") or fn.lower().endswith((".statistic", ".monitor")):
            cands.update(int(g) for g in re.findall(r"\d{6,}", fn))
    lead = [c for c in sorted(set(primary)) if c]
    return lead + sorted(cands - set(lead) - {0})


def _newest_templates(attach, limit=8):
    """取**最新**的 limit 个 `*_t.dat` 的前 16 字节当验证模板。

    2026-09-15 踩过（假阴性根因）：原来 os.walk 撞上的第一个模板是 **2025-08** 的旧图。
    微信轮换过密钥 → 用旧图当模板，会让**完全有效的当前 key** 验证失败、误报"解不出密钥"。
    验证必须用最新图片。
    """
    found = []
    for d, _dirs, files in os.walk(attach):
        for fn in files:
            if not fn.lower().endswith("_t.dat"):
                continue
            p = os.path.join(d, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size >= 0x0F + 16:
                found.append((st.st_mtime, p))
        if len(found) > 40000:
            break
    found.sort(reverse=True)
    out = []
    for mt, p in found[: limit * 6]:
        try:
            with open(p, "rb") as f:
                blob = f.read(0x0F + 16)
        except OSError:
            continue
        if len(blob) == 0x0F + 16 and blob.startswith(V2_MAGIC):
            out.append((mt, p, blob[0x0F:]))
        if len(out) >= limit:
            break
    return out


def _verify_code(code, template):
    """候选 code 试解模板首块；能解出图片 magic 才返回 (xor_key, aes_key)。"""
    from Crypto.Cipher import AES

    xor_key, aes_key = derive_keys(code, WXID)
    try:
        block = AES.new(aes_key.encode("ascii"), AES.MODE_ECB).decrypt(template)
    except Exception:  # noqa: BLE001
        return None
    return (xor_key, aes_key) if detect_format(block) else None


def load_cached_key():
    """读上次验证通过的 code（**用之前仍会再验一次**，缓存不代替验证）。"""
    try:
        with open(KEY_CACHE_P, encoding="utf-8") as f:
            j = json.load(f)
        code = int(j.get("code") or 0)
        if code and j.get("wxid") == WXID:
            return code, j
    except (OSError, ValueError, TypeError):
        pass
    return None, None


def save_cached_key(code, evidence):
    """缓存"验证通过"的 code —— 兜底场景：kvcomm 文件暂时不在/改名了，图片线还能跑。"""
    try:
        os.makedirs(os.path.dirname(KEY_CACHE_P), exist_ok=True)
        with open(KEY_CACHE_P, "w", encoding="utf-8") as f:
            json.dump({"code": code, "wxid": WXID, "xor": code & 0xFF,
                       "verified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "verified_against": evidence},
                      f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def derive_keys(code, wxid):
    digest = hashlib.md5(f"{code}{wxid}".encode("utf-8")).hexdigest()
    return code & 0xFF, digest[:16]


def detect_format(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith((b"gif87a", b"gif89a")):
        return "gif"
    if data.startswith((b"wxgf", b"WXGF")):
        return "wxgf"
    return None


def wxgf_to_jpg(blob):
    """Decode WeChat .wxgf (wrapped HEVC image) to JPEG bytes with PyAV (pure Python)."""
    import io as _io
    i = blob.find(b"\x00\x00\x00\x01")
    if i < 0:
        i = blob.find(b"\x00\x00\x01")
    if i < 0:
        return None
    try:
        import av
        container = av.open(_io.BytesIO(blob[i:]), format="hevc")
        for frame in container.decode(video=0):
            buf = _io.BytesIO()
            frame.to_image().convert("RGB").save(buf, format="JPEG", quality=92)
            return buf.getvalue()
    except Exception:
        return None
    return None


def decrypt_v4(data, xor_key, aes_key):
    from Crypto.Cipher import AES
    from Crypto.Util import Padding

    header, rest = data[:0x0F], data[0x0F:]
    if len(header) != 15 or len(rest) < 16:
        return None
    sig, aes_size, xor_size = struct.unpack("<6sLLx", header)
    if sig != V2_MAGIC:
        return None
    aes_size += AES.block_size - aes_size % AES.block_size
    if aes_size > len(rest) or xor_size > len(rest):
        return None
    aes_data = rest[:aes_size]
    cipher = AES.new(aes_key[:16].encode("ascii"), AES.MODE_ECB)
    try:
        decrypted = Padding.unpad(cipher.decrypt(aes_data), AES.block_size)
    except Exception:
        return None
    if xor_size > 0:
        raw_data = rest[aes_size:-xor_size]
        xored = bytes(b ^ xor_key for b in rest[-xor_size:])
    else:
        raw_data = rest[aes_size:]
        xored = b""
    return decrypted + raw_data + xored


def resolve_key(kvcomm, allow_cache=True):
    """解出图片密钥；返回 (xor_key, aes_key) 或 None。

    候选来源三级（**每一级都只是候选，能不能用一律以"能否解开最新 _t.dat"为准**）：
      ① 缓存 `output\\window\\_image_key.json`（上次验证通过的）
      ② kvcomm 现存的 `key*` 文件里的候选 code
      ③ `HISTORICAL_CODES`（本机历史上验证过的 code —— 微信未登录时 kvcomm 只剩占位 key，
         而**本机 code 不随登录态变化**；2026-09-15 实测 09-11 记录的 code 仍能解开当天的图）
    失败原因写在模块级 `LAST_KEY_REASON` 里，调用方原样回报。
    """
    global LAST_KEY_REASON, LAST_KEY_SOURCE
    LAST_KEY_REASON = ""
    LAST_KEY_SOURCE = ""

    attach = os.path.join(WX_ROOT, "msg", "attach")
    templates = _newest_templates(attach)
    if not templates:
        LAST_KEY_REASON = ("找不到可用于验证的 *_t.dat 模板（查 WX_ROOT=%s 是否正确、本机是否还有微信图片）"
                           % WX_ROOT)
        print("[key] " + LAST_KEY_REASON)
        return None

    login = wx_login_state(kvcomm)
    kv_codes = enumerate_codes(kvcomm)

    tried = set()
    plans = []
    if allow_cache:
        code, _meta = load_cached_key()
        if code:
            plans.append(("cached", code))
    plans += [("kvcomm", c) for c in kv_codes]
    plans += [("historical", c) for c in HISTORICAL_CODES]

    print("[key] 候选：cached=%s kvcomm=%s historical=%s | 已协商密钥: %s（last_uin=%r，**空不代表未登录**）"
          % ([c for w, c in plans if w == "cached"], kv_codes, list(HISTORICAL_CODES),
             login["codeNegotiated"], login["lastUin"]))

    for where, code in plans:
        if code in tried:
            continue
        tried.add(code)
        for _mt, p, tpl in templates[:5]:
            hit = _verify_code(code, tpl)
            if hit:
                print("[key] VERIFIED (%s): code=%s xor=0x%02X aes=%s | 模板=%s"
                      % (where, code, hit[0], hit[1], os.path.basename(p)))
                LAST_KEY_SOURCE = where
                save_cached_key(code, os.path.basename(p))
                return hit

    if login["loggedIn"] is False:
        LAST_KEY_REASON = ("微信客户端没协商出密钥（kvcomm 里只有 code=0 的占位文件、config.ini 的 last_uin 也空）→ "
                           "登录微信后重跑本步；注意「未登录」这个判断要看 kvcomm 的 code 段，"
                           "**不能只看 last_uin**（已登录时它也可能是空）")
    elif login["loggedIn"] is None:
        LAST_KEY_REASON = ("读不到微信状态（kvcomm 目录/config.ini 都不在）且候选 %s 全部验证失败 → "
                           "确认微信是否在运行/登录，或 kvcomm 布局是否又变了" % (sorted(tried),))
    else:
        LAST_KEY_REASON = ("已登录但候选 %s 全部验证失败（注意：kvcomm 里那个大数是 idkey_clientversion、"
                           "不是密钥）→ kvcomm 布局可能又变了，需人工核对" % (sorted(tried),))
    print("[key] " + LAST_KEY_REASON)
    return None


def load_messages():
    """Return (chat_md5_map, chat_name_map, image_msgs). Reads the single wx_raw.jsonl."""
    chat_md5 = {}   # chat -> md5(chat)
    chat_name = {}  # chat -> display name
    img_msgs = []   # list of image messages (all extracted windows)
    # 只认单一权威输入：原来这里是 glob.glob("wx_raw*.jsonl")，多出一个同名文件就会把
    # 图片索引从几十条撑到几千条（KNOWN_ISSUES #2 声称已修，2026-09-14 审计发现仍是通配）。
    paths = [MSG_JSONL]
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                chat, name = j.get("chat", ""), j.get("chat_name", "")
                if chat:
                    chat_md5.setdefault(chat, hashlib.md5(chat.encode("utf-8")).hexdigest())
                    chat_name.setdefault(chat, name or chat)
                blob = (j.get("raw") or "") or (j.get("text") or "")
                m = re.findall(r'<img\b[^>]*?\bmd5="([0-9a-f]{32})"', blob, re.I | re.S) or MD5_RE.findall(blob)
                if m:
                    tl = re.search(r'cdnthumblength="(\d+)"', blob, re.I)
                    tw = re.search(r'cdnthumbwidth="(\d+)"', blob, re.I)
                    th = re.search(r'cdnthumbheight="(\d+)"', blob, re.I)
                    img_msgs.append(
                        {
                            "chat": chat,
                            "chat_name": chat_name.get(chat, chat),
                            "ts": j.get("ts"),
                            "sender": j.get("sender_name", ""),
                            "md5": m[0].lower(),
                            "thumb_len": int(tl.group(1)) if tl else None,
                            "thumb_w": int(tw.group(1)) if tw else None,
                            "thumb_h": int(th.group(1)) if th else None,
                        }
                    )
    md5_to_chat = {}
    for chat, h in chat_md5.items():
        md5_to_chat[h] = chat
    return chat_md5, chat_name, md5_to_chat, img_msgs


def main():
    kvcomm = find_kvcomm()
    if not kvcomm:
        print("[ERR] kvcomm not found")
        return
    keys = resolve_key(kvcomm)
    if not keys:
        print("[ERR] image key unresolved: %s" % (LAST_KEY_REASON or "未知原因"))
        return
    xor_key, aes_key = keys

    chat_md5, chat_name, md5_to_chat, img_msgs = load_messages()
    print("[map] chats in window:", len(chat_md5), "| image msgs:", len(img_msgs))

    wanted = {}
    for r in img_msgs:
        wanted.setdefault(r["md5"], []).append(r)

    attach = os.path.join(WX_ROOT, "msg", "attach")
    os.makedirs(OUT_IMG, exist_ok=True)

    content_index = {}  # content md5 -> [relpath]
    thumb_index = {}    # (chat_hash, plain_len) -> [relpath]  (thumbnail byte-length anchor)
    files_seen = 0
    files_ok = 0
    for d, dirs, files in os.walk(attach):
        parts = d.replace(attach, "").lstrip("\\/").split("\\")
        # parts: [chatmd5, YYYY-MM, ...]
        chat_hash = parts[0] if parts else ""
        if not re.fullmatch(r"[0-9a-f]{32}", chat_hash or ""):
            continue
        chat = md5_to_chat.get(chat_hash, chat_hash)
        disp = chat_name.get(chat, chat) or chat_hash
        is_rec_img_dir = os.path.basename(d) == "Img" and "Rec" in parts
        for fn in files:
            base_md5 = None
            kind = "o"
            low = fn.lower()
            if low.endswith(".dat"):
                m = re.match(r"(?i)^([0-9a-f]{32})(?:[._]([thbc]))?\.dat$", fn)
                if m:
                    base_md5 = m.group(1).lower()
                    kind = m.group(2) or "o"
            elif is_rec_img_dir:
                # Rec\<msgid>\Img\<N>[_t] : same V2 container, no extension
                m = re.match(r"(?i)^(\d+)(_t|_h|_b|_c)?$", fn)
                if m:
                    rec_id = parts[-2] if len(parts) >= 2 else "rec"
                    base_md5 = "rec%s-%s" % (rec_id, m.group(1))
                    kind = (m.group(2) or "o").lstrip("_")
            if base_md5 is None:
                continue
            p = os.path.join(d, fn)
            files_seen += 1
            try:
                with open(p, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            plain = decrypt_v4(data, xor_key, aes_key)
            if plain is None:
                continue
            # keep the ORIGINAL bytes' md5/length for matching against the message XML
            # (a wxgf image's own container md5 is what the message declares; transcoding
            #  to jpg would otherwise break that match)
            orig_md5 = hashlib.md5(plain).hexdigest()
            orig_len = len(plain)
            fmt = detect_format(plain)
            if fmt == "wxgf":
                # reuse an already-transcoded jpg instead of re-decoding HEVC (slow)
                cand = os.path.join(OUT_IMG, disp, "%s%s.jpg" % (base_md5, "_" + kind if kind != "o" else ""))
                if os.path.exists(cand):
                    with open(cand, "rb") as f:
                        plain = f.read()
                    fmt = "jpg"
                else:
                    conv = wxgf_to_jpg(plain)
                    if conv is not None:
                        plain, fmt = conv, "jpg"
            if fmt is None:
                continue
            files_ok += 1
            out_dir = os.path.join(OUT_IMG, disp)
            os.makedirs(out_dir, exist_ok=True)
            out_name = f"{base_md5}{'_' + kind if kind != 'o' else ''}.{fmt}"
            out_path = os.path.join(out_dir, out_name)
            if not os.path.exists(out_path):
                with open(out_path, "wb") as f:
                    f.write(plain)
            cm = orig_md5
            rel = os.path.relpath(out_path, OUT_IMG).replace("\\", "/")
            content_index.setdefault(cm, []).append(rel)
            if kind == "t":
                thumb_index.setdefault((chat_hash, orig_len), []).append(rel)

    # index.json: every in-window image message, with anchor + confidence
    index = []
    matched = 0
    matched_thumb = 0
    pending = []
    done = set()
    for r in sorted(img_msgs, key=lambda x: (x["chat"], x["ts"] or 0)):
        rec = dict(r)
        files = content_index.get(r["md5"], [])
        if files:
            rec["anchor"] = "content_md5"
            rec["confidence"] = 1.0
            matched += 1
        else:
            ch = hashlib.md5((r["chat"] or "").encode("utf-8")).hexdigest()
            tlen = r.get("thumb_len")
            cand = thumb_index.get((ch, tlen), []) if tlen else []
            if cand:
                files = cand
                rec["anchor"] = "thumb_length"
                rec["confidence"] = 0.8
                rec["note"] = "缩略图按字节数(%s)与消息 cdnthumblength 吻合；原图未落盘" % tlen
                matched += 1
                matched_thumb += 1
            else:
                rec["anchor"] = None
                rec["confidence"] = 0.0
        rec["path"] = files
        index.append(rec)
        if not files and (r["md5"], r["chat"], r["ts"]) not in done:
            done.add((r["md5"], r["chat"], r["ts"]))
            pending.append(rec)

    with open(os.path.join(OUT_IMG, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)

    with open(os.path.join(OUT_IMG, "pending.txt"), "w", encoding="utf-8") as f:
        f.write(
            "窗口内图片消息且本地图库中未找到匹配文件。\n"
            "成因：微信未下载该图（原图+缩略图都没有）——历史消息不自动补下载；新消息在阈值内会自动落盘。\n"
            "锚定优先级：① 内容 md5 == 消息 XML md5（精确）② 缩略图解密字节数 == 消息 cdnthumblength（强，标 confidence 0.8）。\n"
            "处理：保持微信后台运行 + 「自动下载小于 __MB 的文件」阈值调大（用户已设 1000MB）；\n"
            "历史缺图按「宁缺毋滥」标注缺失，不猜测内容。\n\n"
        )
        for p in pending:
            f.write("%s | ts=%s | %s | md5=%s\n" % (p["chat_name"], p["ts"], p["sender"], p["md5"]))

    print("[done] dat scanned: %d, decrypted: %d, unique content: %d" % (files_seen, files_ok, len(content_index)))
    print("[done] image msgs: %d, matched: %d (md5=%d, thumb_len=%d), pending: %d"
          % (len(img_msgs), matched, matched - matched_thumb, matched_thumb, len(pending)))
    print("[done] images ->", OUT_IMG)


if __name__ == "__main__":
    main()