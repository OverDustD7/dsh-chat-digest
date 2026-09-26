# -*- coding: utf-8 -*-
"""units_day.py — 把一天的消息**机械降噪**成"话语单元"（水群能逐条读完的前提）。

背景（2026-09-13 用户："对于水群，你有没有更好的想法"）：
方向不是"筛得更准"，而是**把 5000 条变成能逐条读完的 ~800 个单元** ——
覆盖率不降，降的是"要读多少个东西"。全程机械规则，不用模型、几乎零成本。

三步：
  ① 连续发言折叠：同一人、同一会话、间隔 ≤ 窗口秒 的连续消息 → 合成一个单元
  ② 复读/接龙合并：时间相邻 + 文本（规范化后）高度相同 → 合成一个单元（记 ×N 人）
     （大群的钱都花在复读上：同一句被十几个人接龙）
  ③ 标注问答：以 @/回复 开头 → [答]；短且以问号结尾 → [问]。**只标注，绝不删除**（避免信息损失）

用法:  python tools\\units_day.py [YYYY-MM-DD] [复读/折叠窗口秒=300]
产出:  output/days/<date>_units.md   ← 头部是"降噪前后"的统计，正文是单元列表
"""
import datetime as dt
import difflib
import io
import os
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import split_day as sd  # noqa: E402  复用它的清洗/去噪（同一套噪声口径）

TZ = dt.timezone(dt.timedelta(hours=8))
NORM = re.compile(r"[^\w\u4e00-\u9fff]+")
QTAIL = re.compile(r"[?？]$")
ATHEAD = re.compile(r"^(@|回复|引用|\[回复)")


def norm(t):
    return NORM.sub("", t).lower()


def fold(rows, win):
    """① 同一人连续发言折叠"""
    out = []
    for r in rows:
        last = out[-1] if out else None
        if (last and last["chat"] == r["chat"] and last["sender"] == r["sender"]
                and 0 <= r["ts"] - last["ts"] <= win):
            # 折叠合并也**不许静默截断**：原来是 `[:600]`，把合并后文本的尾巴切掉，
            # 而合并的往往是同一人的连续发言（公告常常连发几条）→ 尾巴里正是动作与链接。
            last["text"] = sd.clip(last["text"] + " / " + r["text"])[0]
            last["ts_end"] = r["ts"]
            last["n"] += 1
        else:
            out.append({"chat": r["chat"], "chat_name": r["chat_name"], "sender": r["sender"],
                        "sender_name": r["sender_name"], "ts": r["ts"], "ts_end": r["ts"],
                        "text": r["text"], "n": 1, "rk": 1})
    return out


def merge_repeat(units, win, ratio=0.92):
    """② 复读/接龙合并（相邻、同会话、文本几乎一样）"""
    out = []
    for u in units:
        last = out[-1] if out else None
        if last and last["chat"] == u["chat"] and 0 <= u["ts"] - last["ts_end"] <= win:
            a, b = norm(last["text"]), norm(u["text"])
            same = a == b or (len(b) >= 4 and (b in a or a in b)) or \
                (len(a) >= 4 and len(b) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= ratio)
            if same:
                last["rk"] += 1
                last["ts_end"] = u["ts_end"]
                last["n"] += u["n"]
                if len(u["text"]) > len(last["text"]):
                    last["text"] = u["text"]
                continue
        out.append(u)
    return out


def dedup_global(units, minlen=8):
    """③ 全局去重（不只相邻）：同会话内、规范化后完全相同的**较长**文本只留一次，记 ×N。
    实测依据（09-13 大群）：`QQ2/2` 那 595 条长度高度一致（40–42 字），疑似同一条被反复发；
    而"相邻复读合并"只覆盖接龙，跨时间的重复它看不见。短文本（<minlen）不去重，免得把"？"这类误合并。"""
    seen = {}
    out = []
    for u in units:
        n = norm(u["text"])
        if len(n) >= minlen and (u["chat"], n) in seen:
            tgt = seen[(u["chat"], n)]
            tgt["rk"] += 1
            tgt["ts_end"] = max(tgt["ts_end"], u["ts_end"])
            tgt["n"] += u["n"]
            continue                            # 文本不再写第二遍 —— 省字符就省在这里
        if len(n) >= minlen:
            seen[(u["chat"], n)] = u
        out.append(u)
    return out


# 长消息**不许静默截断**（2026-09-15 事故）：
#   原来这里写的是 `u["text"][:260]` —— AI 大赛那条 525 字公告的**尾部**（报销 / 反馈问卷 /
#   **招募问卷**）被整段砍掉，而提炼层与台账扫描读的正是这份视图 → 直接漏报（用户问"为什么没识别到"）。
#   **公告类的动作项与链接通常都在末尾**，所以尾部必须留：头 400 + 尾 400，中间显式标出省略了多少字。
CLIP_HEAD, CLIP_TAIL = 400, 400


def clip(t):
    """返回 (要写进视图的文本, 省略字数)。不超过 800 字原样返回。"""
    n = len(t)
    if n <= CLIP_HEAD + CLIP_TAIL:
        return t, 0
    head, tail = t[:CLIP_HEAD], t[-CLIP_TAIL:]
    omitted = n - len(head) - len(tail)
    return head + (" ……[省略 %d 字]…… " % omitted) + tail, omitted


def main():
    args = [a for a in sys.argv[1:] if a]
    date = args[0] if args else dt.datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        __import__("datetime").datetime.strptime(date, "%Y-%m-%d")
    except Exception:
        raise SystemExit("units_day.py: 日期参数必须是 YYYY-MM-DD，收到 %r" % (date,))
    win = int(args[1]) if len(args) > 1 else 300

    raw = sd.load(date)                      # 已去噪（卡片/系统/复读机噪声在这里被剥掉一层）
    if raw is None:
        print("缺 output/days/%s.jsonl" % date)
        return 1
    # split_day.load 返回的字段名是 text/chat/who，这里补成 units 需要的形状
    rows = [{"chat": r["chat"], "chat_name": r["chat"], "sender": r["who"], "sender_name": r["who"],
             "ts": r["ts"], "text": r["text"]} for r in raw]
    for r in rows:
        r["sender"] = r["sender"] or "?"
    u1 = fold(rows, win)
    u2 = merge_repeat(u1, win)
    u2 = dedup_global(u2)                        # ③ 全局去重（跨时间的同一条重复）
    for i, u in enumerate(u2):
        t = u["text"]
        u["tag"] = "[答]" if ATHEAD.search(t) else (("[问]" if len(t) <= 40 and QTAIL.search(t) else ""))
        u["i"] = i

    # 统计（按会话对比前后）
    stat = defaultdict(lambda: [0, 0])
    for r in rows:
        stat[r["chat_name"]][0] += 1
    for u in u2:
        stat[u["chat_name"]][1] += 1
    top = sorted(stat.items(), key=lambda kv: -kv[1][0])[:6]

    out = ["# %s 话语单元（原始 %d 行 → 去噪 %d → 折叠 %d → 复读合并后 **%d 个单元**，压掉 %.1f%%）"
           % (date, len(raw), len(rows), len(u1), len(u2), 100.0 * (1 - len(u2) / max(1, len(rows)))),
           "", "> 机械规则产出（不是筛选）：同一人连续发言折叠 + 复读/接龙合并 + 问答标注。",
           "> 供「分片全覆盖、逐条读」用 —— **读这些单元＝读过全部消息**，"
           "**唯一例外**：超过 %d 字的长消息只保留「**头 %d 字 + 尾 %d 字**」、中间以 `……[省略 N 字]……` 显式标出"
           "（公告类的动作与链接通常在**末尾**，所以尾部一定要留；2026-09-15 事故：原来砍到 260 字，"
           "把一条 525 字公告尾部的『反馈问卷/招募问卷』整段砍掉 → 漏报）。"
           % (CLIP_HEAD + CLIP_TAIL, CLIP_HEAD, CLIP_TAIL), "",
           "| 会话 | 原始行 | 单元 | 压缩 |", "|---|---|---|---|"]
    for name, (a, b) in top:
        out.append("| %s | %d | %d | %.0f%% |" % (name[:26], a, b, 100.0 * (1 - b / max(1, a))))
    out.append("")
    n_clip = n_clip_chars = 0
    for u in u2:
        hm = dt.datetime.fromtimestamp(u["ts"], TZ).strftime("%H:%M")
        mark = " ×%d人" % u["rk"] if u["rk"] > 1 else (" +%d" % (u["n"] - 1) if u["n"] > 1 else "")
        txt, elided = clip(u["text"])
        if elided:
            n_clip += 1
            n_clip_chars += elided
        out.append("- %s %s[%s] %s: %s%s" % (hm, (u["tag"] + " ") if u["tag"] else "",
                                             u["chat_name"][:16], (u["sender_name"] or "?")[:12],
                                             txt, mark))
    fn = os.path.join(HERE, "output", "days", "%s_units.md" % date)
    io.open(fn, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print("%s: raw=%d rows=%d fold=%d units=%d (cut %.1f%%) ｜ 超长省略 %d 条（共省 %d 字）"
          " -> output/days/%s_units.md"
          % (date, len(raw), len(rows), len(u1), len(u2), 100.0 * (1 - len(u2) / max(1, len(rows))),
             n_clip, n_clip_chars, date))
    for name, (a, b) in top[:3]:
        print("   chat rows=%d units=%d" % (a, b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
