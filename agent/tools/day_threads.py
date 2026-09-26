# -*- coding: utf-8 -*-
"""day_threads.py — 当天出现的主题，**回看前几天**有没有出现过（"这是新事还是旧事的进展"）。

为什么需要它（2026-09-13 用户指出"跨会话建立时间轴和联系的能力太弱"）：
原则 17 早就写了"第二天的下集，价值点是**口径变化**"，但没有任何工具支撑 ——
实测算力券这条：09-12 19:10（严家乐）与 09-13 18:14（王嘉豪）转的是**同一篇文章**，
两天两处各写各的，没人告诉你"这是第 2 天出现"。

只收**可精确判定**的三种键（不猜语义）：
  A. 文章 URL 键（`__biz+mid+idx+sn` 或 `/s/<id>`）——同一篇文章再次被转发
  B. 卡片标题（`<appmsg><title>`，非引用、去空白，长度 >= 6）——同一个活动/资源再次出现
  C. 域名（`https?://host`）——同一个平台/入口再次出现

用法: python tools\\day_threads.py 2026-09-13 [回看天数，默认 3]
产出: output/days/<date>_threads.md
"""
import datetime as dt
import io
import json
import os
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = dt.timezone(dt.timedelta(hours=8))
REFER = re.compile(r"<refermsg>.*?</refermsg>", re.S)
TITLE = re.compile(r"<title>(.*?)</title>", re.S)
DOM = re.compile(r"https?://([^/\s\"'<>]+)")
MP = re.compile(r"https?://mp\.weixin\.qq\.com/[^\s\"'<>\\)）】]+")
STOP_DOM = {"mp.weixin.qq.com", "wxapp.tc.qq.com", "vweixinf.tc.qq.com", "support.weixin.qq.com"}
# 2026-09-15 加：CDN / 头像 / 表情 / 微信自身域一律不当"跨天键" ——
#   实测（09-12~09-14）这个文件"命中的键"全是 wx.qlogo.cn / mmbiz.qpic.cn / qun.qq.com 这类噪音，
#   15 个键里没有一个能回答"这是不是同一件事的第 N 天"，所以这一步从来没被用上。
NOISE_DOM = re.compile(r"(?:^|\.)(qpic\.cn|qlogo\.cn|gtimg\.cn|qun\.qq\.com|weixin\.qq\.com|wx\.qq\.com|"
                       r"tc\.qq\.com|qq\.com|wechat\.com|wxs\.qq\.com)$")


def urlkey(u):
    u = u.replace("&amp;", "&")
    b = re.search(r"__biz=([^&]+)", u)
    m = re.search(r"mid=(\d+)", u)
    i = re.search(r"idx=(\d+)", u)
    s = re.search(r"sn=([0-9a-fA-F]+)", u)
    if b and m and i and s:
        return "文:%s/%s/%s" % (m.group(1), i.group(1), s.group(1)[:8])
    k = re.search(r"/s/([A-Za-z0-9_-]{10,})", u)
    return "文短:" + k.group(1)[:20] if k else ""


def keys_of(path):
    """从一天的 jsonl 里抽键 -> [(hm, chat, key, 摘要)]"""
    out = []
    for line in io.open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        j = json.loads(line)
        orig = j.get("raw") or ""
        raw = REFER.sub("", orig)
        ts = int(j.get("ts") or 0)
        hm = dt.datetime.fromtimestamp(ts, TZ).strftime("%m-%d %H:%M")
        chat = (j.get("chat_name") or j.get("chat") or "?").strip()
        who = (j.get("sender_name") or j.get("sender") or "").strip()
        for u in dict.fromkeys(MP.findall(raw)):
            k = urlkey(u)
            if k:
                out.append((hm, chat, who, k, u[:90]))
        for t in dict.fromkeys(TITLE.findall(raw)) if "<appmsg" in raw else []:
            # 2026-09-15：剥掉 CDATA 包装、并跳过系统卡（登录操作通知/邀请你加入群聊/群聊的聊天记录…）——
            #   实测它们混在"跨天键"里，让这一步看起来有产出、实际全是噪音。
            t = re.sub(r"<!\[CDATA\[|\]\]>", "", t)
            t = re.sub(r"\s+", "", re.sub(r"&amp;", "&", t))
            if len(t) >= 6 and not re.search(r"拍了拍|撤回|登录操作通知|邀请你加入群聊|群聊的聊天记录|微信红包|微信运动", t):
                out.append((hm, chat, who, "卡:" + t[:36], t[:90]))
        for d in dict.fromkeys(DOM.findall(raw)):
            if d not in STOP_DOM and "." in d and not NOISE_DOM.search(d):
                out.append((hm, chat, who, "域:" + d, d))
    return out


def main():
    args = [a for a in sys.argv[1:] if a]
    DATE = args[0] if args else dt.datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        __import__("datetime").datetime.strptime(DATE, "%Y-%m-%d")
    except Exception:
        raise SystemExit("day_threads.py: 日期参数必须是 YYYY-MM-DD，收到 %r" % (DATE,))
    back = int(args[1]) if len(args) > 1 else 3
    d0 = dt.datetime.strptime(DATE, "%Y-%m-%d").replace(tzinfo=TZ)

    today = keys_of(os.path.join(HERE, "output", "days", "%s.jsonl" % DATE))
    if not today:
        print("没有数据：%s" % DATE)
        return 1
    tmap = defaultdict(list)
    for hm, chat, who, k, snip in today:
        tmap[k].append((hm, chat, who, snip))

    hist = defaultdict(list)                      # key -> [(date, hm, chat, snip)]
    for i in range(1, back + 1):
        d = (d0 - dt.timedelta(days=i)).strftime("%Y-%m-%d")
        p = os.path.join(HERE, "output", "days", "%s.jsonl" % d)
        if not os.path.exists(p):
            continue
        for hm, chat, who, k, snip in keys_of(p):
            hist[k].append((d, hm, chat, snip))

    rows = []
    for k, hits in tmap.items():
        # 只报"今天出现过、以前也出现过"的；今天太泛滥的键（>6 次）多半是背景，不报
        if k not in hist or len(hits) > 6:
            continue
        rows.append((k, hits, hist[k]))
    rows.sort(key=lambda x: (-len(x[2]), len(x[1]), x[0]))

    out = os.path.join(HERE, "output", "days", "%s_threads.md" % DATE)
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("# %s 主题跨天回溯（回看 %d 天；**同一个键今天与以前都出现过**）\n\n" % (DATE, back))
        f.write("> 只收可精确判定的三种键：文章URL键 / 卡片标题 / 域名。**不猜语义联系。**\n")
        f.write("> 用法：看到「以前也出现过」→ 去核对**是不是同一件事的第 N 天、口径有没有变**（原则 17）。\n")
        f.write("> 命中 %d 个键（今天出现过 且 回看窗口内出现过）\n\n" % len(rows))
        if not rows:
            f.write("- （无：今天没有「以前也出现过」的键）\n")
        for k, hits, old in rows:
            f.write("## %s\n\n" % k[:80])
            for hm, chat, who, snip in hits[:4]:
                f.write("- **今天** %s [%s] %s：%s\n" % (hm, chat[:16], who[:10], snip[:100]))
            for d, hm, chat, snip in old[:4]:
                f.write("- 以前　 %s [%s]：%s\n" % (hm, chat[:16], snip[:100]))
            if len(old) > 4:
                f.write("- …以前共 %d 处\n" % len(old))
            f.write("\n")
    print("%s ｜ 跨天命中 %d 个键 → %s" % (DATE, len(rows), out))
    for k, hits, old in rows[:8]:
        print("   %s ｜ 今天 %d 处 / 以前 %d 处" % (k[:40], len(hits), len(old)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
