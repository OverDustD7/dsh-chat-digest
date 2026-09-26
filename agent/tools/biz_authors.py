# -*- coding: utf-8 -*-
r"""biz_authors.py — 每天挖一遍"被转发的公众号作者"，并解出号名（供 `docs\knowledge\official_accounts.md` 第一节）。

用户 2026-09-15 的要求：**"你每天都该看一眼（别人转发的，自己在网上搜）"**。
为什么不能只看本地推送：微信只把**他本人已关注**号的推送写进 `biz_articles.jsonl`
→ 只看它，能发现的号**永远只有他自己关注的那几个**。别人转到群里/私聊的文章，作者往往是他没关注的号。

所以以 `output\days\<date>_articles.md` 为主源（3e 视图，**链接是完整的**、还带标题/转发人/群/时间），
按链接里的 `__biz` 归并成"号"，再用 `--fetch`（本机 `node scripts\fetch_article.mjs`，不用宿主 web 工具）
抓每个号的一篇解出**号名**，最后标出哪些是**他已关注**、哪些是**值得关注但没关注**的候选。

用法:
  python tools\biz_authors.py                          # 统计（快，不联网）：默认最近 30 天
  python tools\biz_authors.py --date 2026-10-01        # 只扫这一天
  python tools\biz_authors.py --from 2026-09-28 --to 2026-10-03   # 区间（含两端，跨月/跨年都行）
  python tools\biz_authors.py --days 7                 # 默认行为改成最近 7 天
  python tools\biz_authors.py --all                    # 本机 output\days 下所有 _articles.md
  python tools\biz_authors.py --fetch                  # 顺带抓号名（每个号一篇，缓存到 output\window\articles\）
产出: output\window\biz_authors.md

审计 A14（2026-09-20）修的是：原来这里 glob 写死 `2026-09-*_articles.md`，10 月的新文件永远扫不到。
现在窗口由日期算术算出，跨月、跨年都不会漏；**窗口里每一天都会打印一行**，
没有文件的天、有文件但 0 篇的天都显式写出来（0 篇必须打印，不许静默跳过）。
不带参数时锚点取本机 output\days 里**最新**的 `_articles.md`（数据"到今天为止"的日期），
往前 30 天 —— 覆盖范围只增不减，所以不会比旧行为更差。
"""
import argparse
import datetime
import glob
import io
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL_RE = re.compile(r"https?://mp\.weixin\.qq\.com/s\?[^\s\"'<>\\)\]，,；;]+")
BIZ_RE = re.compile(r"__biz=([A-Za-z0-9=+/]+)")
CARD_RE = re.compile(r"^-\s+(\d\d:\d\d)\s+\[([^\]]+)\]\s+([^：:]{1,24})[：:]\s*\*\*(.+?)\*\*")
# `2026-09-17_articles.md` / `2026-9-14_articles.md` 两种命名都收（output\days 里两种都出现过）
ART_MD_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})_articles\.md$")


def load_jsonl(p):
    for l in io.open(p, encoding="utf-8", errors="replace"):
        l = l.strip()
        if l:
            try:
                yield json.loads(l)
            except Exception:
                pass


def parse_ymd(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        raise SystemExit("日期必须是 YYYY-MM-DD，收到 %r" % (s,))


def articles_md_map():
    """本机 `output\\days\\*_articles.md`：date -> 路径（文件名不合法的忽略）。"""
    m = {}
    for p in glob.glob(os.path.join(HERE, "output", "days", "*_articles.md")):
        mt = ART_MD_RE.match(os.path.basename(p))
        if mt:
            m[datetime.date(int(mt.group(1)), int(mt.group(2)), int(mt.group(3)))] = p
    return m


def date_window(a, amap):
    """返回 (days, from_date, to_date)：--date 单日 / --from--to 区间 / 否则最近 N 天。"""
    if a.date and (a.date_from or a.date_to):
        raise SystemExit("--date 与 --from/--to 不能同时用")
    if a.date:
        d = parse_ymd(a.date)
        return [d], d, d
    if a.date_from or a.date_to:
        f = parse_ymd(a.date_from or a.date_to)
        t = parse_ymd(a.date_to or a.date_from)
        if f > t:
            raise SystemExit("--from 不能晚于 --to（%s > %s）" % (f, t))
    else:
        # 默认锚点：本机最新的 _articles.md（数据"到今天为止"的日期）；一份都没有就退回系统今天
        t = max(amap) if amap else datetime.date.today()
        f = t - datetime.timedelta(days=max(1, a.days) - 1)
    n = (t - f).days + 1
    return [f + datetime.timedelta(days=i) for i in range(n)], f, t


def rows_from_articles_md(days, amap):
    """从窗口内每天的 `output\\days\\<date>_articles.md` 取（完整链接 + 标题 + 转发人 + 群 + 日期）。

    只统计**第一节「带标题的文章卡片」**：二、三节是没有链接的卡片/裸链接，不算"文章"。
    返回 (rows, per_day, missing)：
      per_day[date] = {"cards","with_body","no_body"} 或 None（当天没有 _articles.md）
      missing       = 窗口里缺文件的天（**显式报出，不静默跳过**）
    """
    rows, per_day, missing = [], {}, []
    for d in days:
        p = amap.get(d)
        if not p:
            per_day[d] = None
            missing.append(d)
            continue
        st = {"cards": 0, "with_body": 0, "no_body": 0}
        cur = None
        in_sec1 = False
        for ln in io.open(p, encoding="utf-8", errors="replace"):
            if ln.startswith("## "):
                in_sec1 = "带标题的文章卡片" in ln
                if in_sec1:
                    m = re.search(r"（\s*(\d+)\s*篇", ln)
                    if m:
                        st["cards"] = int(m.group(1))
                cur = None
                continue
            if not in_sec1:
                continue
            if "**有正文" in ln:
                st["with_body"] += 1
                continue
            if "**本地无正文" in ln:
                st["no_body"] += 1
                continue
            m = CARD_RE.match(ln)
            if m:
                cur = {"t": m.group(1), "chat": m.group(2), "who": m.group(3).strip(),
                       "title": m.group(4)}
                continue
            u = URL_RE.search(ln)
            if u and cur:
                out_row = dict(cur, url=u.group(0).rstrip("。，、）)"), date=d.isoformat())
                rows.append(out_row)
                cur = None
        per_day[d] = st
    return rows, per_day, missing


def followed_accounts():
    s = set()
    p = os.path.join(HERE, "output", "window", "biz_articles.jsonl")
    if os.path.exists(p):
        for j in load_jsonl(p):
            if j.get("account"):
                s.add(str(j["account"]))
    return s


def names_from_cache():
    """已抓正文里的号名：`output\\window\\articles\\*.md` 的 `- 公众号：X`。

    注意（2026-09-15 踩过）：**别用 `\\s*` 去匹配冒号后的空白** —— 它会跨行吃掉下一行的
    `- 发布：`，于是把号名解成 "- 发布："。这里用 `[^\\n]+` 严格限定在同一行。
    """
    m = {}
    for p in glob.glob(os.path.join(HERE, "output", "window", "articles", "*.md")):
        head = io.open(p, encoding="utf-8", errors="replace").read()[:1500]
        acc = re.search(r"公众号[ \t]*[：:][ \t]*([^\n]+)", head)
        u = URL_RE.search(head)
        b = BIZ_RE.search(u.group(0)) if u else None
        name = acc.group(1).strip() if acc else ""
        if b and name and name not in ("-", "发布：") and not name.startswith("- "):
            m[b.group(1)] = name
    return m


def fetch_unknown(unknown, limit):
    """每个未知号抓一篇解号名（缓存；已存在就跳过）。"""
    adir = os.path.join(HERE, "output", "window", "articles")
    os.makedirs(adir, exist_ok=True)
    got = {}
    for biz, info in sorted(unknown.items(), key=lambda kv: -kv[1]["count"])[:limit]:
        out = os.path.join(adir, "biz_%s.md" % biz[:16])
        if not os.path.exists(out):
            try:
                subprocess.run(["node", os.path.join(HERE, "scripts", "fetch_article.mjs"), info["url"], out],
                               cwd=HERE, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=90)
            except Exception as e:  # noqa: BLE001
                print("   抓取异常 %s" % e)
        head = io.open(out, encoding="utf-8", errors="replace").read()[:1500] if os.path.exists(out) else ""
        acc = re.search(r"公众号[ \t]*[：:][ \t]*([^\n]+)", head)
        nm = acc.group(1).strip() if acc else ""
        if nm in ("-", "发布："):
            nm = ""
        print("   %-24s %-22s %s" % (biz[:24], nm or "(未解出)", info["title"][:34]))
        if nm and nm != "-":
            got[biz] = nm
    return got


def main():
    ap = argparse.ArgumentParser(
        description="挖被转发的公众号作者（默认最近 N 天，锚点=本机 output\\days 里最新的 _articles.md）")
    ap.add_argument("--out", default=os.path.join(HERE, "output", "window", "biz_authors.md"))
    ap.add_argument("--date", help="只扫这一天（YYYY-MM-DD）")
    ap.add_argument("--from", dest="date_from", help="区间起（YYYY-MM-DD，含）")
    ap.add_argument("--to", dest="date_to", help="区间止（YYYY-MM-DD，含）")
    ap.add_argument("--days", type=int, default=30, help="不带日期参数时扫最近 N 天（默认 30）")
    ap.add_argument("--all", action="store_true", help="扫本机 output\\days 下所有 _articles.md")
    ap.add_argument("--fetch", action="store_true", help="未知号名的抓一篇解出来（本机 node）")
    ap.add_argument("--limit", type=int, default=30)
    a = ap.parse_args()

    amap = articles_md_map()
    if a.all:
        if a.date or a.date_from or a.date_to:
            raise SystemExit("--all 与 --date/--from/--to 不能同时用")
        if not amap:
            raise SystemExit("output\\days 下没有任何 *_articles.md，无从统计")
        days = sorted(amap)
        d_from, d_to = days[0], days[-1]
    else:
        days, d_from, d_to = date_window(a, amap)

    rows, per_day, missing = rows_from_articles_md(days, amap)

    # 窗口逐日打印：缺文件的天、0 篇的天都显式写出来（0 篇必须可见）
    zero = [d for d in days if per_day[d] and per_day[d]["cards"] == 0]
    print("窗口 %s .. %s（%d 天）｜ 有 _articles.md %d 天 ｜ 缺文件 %d 天 ｜ 0 篇 %d 天"
          % (d_from, d_to, len(days), len(days) - len(missing), len(missing), len(zero)))
    for d in days:
        st = per_day[d]
        if st is None:
            print("  %s  缺 _articles.md（按 0 篇计）" % d)
            continue
        note = ""
        if st["cards"] == 0:
            note = "  <- 0 篇（当天没有文章卡片）"
        elif st["cards"] != st["with_body"] + st["no_body"]:
            note = "  <- 表头 %d 篇 与正文行数 %d 不一致，需复核" % (st["cards"], st["with_body"] + st["no_body"])
        print("  %s  卡片 %d 篇（有正文 %d / 缺正文 %d）%s"
              % (d, st["cards"], st["with_body"], st["no_body"], note))

    acc = {}
    for r in rows:
        m = BIZ_RE.search(r["url"])
        if not m:
            continue
        biz = m.group(1)
        d = acc.setdefault(biz, {"count": 0, "urls": set(), "chats": set(), "who": set(),
                                 "titles": [], "dates": set(), "title": r["title"], "url": r["url"]})
        if r["url"] not in d["urls"]:
            d["count"] += 1
            d["urls"].add(r["url"])
            d["titles"].append("%s（%s %s）" % (r["title"][:40], r["date"][5:], r["who"]))
        d["chats"].add(r["chat"])
        d["who"].add(r["who"])
        d["dates"].add(r["date"])

    known = names_from_cache()
    followed = followed_accounts()
    unknown = {b: d for b, d in acc.items() if b not in known}
    # 本地推送（他已关注号）也补一份：**只用来解出真名**（修 #27：contact 表的备注名 ≠ 真号名，
    # 「艾生活｜秋季学期选课安排」实际号是「艾生权」），不进"未关注候选池"——这些号他本来就关注了。
    push = {}
    bp = os.path.join(HERE, "output", "window", "biz_articles.jsonl")
    if os.path.exists(bp):
        for j in load_jsonl(bp):
            m = BIZ_RE.search(j.get("url") or "")
            if m and m.group(1) not in known:
                d = push.setdefault(m.group(1), {"count": 0, "url": j.get("url"), "title": (j.get("title") or "")[:46]})
                d["count"] += 1
    if a.fetch and push:
        print("--fetch：本地推送里还有 %d 个号没解出真名（#27 用）" % len(push))
        known.update(fetch_unknown(push, max(0, a.limit - len(unknown))))
    if a.fetch and unknown:
        known.update(fetch_unknown(unknown, a.limit))

    lines = ["# 被转发的公众号作者（来源：`output\\days\\*_articles.md` 的文章卡片；窗口 %s .. %s；共 %d 个号 / %d 篇）"
             % (d_from, d_to, len(acc), sum(d["count"] for d in acc.values())), "",
             "> 这张表回答「别人转发的文章是谁写的」。**他已关注**的号本地才有推送；未关注的才是「值得关注」的候选。", "",
             "> 窗口口径：逐日读 `output\\days\\<date>_articles.md` 第一节「带标题的文章卡片」；"
             "缺文件的天按 0 篇计（不静默跳过）。", "",
             "| 号 | 篇数 | 谁转发（群/人） | 日期 | 状态 |", "|---|---|---|---|---|"]
    cand = []
    for biz, d in sorted(acc.items(), key=lambda kv: -kv[1]["count"]):
        nm = known.get(biz, "")
        st = "已关注" if nm in followed else ("未关注" if nm else "**号名未解出**")
        if nm and nm not in followed:
            cand.append((nm, d["count"], "、".join(sorted(d["chats"])[:2]), d["titles"][0]))
        lines.append("| %s | %d | %s | %s | %s |" % (nm or ("`%s`" % biz[:20]),
                                                     d["count"], "、".join(sorted(d["chats"])[:2])[:46],
                                                     ",".join(sorted(d["dates"]))[2:], st))
    lines += ["", "## 值得关注但**他还没关注**的号（候选池）", ""]
    if cand:
        for nm, c, chats, t in sorted(cand, key=lambda x: -x[1]):
            lines.append("- **%s**（%d 篇｜%s）例：%s" % (nm, c, chats, t))
    else:
        lines.append("（本轮没有解出新的未关注号；把 `--fetch` 跑一遍再看）")
    with io.open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print("文章卡片：%d 篇 → %d 个号 ｜ 已解出号名 %d ｜ 未关注候选 %d ｜ 号名未解出 %d"
          % (len(rows), len(acc), len(known), len(cand), sum(1 for b in acc if b not in known)))
    for nm, c, chats, t in sorted(cand, key=lambda x: -x[1])[:12]:
        print("   + %-22s %d 篇  %s" % (nm, c, chats))
    print("明细 -> %s" % os.path.relpath(a.out, HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
