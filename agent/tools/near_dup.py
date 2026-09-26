# -*- coding: utf-8 -*-
"""near_dup.py — 用本地 bge-m3 找**近重复**（同一内容被转发/复读多次，但有一两字差异）。

评估结论（2026-09-14，用户让"自己评估后决定接不接"）：
  · **不接**"疑似已报匹配"：绝对分数不可分（0.624 既是命中也误报），固定阈值必漏或必噪。
  · **不接**"共识簇自动判定"：0.80 阈值下 400 单元出 366 簇、仅 5 个 ≥3，且多是"同一广告转发两次"。
  · **只接这个**：**高阈值近重复去重**（cos ≥ 0.93 且规范化长度 ≥ 20）—— 可精确判定、纯机械收益、不误伤语义。
    它补的正是 `units_day.py` 精确去重抓不住的情况（两份文案有一处不同）。

用法: python tools\\near_dup.py [YYYY-MM-DD] [阈值=0.93]
产出: output/days/<date>_near_dup.md（每组的成员 + 建议保留哪条），控制台给 ASCII 统计（不自动改产物）。
"""
import io
import json
import math
import os
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://127.0.0.1:11434/api/embed"
MODEL = "bge-m3:latest"


def embed(texts):
    out = []
    for i in range(0, len(texts), 16):
        chunk = texts[i:i + 16]
        payload = {"model": MODEL, "input": chunk}
        req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            out.extend((json.loads(r.read().decode("utf-8", "replace")).get("embeddings")) or [])
        if (i // 16) % 20 == 0:
            print("  embedded %d/%d" % (min(i + 16, len(texts)), len(texts)))
    return out


def cos(a, b):
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return s / (na * nb) if na and nb else 0.0


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-09-13"
    TH = float(sys.argv[2]) if len(sys.argv) > 2 else 0.93
    p = os.path.join(HERE, "output", "days", "%s_units.md" % date)
    units = []
    for l in io.open(p, encoding="utf-8", errors="replace"):
        l = l.rstrip("\n")
        if l.startswith("- "):
            body = l[2:]
            m = re.match(r"^\d\d:\d\d\s+(\[[^\]]*\]\s*)*\[([^\]]+)\]\s*[^:]{0,20}:\s*(.*)$", body)
            units.append((m.group(2) if m else "?", m.group(3) if m else body, body))
    txt = [(u[1] or "") for u in units]
    print("单元 %d ｜ 阈值 %.2f ｜ 开始算 embedding（本地 bge-m3）" % (len(units), TH))
    V = embed(txt)
    if len(V) != len(txt):
        print("embedding 数不匹配（%d vs %d）" % (len(V), len(txt)))
        return 1
    n = len(txt)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pairs = 0
    for i in range(n):
        if len(re.sub(r"\W", "", txt[i])) < 20:
            continue
        for j in range(i + 1, n):
            if len(re.sub(r"\W", "", txt[j])) < 20:
                continue
            if cos(V[i], V[j]) >= TH:
                a, b = find(i), find(j)
                if a != b:
                    parent[max(a, b)] = min(a, b)
                pairs += 1
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    dup = sorted([g for g in groups.values() if len(g) > 1], key=lambda g: -len(g))
    L = ["# %s 近重复组（bge-m3，阈值 %.2f，规范化长度 ≥20）" % (date, TH), "",
         "> 共 %d 单元 ｜ 近重复组 **%d** 组 ｜ 命中对 %d ｜ 可省 %d 条"
         % (n, len(dup), pairs, sum(len(g) - 1 for g in dup)), "",
         "> 用途：这些是「同一内容被转发/复读多次、但文案有一两处不同」的情况（精确去重抓不住）。",
         "> 同组建议只留**时间最早**那条，其余只计次数。", ""]
    for g in dup[:40]:
        L.append("- **%d 条**（建议留最早 `%s`）" % (len(g), units[g[0]][2][:80]))
        for i in g:
            L.append("  - %s" % units[i][2][:150])
    io.open(os.path.join(HERE, "output", "days", "%s_near_dup.md" % date), "w",
            encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
    print("OK groups=%d pairs=%d saveable=%d -> output/days/%s_near_dup.md"
          % (len(dup), pairs, sum(len(g) - 1 for g in dup), date))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
