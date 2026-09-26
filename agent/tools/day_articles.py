# -*- coding: utf-8 -*-
"""day_articles.py — 列出**当天所有文章/卡片**，并给出"本地已有正文"的路径（提炼必查）。

为什么需要它（2026-09-13 用户指出"新加的算力券那条还是没有读文章提取关键信息"）：
`output\\window\\articles\\` 里**早就有**抓好的正文（如 `g3_suanliquan2.md`，6012 字节，含线下联系人
"文章里的线下联系人"），但提炼时只读了群消息、**没人去查这个缓存目录** → 文章里的关键信息整批丢失。
本脚本把"当天出现的文章卡片"与"本地正文"对上，让提炼方一眼看到"这篇有正文 / 这篇没有"。

用法:
    python tools\\day_articles.py 2026-09-13              # 只列（不联网）
    python tools\\day_articles.py 2026-09-13 --fetch      # 对本地缺正文的尝试抓取（会遇 captcha，如实记录）
产出: output/days/<date>_articles.md
"""
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = dt.timezone(dt.timedelta(hours=8))
ART = os.path.join(HERE, "output", "window", "articles")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
URL_RE = re.compile(r"<url>(.*?)</url>", re.S)
ANY_URL = re.compile(r"https?://mp\.weixin\.qq\.com/[^\s\"'<>\\)）】]+")
SRC_LINE = re.compile(r"^- 来源：(\S+)", re.M)
# 引用消息（refermsg）里也带 <title>/<url> —— 不剥掉就会把"拍了拍""颇像一位故人"当成文章卡片
REFER = re.compile(r"<refermsg>.*?</refermsg>", re.S)
# 无链接卡片里，标题含这些词才可能是"要填的表/要参加的活动"
CARDKW = r"统计|问卷|报名|登记|接龙|投票|表|培训|直播|团购|讲座|课程|活动|申请|拍卖|开学"


def urlkey(u):
    """把微信文章 URL 归一成可比的键：优先 (__biz, mid, idx, sn)，否则 /s/<id> 段。"""
    u = u.replace("&amp;", "&").strip()
    biz = re.search(r"__biz=([^&]+)", u)
    mid = re.search(r"mid=(\d+)", u)
    idx = re.search(r"idx=(\d+)", u)
    sn = re.search(r"sn=([0-9a-fA-F]+)", u)
    if biz and mid and idx and sn:
        return "b%s_m%s_i%s_s%s" % (biz.group(1), mid.group(1), idx.group(1), sn.group(1))
    m = re.search(r"/s/([A-Za-z0-9_-]{10,})", u)
    return "s_" + m.group(1) if m else u[:80]


def local_index():
    """本地已抓正文：键 -> (文件名, 字符数)。"""
    idx = {}
    if not os.path.isdir(ART):
        return idx
    for name in sorted(os.listdir(ART)):
        if not name.endswith(".md"):
            continue
        p = os.path.join(ART, name)
        try:
            t = io.open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        m = SRC_LINE.search(t)
        if m:
            idx.setdefault(urlkey(m.group(1)), (name, len(t)))
    return idx


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_fetch = "--fetch" in sys.argv
    DATE = args[0] if args else dt.datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        __import__("datetime").datetime.strptime(DATE, "%Y-%m-%d")
    except Exception:
        raise SystemExit("day_articles.py: 日期参数必须是 YYYY-MM-DD，收到 %r" % (DATE,))
    src = os.path.join(HERE, "output", "days", "%s.jsonl" % DATE)
    if not os.path.exists(src):
        print("缺 %s" % src)
        return 1

    cards = []          # 带标题 + 有链接的卡片（真文章）
    nolink = []         # 只有标题、没有 http 链接（小程序/表单/直播分享等）
    plain = []          # 只有裸链接
    for line in io.open(src, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        j = json.loads(line)
        orig = j.get("raw") or ""                     # 原始（含 refermsg）
        raw = REFER.sub("", orig)                     # 剥掉引用后，才是"本条自己的卡片"
        blob = raw + " " + (j.get("text") or "")
        rec = {"ts": int(j.get("ts") or 0), "chat": (j.get("chat_name") or j.get("chat") or "?").strip(),
               "who": (j.get("sender_name") or j.get("sender") or "").strip()}
        tm = TITLE_RE.search(raw)                     # 标题只从非引用部分取
        um = URL_RE.search(raw)
        # 真卡片一定包在 <appmsg> 里；拍一拍/系统提示的 <title> 不算（否则清单会被闲聊塞满）
        if tm and "<appmsg" in raw and not re.search(r"拍了拍|撤回", tm.group(1)):
            u = (um.group(1).replace("&amp;", "&").strip() if um else "")
            rm = REFER.search(orig)                   # ★引用要从**原始** raw 里找
            # 引用块里的标题是**转义**的（&lt;title&gt;尺码统计&lt;/title&gt;）→ 先反转义再取
            rt = TITLE_RE.search(rm.group(0).replace("&lt;", "<").replace("&gt;", ">")) if rm else None
            item = dict(rec, title=re.sub(r"\s+", " ", tm.group(1)).strip()[:120], url=u,
                        quoted=re.sub(r"\s+", " ", rt.group(1)).strip()[:60] if rt else "")
            if u.startswith("http"):
                cards.append(item)
            elif item["quoted"] or re.search(CARDKW, item["title"]):
                nolink.append(item)      # 只留"引用了某张卡"或"标题像表单/活动"的
            continue
        for u in dict.fromkeys(ANY_URL.findall(blob)):
            plain.append(dict(rec, title="", url=u))

    idx = local_index()
    seen, uniq = set(), []
    for c in cards:
        k = urlkey(c["url"]) if c["url"] else "t_" + c["title"][:40]
        if k in seen:
            continue
        seen.add(k)
        c["key"] = k
        c["local"] = idx.get(k)
        uniq.append(c)

    fetched = []
    if do_fetch:
        for c in uniq:
            if c["local"] or not c["url"]:
                continue
            out = os.path.join(ART, "_day_%s_%s.md" % (DATE, re.sub(r"\W", "", c["key"])[:24]))
            try:
                subprocess.run(["node", os.path.join(HERE, "scripts", "fetch_article.mjs"), c["url"], out],
                               capture_output=True, text=True, timeout=90)
            except Exception as e:  # noqa: BLE001
                fetched.append((c["title"] or c["url"], "ERROR %s" % e))
                continue
            n = 0
            if os.path.exists(out):
                n = len(io.open(out, encoding="utf-8", errors="replace").read())
            c["local"] = (os.path.basename(out), n) if n > 400 else None
            fetched.append((c["title"] or c["url"][:60], "%d 字符%s" % (n, "（疑似 captcha/空正文）" if n <= 400 else "")))

    out = os.path.join(HERE, "output", "days", "%s_articles.md" % DATE)
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("# %s 当天文章/卡片清单（提炼前**必查**：有正文的必须读，别只读群消息）\n\n" % DATE)
        f.write("> 本地正文目录：`output\\window\\articles\\`（历史上抓过的都在这里；**先查它再考虑联网**）\n")
        f.write("> 联网抓微信文章现在常被反爬拦到 captcha → 抓不到就如实标注，不要静默跳过\n\n")
        f.write("## 一、带标题的文章卡片（%d 篇去重后）\n\n" % len(uniq))
        if not uniq:
            f.write("- （无）\n")
        for c in sorted(uniq, key=lambda x: x["ts"]):
            h = dt.datetime.fromtimestamp(c["ts"], TZ).strftime("%H:%M")
            loc = ("**有正文：`output\\window\\articles\\%s`（%d 字符）**" % c["local"]) if c["local"] else "**本地无正文**"
            f.write("- %s [%s] %s：**%s**\n  - %s\n" % (h, c["chat"][:16], c["who"][:10], c["title"], loc))
            if c["url"]:
                f.write("  - %s\n" % c["url"])
        f.write("\n## 二、有标题但无 http 链接的卡片（小程序 / 表单 / 直播分享；**这类常是「要填的表」**）\n\n")
        if not nolink:
            f.write("- （无）\n")
        for c in sorted(nolink, key=lambda x: x["ts"])[:20]:
            h = dt.datetime.fromtimestamp(c["ts"], TZ).strftime("%H:%M")
            q = ("（引用：%s）" % c["quoted"]) if c.get("quoted") else ""
            f.write("- %s [%s] %s：**%s**%s\n" % (h, c["chat"][:16], c["who"][:10], c["title"], q))
        f.write("\n## 三、只出现裸链接的（%d 条，未标题化）\n\n" % len(plain))
        if not plain:
            f.write("- （无）\n")
        for c in sorted(plain, key=lambda x: x["ts"])[:40]:
            h = dt.datetime.fromtimestamp(c["ts"], TZ).strftime("%H:%M")
            hit = idx.get(urlkey(c["url"]))
            f.write("- %s [%s] %s：%s%s\n" % (h, c["chat"][:16], c["who"][:10], c["url"][:110],
                                              ("（有正文：%s）" % hit[0]) if hit else ""))
    miss = sum(1 for c in uniq if not c["local"])
    print("%s ｜ 卡片 %d 篇（本地有正文 %d / 缺 %d）｜ 裸链 %d 条 → %s"
          % (DATE, len(uniq), len(uniq) - miss, miss, len(plain), out))
    for t, r in fetched:
        print("   fetch: %s -> %s" % (t[:50], r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
