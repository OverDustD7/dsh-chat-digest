# -*- coding: utf-8 -*-
"""embed_probe.py — 实测 bge-m3（本地 embedding）能不能担起"疑似已报匹配"与"共识簇候选"。

背景：用户让"自己评估后决定接不接"。中文语义归并我栽过三次（都因精度不够），所以**先量化再决定**。
测两件事（都用本地 bge-m3，零花费）：
  ① **疑似已报**：现有面板条目 × 当天随机单元 → 余弦相似 top-3。人工判"是不是真的同一件事"。
  ② **共识簇候选**：当天单元之间互相相似 → 贪心聚簇，列出 ≥3 成员的簇（人工判"是不是同一个话题/共识"）。
用法: python tools\\embed_probe.py [YYYY-MM-DD] [单元取样数=400] [每条的 topK=3]
产出: output/window/_embed_probe.md
"""
import io
import json
import math
import os
import random
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://127.0.0.1:11434/api/embed"
MODEL = "bge-m3:latest"


def embed(texts):
    out = []
    B = 16
    for i in range(0, len(texts), B):
        chunk = texts[i:i + B]
        payload = {"model": MODEL, "input": chunk}
        req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
        out.extend(j.get("embeddings") or [])
    return out


def cos(a, b):
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return s / (na * nb) if na and nb else 0.0


def load_units(date, n, seed=20260914):
    p = os.path.join(HERE, "output", "days", "%s_units.md" % date)
    if not os.path.exists(p):
        return None
    rows = []
    for l in io.open(p, encoding="utf-8", errors="replace"):
        l = l.strip()
        if l.startswith("- "):
            l = l[2:]
            m = re.match(r"^\d\d:\d\d\s+(\[[^\]]*\]\s*)*\[([^\]]+)\]\s*[^:]{0,20}:\s*(.*)$", l)
            txt = m.group(3) if m else l
            if len(txt) >= 12:                    # 太短的没有语义价值
                rows.append(txt)
    random.Random(seed).shuffle(rows)
    return rows[:n]


def load_items():
    p = os.path.join(HERE, "docs", "信息列表.md")
    if not os.path.exists(p):
        return []
    out = []
    for l in io.open(p, encoding="utf-8", errors="replace"):
        l = l.strip()
        if re.match(r"^- \[[ x]\]", l):
            t = re.sub(r"^- \[[ x]\]\s*", "", l)
            t = re.sub(r"\*\*【新】\*\*\s*", "", t).strip()
            if t:
                out.append(t[:160])
    return out


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-09-13"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    k = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    units = load_units(date, n)
    items = load_items()
    if not units or not items:
        print("缺 units(%s) 或 items(%d)" % (bool(units), len(items)))
        return 1
    print("单元 %d ｜ 现有条目 %d → 开始算 embedding（本地 bge-m3）" % (len(units), len(items)))
    vu = embed(units)
    vi = embed(items)
    L = ["# bge-m3 精度实测（%s，单元取样 %d / 条目 %d）" % (date, len(units), len(items)), "",
         "## 一、疑似已报匹配（每条现成条目 → 当天最相似的 %d 个单元）" % k, ""]
    for it, vec in zip(items, vi):
        sims = sorted(((cos(vec, u), t) for u, t in zip(vu, units)), reverse=True)[:k]
        L.append("- **%s**" % it)
        for s, u in sims:
            L.append("  - %.3f ｜ %s" % (s, u[:110]))
    L += ["", "## 二、当天单元的相似簇（≥3 成员，可能是同一话题/共识）", ""]
    # 贪心聚簇：按相似度把单元并到已有簇（阈值 0.80）
    TH = 0.80
    clusters = []
    for i, v in enumerate(vu):
        placed = False
        for c in clusters:
            if cos(v, c["v"]) >= TH:
                c["m"].append(units[i])
                placed = True
                break
        if not placed:
            clusters.append({"v": v, "m": [units[i]]})
    big = sorted([c for c in clusters if len(c["m"]) >= 3], key=lambda c: -len(c["m"]))[:12]
    L.append("（阈值 %.2f，共 %d 簇，其中 ≥3 成员 %d 簇，列前 %d）" % (TH, len(clusters), len([c for c in clusters if len(c["m"]) >= 3]), len(big)))
    L.append("")
    for c in big:
        L.append("- **%d 条**：" % len(c["m"]))
        for m in c["m"][:4]:
            L.append("  - %s" % m[:100])
    io.open(os.path.join(HERE, "output", "window", "_embed_probe.md"), "w",
            encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
    print("OK -> output/window/_embed_probe.md（%d 簇，≥3 成员 %d 簇）" % (len(clusters), len(big)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
