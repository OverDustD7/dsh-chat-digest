# -*- coding: utf-8 -*-
"""find_attachments.py <YYYY-MM-DD> — 把当天"文件类消息"与**本机真实文件**对上，产出索引。

用法:
    python find_attachments.py 2026-09-17
    python find_attachments.py 2026-09-17 --root "WX_MSG_GLOB"

产出: output/days/<date>_files.json（形状对齐 <date>_images.json）

为什么重写（2026-09-20 全量审计 A01，P1）:
  旧版第 15 行把根写死成 `output/wx/msg/attach`（**本机不存在**），于是永远打印
  `attach_root exists: False` 然后**静默报 0**。用户 2026-09-12 起要求"顺便把文件看一看"，
  而这条线**近几轮全在报假阴性**（已核实 3 例：（某类 docx） / （某类 docx） /
  （某类附件））。"工具报 0"被当成了"确实没有"。

本版的判据（逐条对应 A01 的验收条件）:
  1. 根：`WX_ROOT` 环境变量 > `--root` > 自动探测 `WX_MSG_GLOB`。
     **根不存在 → 退出码 3**（与"扫了但没有"严格分开，不再静默报 0）。
  2. **两处都扫**：主位置 `msg\\file\\YYYY-MM\\<原名>`；次位置
     `msg\\attach\\<md5(会话)>\\YYYY-MM\\Rec\\<消息id>\\F\\0\\<原名>`。
  3. 每条索引项带**消息锚点**（jsonl 的 `msg_id`）、`found`、真实 `path`、`bytes`、
     `read_status`（unread/…）、`readable`（按扩展名判定可读范围）。
  4. `found: false` 一律**如实标注**，不猜 —— 用户 2026-09-20 明确"有一些文件被我移动了，
     那就是没有"。
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
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 工作区
TZ = dt.timezone(dt.timedelta(hours=8))
DAYS = os.path.join(HERE, "output", "days")
DEFAULT_WX_FAMILY = _os.path.dirname(WX_ACCOUNT_DIR)

#: 可提取正文的扩展名（读取范围，A01 验收要求"音视频明确读取范围"）
TEXT_EXT = {"pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "txt", "md", "csv", "json", "xml", "html"}
ARCHIVE_EXT = {"zip", "rar", "7z", "tar", "gz"}
AV_EXT = {"mp4", "mov", "avi", "mkv", "mp3", "m4a", "amr", "wav", "silk", "flac"}
IMG_EXT = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "heic"}


def pick_root(cli_root=None):
    """返回 (root, how)。root 是 `...\\<wxid>\\msg` 这一层。"""
    env = os.environ.get("WX_ROOT")
    if env:
        return env, "env:WX_ROOT"
    if cli_root:
        return cli_root, "cli:--root"
    # 自动探测：xwechat_files 下哪个账号目录里有 msg\file 或 msg\attach
    for cand in sorted(glob.glob(os.path.join(DEFAULT_WX_FAMILY, "*", "msg"))):
        if os.path.isdir(os.path.join(cand, "file")) or os.path.isdir(os.path.join(cand, "attach")):
            return cand, "auto:" + DEFAULT_WX_FAMILY
    return os.path.join(DEFAULT_WX_FAMILY, "*", "msg"), "auto-missing"


def norm_name(name):
    """归一化文件名：去掉微信**重复下载**加上的 `(1)`/`(2)` 后缀。

    为什么必须有这一步（2026-09-20 实测 09-17）：按精确名匹配时有 4 条报"本机没有"，
    实际全都在，只是落盘名是 `提问环节-顺序与站位(1).pdf` 这种。用户要的是"别把
    存在的东西说成不存在" —— 归一化后按 (词干, 扩展名) 再匹配一次。
    """
    stem, ext = os.path.splitext(name or "")
    stem = re.sub(r"\s*\(\d+\)$", "", stem)
    return (stem.strip().lower(), ext.lower())


def build_disk_index(root):
    """两处目录 → ({文件名: [条目]}, {(词干,扩展名): [条目]}, scanned)。"""
    idx = {}
    idx_norm = {}
    scanned = {"file": 0, "attach_rec": 0}

    def add(path, month, source):
        rec = {"path": path, "bytes": os.path.getsize(path), "mtime": os.path.getmtime(path),
               "month": month, "source": source}
        base = os.path.basename(path)
        idx.setdefault(base, []).append(rec)
        idx_norm.setdefault(norm_name(base), []).append(rec)

    fdir = os.path.join(root, "file")
    if os.path.isdir(fdir):
        for month in sorted(os.listdir(fdir)):
            md = os.path.join(fdir, month)
            if not os.path.isdir(md):
                continue
            for p in glob.glob(os.path.join(md, "**", "*"), recursive=True):
                if not os.path.isfile(p):
                    continue
                scanned["file"] += 1
                add(p, month, "file")
    adir = os.path.join(root, "attach")
    if os.path.isdir(adir):
        pat = os.path.join(adir, "*", "*", "Rec", "*", "F", "0", "*")
        for p in glob.glob(pat):
            if not os.path.isfile(p):
                continue
            scanned["attach_rec"] += 1
            rel = os.path.relpath(p, adir).split(os.sep)
            add(p, rel[1] if len(rel) > 1 else "", "attach_rec")
    return idx, idx_norm, scanned


def readable_of(ext):
    e = (ext or "").lower()
    if e in TEXT_EXT:
        return "text"          # 可提正文
    if e in IMG_EXT:
        return "image"         # 走图片线（vision_triage）
    if e in AV_EXT:
        return "av-unread"     # 音视频：本线不读，明确标"未读"
    if e in ARCHIVE_EXT:
        return "archive"       # 压缩包：需解包后按内部文件判
    return "unknown"


def parse_file_msg(raw):
    """判定并解析"文件消息"。返回 None 表示不是文件消息。

    **为什么不能只看 `attachid`/`<fileext>` 出现**（2026-09-20 实测 09-17 语料）：
    这两串字符在**引用消息（refermsg）**、拍一拍（type 62）、直播商品（type 57）、
    小程序卡片里都会出现 —— 只看它们会把 78 条普通聊天误判成"78 个文件"，
    然后报 70 条假"本机没有"。
    真实文件消息的形状是 `<appmsg><type>6</type>…<appattach><fileext>pdf</fileext>…`，
    且 `<title>` 就是文件名。判据：**fileext 非空 且 外层 type 为 6（或缺失但带 appattach）
    且 title 非空**。表情（type 8）虽有 fileext 但 title 为空 → 不算文件。
    """
    fe = re.search(r"<fileext>(.*?)</fileext>", raw, re.S)
    ext = (fe.group(1).strip().lower() if fe else "")
    if not ext:
        return None
    ty = re.search(r"<type>(\d+)</type>", raw)
    tyv = ty.group(1) if ty else ""
    if tyv and tyv != "6":
        return None
    tm = re.search(r"<title>(.*?)</title>", raw, re.S)
    title = (tm.group(1).strip() if tm else "")
    if not title:
        return None
    if not tyv and "<appattach>" not in raw:
        return None
    return {"title": title, "ext": ext, "type": tyv}


def attachment_messages(rows):
    """从当天 jsonl 里挑出**文件类消息**。"""
    out = []
    for r in rows:
        raw = r.get("raw") or ""
        if "<fileext>" not in raw:
            continue
        pm = parse_file_msg(raw)
        if not pm:
            continue

        def one(tag):
            m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), raw, re.S)
            return (m.group(1).strip() if m else "")

        out.append({"msg_id": r.get("msg_id") or "",
                    "ts": r.get("ts"), "chat": r.get("chat"), "chat_name": r.get("chat_name"),
                    "sender": r.get("sender"), "sender_name": r.get("sender_name"),
                    "title": pm["title"], "ext": pm["ext"], "appmsg_type": pm["type"],
                    "total_len": one("totallen"), "aeskey": one("aeskey")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--root", default=None)
    ap.add_argument("--jsonl", default=None, help="默认 output/days/<date>.jsonl")
    a = ap.parse_args()

    root, how = pick_root(a.root)
    if not os.path.isdir(root):
        print("[x] 微信附件根不存在：%s（来源 %s）" % (root, how))
        print("    这不是'当天没有文件'，而是**根本没查到**——所以退出码 3，不当成功。")
        print("    指定方式：环境变量 WX_ROOT，或 --root \"…\\<wxid>\\msg\"")
        return 3

    jsonl = a.jsonl or os.path.join(DAYS, "%s.jsonl" % a.date)
    if not os.path.exists(jsonl):
        print("[x] 当天消息不存在（先跑 extract_day.py）：%s" % jsonl)
        return 4
    rows = []
    with open(jsonl, encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except ValueError:
                    pass

    idx, idx_norm, scanned = build_disk_index(root)
    msgs = attachment_messages(rows)
    entries = []
    for m in msgs:
        title = m["title"] or ""
        hits = idx.get(title) or []
        matched = "exact"
        if not hits:
            low = title.lower()
            for name, lst in idx.items():
                if name.lower() == low:
                    hits = lst
                    matched = "case-insensitive"
                    break
        if not hits:
            hits = idx_norm.get(norm_name(title)) or []
            if hits:
                matched = "normalized(去(1)/(2)后缀)"
        e = dict(m)
        e["found"] = bool(hits)
        e["readable"] = readable_of(m["ext"])
        e["read_status"] = "unread"
        e["match"] = matched if hits else None
        if hits:
            h = sorted(hits, key=lambda x: -x["mtime"])[0]
            e.update({"path": h["path"], "bytes": h["bytes"], "month": h["month"],
                      "found_source": h["source"], "copies": len(hits)})
        else:
            e.update({"path": None, "bytes": None, "month": None, "found_source": None, "copies": 0})
        entries.append(e)

    out = {"date": a.date, "at": int(dt.datetime.now(TZ).timestamp()),
           "root": root, "root_how": how, "root_ok": True,
           "scanned": scanned, "disk_files": sum(len(v) for v in idx.values()),
           "summary": {"referenced": len(entries),
                       "found": sum(1 for e in entries if e["found"]),
                       "missing": sum(1 for e in entries if not e["found"])},
           "files": entries}
    p = os.path.join(DAYS, "%s_files.json" % a.date)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("root=%s（%s）" % (root, how))
    print("磁盘：file 目录 %d 个文件 ｜ attach Rec %d 个" % (scanned["file"], scanned["attach_rec"]))
    print("当天文件类消息 %d 条 → 命中 %d ／ 本机没有 %d"
          % (len(entries), out["summary"]["found"], out["summary"]["missing"]))
    for e in entries:
        if not e["found"]:
            print("   缺：%s (%s, %s B)" % (e["title"], e["ext"], e["total_len"] or "?"))
    print("->", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
