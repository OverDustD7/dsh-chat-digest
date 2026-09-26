# -*- coding: utf-8 -*-
r"""compare_daily_items.py —— 双轨对比：ZCode 闲时任务的产出 vs DSH 主 agent 的产出。

用法:
    python tools\compare_daily_items.py 2026-09-15
    python tools\compare_daily_items.py 2026-09-15 --a output\zcode\2026-09-15\items.json --b output\daily\2026-09-15\items.json

产出: `output\zcode\<date>\COMPARE.md`（人读）+ 终端摘要。

为什么**不按 id 比**：两侧各自造 id（`kind`/`urgency` 也会不同），id 对齐没有意义。
所以按**内容相似度**配对：对每条 B（DSH 侧）找 A（ZCode 侧）里最像的一条，
取「4-gram 包含度」(交集 / 较短那侧)，低于阈值就记成"**A 可能漏报**"。
这个指标是**给人看的线索**，不是判据 —— 报告里会把分数一起打出来，让你能一眼复核。
"""
import argparse
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THRESH = 0.40          # 4-gram 包含度低于它 → 视为"没匹配上"


def load(p):
    if not os.path.exists(p):
        return None
    try:
        j = json.load(io.open(p, encoding="utf-8"))
    except ValueError as e:
        print("!! %s 不是合法 JSON：%s" % (p, e))
        return None
    if isinstance(j, dict):
        j = j.get("items") or []
    return [x for x in j if isinstance(x, dict)] if isinstance(j, list) else None


def norm(t):
    t = re.sub(r"[#*`>\-\|\s]+", "", str(t or ""))
    return t


def grams(t, n=4):
    t = norm(t)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))} if len(t) >= n else {t}


def sim(a, b):
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / float(min(len(ga), len(gb)))


def head(x, n=52):
    return str(x.get("text") or "").split("\n")[0][:n]


def hist(items, key):
    d = {}
    for x in items:
        d[str(x.get(key) or "?")] = d.get(str(x.get(key) or "?"), 0) + 1
    return d


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--a", default=None, help="ZCode 侧 items.json")
    ap.add_argument("--b", default=None, help="DSH 侧 items.json")
    a = ap.parse_args(argv)
    date = a.date
    pa = a.a or os.path.join("output", "zcode", date, "items.json")
    pb = a.b or os.path.join("output", "daily", date, "items.json")
    A, B = load(os.path.join(HERE, pa)), load(os.path.join(HERE, pb))
    if A is None:
        print("缺 A（ZCode 侧）：%s —— 闲时任务还没产出，或路径不对" % pa)
        return 2
    if B is None:
        print("缺 B（DSH 侧）：%s —— 那一轮没跑过 / 没落 items.json" % pb)
        return 2

    # 配对：每条 B 找 A 里最像的；每条 A 找 B 里最像的
    def pair(src, dst):
        out = []
        for s in src:
            st = str(s.get("text") or "")
            best, sc = None, 0.0
            for d in dst:
                v = sim(st, str(d.get("text") or ""))
                if v > sc:
                    best, sc = d, v
            out.append((s, best, sc))
        return out

    b2a = pair(B, A)
    a2b = pair(A, B)
    miss = [(s, sc, m) for s, m, sc in b2a if sc < THRESH]      # B 有、A 没有 → ZCode 可能漏
    extra = [(s, sc, m) for s, m, sc in a2b if sc < THRESH]     # A 有、B 没有 → ZCode 可能多报
    matched = [(s, sc) for s, m, sc in b2a if sc >= THRESH]

    def med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else 0

    out = ["# %s 双轨对比（A＝ZCode 闲时任务 ｜ B＝DSH 主 agent）" % date, "",
           "> **先读这段**：本文件的自动配对结论**只能当线索、不能当判定**（2026-09-15 实测踩过三点）：",
           "> ① 两侧**读的语料可能不同**（A 读 `<date>_slices.md` 索引分片＝3i 筛后；DSH 那轮可能读非 `--units` 的全量分片）；",
           "> ② **B 常常是「累计活清单」**（含前几天继承的条目），而 A 是**单天提炼** ⇒ 「B 有 A 无」里很多是"
           "**源消息根本不在当天语料里**；",
           "> ③ n-gram 判不了同题不同措辞（实测同题可低到 0.20、不同题噪音可到 0.15）。",
           "> ⇒ **正解：看下面的并排清单逐题判**，可疑的回语料核实（`output\\logs\\_corpus_check.py` 是范例）。", "",
           "- A：`%s` —— **%d 条**" % (pa, len(A)),
           "- B：`%s` —— **%d 条**" % (pb, len(B)),
           "- 配对阈值：4-gram 包含度 ≥ %.2f（**只是线索**）" % THRESH, "",
           "## 两侧条目并排（**逐题看这一节**）", ""]
    for tag, xs in (("A ＝ ZCode 闲时任务", A), ("B ＝ DSH 主 agent", B)):
        out += ["### %s（%d 条）" % (tag, len(xs)), ""]
        for i, x in enumerate(xs, 1):
            out.append("%2d. `%s` [%s/%s] %s" % (i, x.get("date"), x.get("kind"), x.get("urgency"), head(x, 90)))
        out.append("")
    out += ["## date 分布（**用这里判断 B 是不是累计清单**）", "",
            "- A：%s" % dict(sorted(hist(A, "date").items())),
            "- B：%s" % dict(sorted(hist(B, "date").items())), "",
            "> B 的 date 跨好几天、A 只有一天 ⇒ 两者不是同一种东西，「B 有 A 无」不能直接算漏报。", "",
            "## 分类分布", "", "| 类别 | A(ZCode) | B(DSH) |", "|---|---|---|"]
    ka, kb = hist(A, "kind"), hist(B, "kind")
    for k in sorted(set(ka) | set(kb)):
        out.append("| `%s` | %d | %d |" % (k, ka.get(k, 0), kb.get(k, 0)))
    out += ["", "| 紧迫性 | A(ZCode) | B(DSH) |", "|---|---|---|"]
    ua, ub = hist(A, "urgency"), hist(B, "urgency")
    for k in sorted(set(ua) | set(ub)):
        out.append("| `%s` | %d | %d |" % (k, ua.get(k, 0), ub.get(k, 0)))
    out += ["", "## 正文长度（中位数，字符）", "",
            "- A：%d ｜ B：%d ｜ 匹配上的 %d 对" % (med([len(str(x.get("text") or "")) for x in A]),
                                                med([len(str(x.get("text") or "")) for x in B]), len(matched)), "",
            "## 未配上（**线索，需回语料人工核**）—— A 侧缺 B 的", ""]
    if miss:
        for s, sc, m in sorted(miss, key=lambda r: -len(str(r[0].get("text") or ""))):
            near = ("（最近的一条 A 相似度 %.2f：%s）" % (sc, head(m))) if m else "（A 里一条都没有）"
            out.append("- `%s` [%s/%s] %s  \n  %s" % (s.get("id"), s.get("kind"), s.get("urgency"), head(s), near))
    else:
        out.append("- （无）")
    out += ["", "## 未配上 —— A 侧多出 B 的", ""]
    if extra:
        for s, sc, m in sorted(extra, key=lambda r: -len(str(r[0].get("text") or ""))):
            near = ("（最近的一条 B 相似度 %.2f：%s）" % (sc, head(m))) if m else "（B 里一条都没有）"
            out.append("- `%s` [%s/%s] %s  \n  %s" % (s.get("id"), s.get("kind"), s.get("urgency"), head(s), near))
    else:
        out.append("- （无）")
    out += ["", "## 怎么读这份对比（别只看条数）", "",
            "1. **先看「A 可能漏报」** —— 漏报比多报严重得多（多报只是噪音，漏报是没做事）。",
            "2. **逐条回原文核实**：相似度是线索不是判据；A 的那条可能只是写法不同。",
            "3. **看执行形态**：A 的 `SUMMARY.md` 里写了用没用前台子智能体、有没有降级成串行 —— 降级了就别怪它漏。",
            "4. **看动作项台账**：A 的 `ACTION-LEDGER.md` 与 `%s_action_scan.md` 对账，命中是否**每条都有处置**。" % date,
            "5. 结论只有两种：**可以替换** / **继续留在 DSH**；两者都要写进 `docs\\EVOLUTION.md`。", ""]
    outdir = os.path.join(HERE, "output", "zcode", date)
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    p = os.path.join(outdir, "COMPARE.md")
    io.open(p, "w", encoding="utf-8", newline="\n").write("\n".join(out))

    print("A(ZCode) %d 条 ｜ B(DSH) %d 条 ｜ 配上 %d 对" % (len(A), len(B), len(matched)))
    print("  未配上（线索，需回语料人工核）：A 缺 B 的 %d 条 ｜ A 多出 B 的 %d 条" % (len(miss), len(extra)))
    print("  kind: A=%s  B=%s" % (ka, kb))
    for s, sc, m in sorted(miss, key=lambda r: -len(str(r[0].get("text") or "")))[:5]:
        print("  漏报候选？ %s  [%s/%s]" % (head(s, 60), s.get("kind"), s.get("urgency")))
    print("报告已写：%s" % os.path.relpath(p, HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
