# -*- coding: utf-8 -*-
r"""day_tail.py — 当天某个时刻之后的**增量视图**（给"上次采集之后才算新的"这种轮次用）。

为什么需要（2026-09-13 自动到点那轮）：`daily_prep.py` 出的是**整天**的 timeline/brief/articles，
而那一轮的指令是"上次采集 21:26，这之后的消息才算新的" → 提炼者需要一份**只含增量**的视图，
否则它会在整天 4700 行里挑，很容易把已经报过的条目重报一遍。

用法: python tools\day_tail.py <YYYY-MM-DD> <from_epoch> [to_epoch]
产出: output/days/<date>_tail_<HHMM>.md
"""
import datetime as dt
import io
import json
import os
import re
import sys
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(HERE, "tools")
sys.path.insert(0, TOOLS)
import day_timeline as TL  # noqa: E402  复用它的清洗/去噪规则，保证与整天视图同口径

TZ = dt.timezone(dt.timedelta(hours=8))
URL_RE = re.compile(r"https?://[^\s\"'<>）)]+")
IMG_TYPES = ("图片", "照片")


def main(argv):
    date = argv[0]
    from_ts = int(argv[1])
    to_ts = int(argv[2]) if len(argv) > 2 else 1 << 40
    src = os.path.join(HERE, "output", "days", "%s.jsonl" % date)
    rows, dropped = [], 0
    for line in io.open(src, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        j = json.loads(line)
        ts = int(j.get("ts") or 0)
        if not (from_ts <= ts <= to_ts):
            continue
        raw = "%s %s" % (j.get("text") or "", j.get("raw") or "")
        urls = [u.rstrip(".,;") for u in URL_RE.findall(raw)]
        t = TL.clean(j.get("text")) or ""
        if not t or TL.XML_MEDIA.search(t):
            m = TL.TITLE_RE.search(raw)
            if m:
                t = "[卡片] " + re.sub(r"&amp;", "&", m.group(1).strip())[:160]
            else:
                t = ""
        if t:
            t = re.sub(r"\s+", " ", t).strip()
            if any(p.search(t) for p in TL.DROP):
                t = ""
        typ = j.get("type") or ""
        media = ""
        if typ in IMG_TYPES:
            media = "[%s]" % typ
        elif not t and typ not in ("文本",):
            media = "[%s]" % typ
        if not t and not media:
            dropped += 1
            continue
        rows.append({"ts": ts, "chat": (j.get("chat_name") or j.get("chat") or "?").strip(),
                     "who": (j.get("sender_name") or j.get("sender") or "").strip(),
                     "text": t[:400], "urls": urls[:4], "media": media, "type": typ})
    rows.sort(key=lambda r: r["ts"])

    # 图片清单（本地已落盘的）
    imgs = []
    ip = os.path.join(HERE, "output", "days", "%s_images.json" % date)
    if os.path.exists(ip):
        try:
            for it in json.load(io.open(ip, encoding="utf-8")):
                if from_ts <= int(it.get("ts") or 0) <= to_ts:
                    imgs.append(it)
        except Exception as e:  # noqa: BLE001
            print("images.json 读取失败:", e)
    imgs.sort(key=lambda x: int(x.get("ts") or 0))

    per_chat = collections.Counter(r["chat"] for r in rows)
    stamp = dt.datetime.fromtimestamp(from_ts, TZ).strftime("%H%M")
    out = os.path.join(HERE, "output", "days", "%s_tail_%s.md" % (date, stamp))
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("# %s 增量视图（%s 之后）\n\n" % (date, dt.datetime.fromtimestamp(from_ts, TZ).strftime("%m-%d %H:%M")))
        f.write("> 覆盖 %s ~ %s ｜ 消息行 %d ｜ 图片 %d（丢弃空/表情 %d）\n" % (
            dt.datetime.fromtimestamp(from_ts, TZ).strftime("%H:%M"),
            dt.datetime.fromtimestamp(min(to_ts, int(rows[-1]["ts"]) if rows else from_ts), TZ).strftime("%H:%M"),
            len(rows), len(imgs), dropped))
        f.write("> 行式 `- HH:MM [群] 人: 内容`；`⟨…⟩`＝该条里出现的链接；`[图片/文件]`＝非文本消息\n\n")
        f.write("## 各会话条数（先看谁在说话）\n\n")
        for c, n in per_chat.most_common():
            f.write("- %s：%d\n" % (c, n))
        f.write("\n## 增量时间轴\n\n")
        cur = None
        for r in rows:
            d = dt.datetime.fromtimestamp(r["ts"], TZ)
            if d.strftime("%H") != cur:
                cur = d.strftime("%H")
                f.write("\n### %s 时\n\n" % d.strftime("%H"))
            line = "- %s [%s] %s: %s" % (d.strftime("%H:%M"), r["chat"][:18], r["who"][:12], r["text"])
            if r["media"]:
                line += " %s" % r["media"]
            if r["urls"]:
                line += " ⟨%s⟩" % " ; ".join(r["urls"])
            f.write(line + "\n")
        f.write("\n## 增量图片（本地已落盘，可 read_image 看）\n\n")
        for it in imgs:
            d = dt.datetime.fromtimestamp(int(it.get("ts") or 0), TZ).strftime("%H:%M")
            p = (it.get("path") or [""])[0]
            f.write("- %s [%s] %s ｜ %s\n" % (d, it.get("chat_name", "?")[:18], it.get("sender", "")[:10],
                                              os.path.join(HERE, "output", "window", "images", p) if p else ""))
    print("wrote %s ｜ rows=%d imgs=%d ｜ %s" % (out, len(rows), len(imgs), dict(per_chat.most_common(8))))

    # 降噪版：把窗口内条数 >= NOISY_N 的"水群"整段挪出去（只挪，不丢——名单与条数写在文件头）
    NOISY_N = 200
    noisy = {c for c, n in per_chat.items() if n >= NOISY_N}
    if noisy:
        out2 = os.path.join(HERE, "output", "days", "%s_tail_%s_signal.md" % (date, stamp))
        kept = [r for r in rows if r["chat"] not in noisy]
        with io.open(out2, "w", encoding="utf-8", newline="\n") as f:
            f.write("# %s 增量视图·降噪版（%s 之后；已移出大水群）\n\n" % (
                date, dt.datetime.fromtimestamp(from_ts, TZ).strftime("%m-%d %H:%M")))
            f.write("> 本文件 %d 行；**被移出的水群（条数 >= %d）**：%s\n" % (
                len(kept), NOISY_N, "、".join("%s(%d)" % (c, n) for c, n in per_chat.most_common() if c in noisy)))
            f.write("> 那些群的消息仍在 `%s`（别默认它们没价值，扫一眼标题类内容）\n\n" % os.path.basename(out))
            cur = None
            for r in kept:
                d = dt.datetime.fromtimestamp(r["ts"], TZ)
                if d.strftime("%H") != cur:
                    cur = d.strftime("%H")
                    f.write("\n### %s 时\n\n" % d.strftime("%H"))
                line = "- %s [%s] %s: %s" % (d.strftime("%H:%M"), r["chat"][:18], r["who"][:12], r["text"])
                if r["media"]:
                    line += " %s" % r["media"]
                if r["urls"]:
                    line += " ⟨%s⟩" % " ; ".join(r["urls"])
                f.write(line + "\n")
            f.write("\n## 增量图片（本地已落盘）\n\n")
            for it in imgs:
                if (it.get("chat_name") or "") in noisy:
                    continue
                d = dt.datetime.fromtimestamp(int(it.get("ts") or 0), TZ).strftime("%H:%M")
                p = (it.get("path") or [""])[0]
                f.write("- %s [%s] %s ｜ %s\n" % (d, it.get("chat_name", "?")[:18], it.get("sender", "")[:10],
                                                  os.path.join(HERE, "output", "window", "images", p) if p else ""))
        print("wrote %s ｜ rows=%d（移出水群 %s）" % (out2, len(kept), sorted(noisy)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
