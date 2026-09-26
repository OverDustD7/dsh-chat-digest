# -*- coding: utf-8 -*-
r"""本地小模型跑**一整天**的提炼，再与 DSH 基线对账 —— 决定"能不能把'读+初提'交给本地"。

设计（对应"先小样本实测再定管线"）：
  · 把当天的分片按 --chunk 行切成块，逐块喂 Ollama qwen3.5:9b，让它挑出候选条目（同 local_extract_probe 的口径）；
  · 全部候选写 output\logs\_local_candidates_<date>.json；
  · 最后与 output\daily\<date>\items.json（DSH 基线）**双向对账**：
      覆盖率 ＝ 基线条目里有多少能被候选命中（6 字片段包含度 ≥0.4）；
      多出项 ＝ 候选里对不上基线的（可能是它发现的新东西，也可能是编造——列出前 20 条给人看）。
用法: python tools/local_full_probe.py --date 2026-09-14 [--chunk 150] [--max-chunks 0]
"""
import argparse
import glob
import io
import json
import os
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://127.0.0.1:11434/api/chat"
OUT = os.path.join(HERE, "output", "logs")

PROMPT = (
    "你是「聊天情报」的提炼助手。下面是一段微信群/QQ 消息（每行格式：- HH:MM [群] 人: 内容）。\n"
    "读者只有一个人：清华大一学生冯思韬。请挑出**对他有用**的条目。\n"
    "判据（三问，皆否就不收）：① 需要他做什么？② 会不会影响他？③ 他以后用得上吗？\n"
    "硬规矩：动作项（作业/截止/提交/上交/报名/问卷/小测/考试）**一律收**，不许因\"他可能已知\"而丢；"
    "群里的经验/踩坑/对课与平台的评价也收（kind=peer）；别人的私事、玩梗/复读/无观点闲聊不收；**不许编造**。\n"
    "只输出 JSON 数组，每项 {\"head\":\"≤40字\",\"kind\":\"todo|chance|official|peer|resource|life\",\"why\":\"≤30字\"}；没有就输出 []。\n\n消息：\n"
)


def ask(model, content, timeout=900):
    payload = {"model": model, "stream": False, "think": False,
               "messages": [{"role": "user", "content": content}],
               "options": {"temperature": 0.2, "num_ctx": 32768}}
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8"))
    return j, time.time() - t0


def norm(t):
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", str(t or ""))


def grams(t, n=6):
    t = norm(t)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))} if len(t) >= n else ({t} if t else set())


def cover(a, b):          # a 覆盖 b 的程度（b 的 n-gram 落在 a 里的比例）
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / float(len(gb)) if gb else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-09-14")
    ap.add_argument("--chunk", type=int, default=150)
    ap.add_argument("--max-chunks", type=int, default=0, help="0 = 不限")
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--compare-only", action="store_true",
                    help="跳过模型调用，直接用已落盘的候选做对账（改对账逻辑时用，省得重跑）")
    a = ap.parse_args()
    cand_file = os.path.join(OUT, "_local_candidates_%s.json" % a.date)
    if a.compare_only:
        if not os.path.exists(cand_file):
            print("没有已落盘的候选文件：%s" % cand_file)
            return 2
        cands = json.load(io.open(cand_file, encoding="utf-8"))
        print("（--compare-only）直接读回 %d 条候选：%s" % (len(cands), os.path.relpath(cand_file, HERE)))
        return compare(a.date, cands)
    days = os.path.join(HERE, "output", "days")
    files = sorted(p for p in glob.glob(os.path.join(days, "%s_slice*" % a.date))
                   if not p.endswith("_slices.md"))
    rows, per = [], []
    for f in files:
        n0 = len(rows)
        for ln in io.open(f, encoding="utf-8", errors="replace"):
            s = ln.rstrip("\n")
            if s.startswith("- "):
                rows.append(s)
        per.append((os.path.basename(f), len(rows) - n0))
    print("日期 %s ｜ 分片 %d 个 ｜ 语料 %d 行 ｜ 切块 %d 行" % (a.date, len(files), len(rows), a.chunk))
    for name, n in per:
        print("   %-44s %5d 行" % (name, n))
    chunks = [rows[i:i + a.chunk] for i in range(0, len(rows), a.chunk)]
    if a.max_chunks:
        chunks = chunks[:a.max_chunks]
    cands, t_all, tok_out = [], 0.0, 0
    for i, ch in enumerate(chunks, 1):
        body = PROMPT + "\n".join(ch)
        try:
            j, sec = ask(a.model, body)
        except Exception as e:                      # noqa: BLE001
            print("  块 %02d 失败：%s" % (i, e))
            continue
        txt = (j.get("message") or {}).get("content") or ""
        t_all += sec
        tok_out += int(j.get("eval_count") or 0)
        m = re.search(r"\[.*\]", txt, re.S)
        got = []
        if m:
            try:
                got = json.loads(m.group(0))
            except ValueError:
                got = []
        for it in got:
            if isinstance(it, dict) and it.get("head"):
                it["_chunk"] = i
                cands.append(it)
        print("  块 %02d/%02d  %3d 行  %5.1fs  → %2d 条  （累计 %d 条 / %.0fs）"
              % (i, len(chunks), len(ch), sec, len(got), len(cands), t_all))
    out = os.path.join(OUT, "_local_candidates_%s.json" % a.date)
    io.open(out, "w", encoding="utf-8", newline="\n").write(json.dumps(cands, ensure_ascii=False, indent=1))
    print("\n本地产出 %d 条候选 ｜ 总耗时 %.0f 秒（平均 %.1fs/块）｜ 输出 %d token ｜ **API 花费 0**"
          % (len(cands), t_all, t_all / max(1, len(chunks)), tok_out))
    print("落盘：%s" % os.path.relpath(out, HERE))

    base = os.path.join(HERE, "output", "daily", a.date, "items.json")
    if not os.path.exists(base):
        print("\n（无 DSH 基线 %s，跳过对账）" % os.path.relpath(base, HERE))
        return 0
    return compare(a.date, cands)


def compare(date, cands):
    """与 DSH 基线双向对账：① 基线覆盖率（本地有没有漏掉基线报过的）② 候选里对不上基线的（新发现 or 编造）。
    注意 `max(..., key=lambda t: t[0])`：分数相同时不能拿 dict 去比大小（2026-09-17 踩过 TypeError）。"""
    base = os.path.join(HERE, "output", "daily", date, "items.json")
    B = json.load(io.open(base, encoding="utf-8"))
    hit, miss = [], []
    for b in B:
        head = str(b.get("text") or "").split("\n")[0]
        best = max(((cover(str(c.get("head", "")) + str(c.get("why", "")), head), c) for c in cands),
                   key=lambda t: t[0]) if cands else (0, None)
        (hit if best[0] >= 0.4 else miss).append((head, best[0]))
    print("\n== 对账 DSH 基线（%d 条）==" % len(B))
    print("  覆盖（候选里有对得上的）：**%d/%d = %.0f%%**" % (len(hit), len(B), 100.0 * len(hit) / max(1, len(B))))
    for h, s in miss:
        print("    漏？ %s  （最高相似度 %.2f）" % (h[:60], s))
    others = []
    for c in cands:
        best = max((cover(str(b.get("text") or ""), str(c.get("head", "")) + str(c.get("why", ""))) for b in B), default=0)
        if best < 0.4:
            others.append(c)
    print("\n  候选里对不上基线的 %d 条（可能是新发现，也可能是编造，需人看）：" % len(others))
    for c in others[:30]:
        print("    [?] [%s] %s ｜ %s" % (c.get("kind"), str(c.get("head"))[:44], str(c.get("why"))[:28]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())