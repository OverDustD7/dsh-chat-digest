# -*- coding: utf-8 -*-
r"""本地小模型能不能扛"读切片 → 初提条目"？—— 小样本实测（质量 + 延迟）。

为什么要先试：用户明确要求「能用本地小模型干的就用本地干」，且「先跑小样本做质量与延迟实测再定管线」。
本脚本只做一件事：拿 **09-14 的第 1 片**里的一小段（默认 60 行）喂给 Ollama `qwen3.5:9b`，
让它按三问挑出"对冯思韬有用的条目"，然后打印：耗时、token 数、它挑出来的东西。
**质量怎么判**：把它的产出与 DSH 那一轮的 `output\daily\2026-09-14\items.json`（14 条基线）
按关键词对照，看有没有"该收没收/编造"。

用法: python tools\local_extract_probe.py [--rows 60] [--slice output\days\2026-09-14_slice01_units.md]
"""
import argparse
import io
import json
import os
import re
import time
import urllib.request

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://127.0.0.1:11434/api/chat"

PROMPT = (
    "你是「聊天情报」的提炼助手。下面是一段微信群/QQ 消息（每行格式：- HH:MM [群] 人: 内容）。\n"
    "读者只有一个人：清华大一学生冯思韬。请挑出**对他有用**的条目。\n"
    "判据（三问，皆否就**不收**）：① 需要他做什么？② 会不会影响他？③ 他以后用得上吗？\n"
    "硬规矩：\n"
    "- 动作项（要他做一次动作的：作业/截止/提交/上交/报名/问卷/小测/考试）**一律收**，"
    "**不许因为\"他可能已经知道\"就不收**；\n"
    "- 群里的经验、踩过的坑、对课/老师/平台的集体评价也收（kind 用 peer）；\n"
    "- 别人的私事、无观点闲聊/玩梗/复读**不收**；\n"
    "- **不许编造**消息里没有的信息（人名/时间/链接尤其）。\n"
    "只输出一个 JSON 数组，每项："
    '{"head":"一句话（≤40字）","kind":"todo|chance|official|peer|resource|life","why":"为什么对他有用（≤30字）"}。\n'
    "没有可收的就输出 []。\n\n消息：\n"
)


def pick_rows(path, n):
    rows = []
    for ln in io.open(path, encoding="utf-8", errors="replace"):
        s = ln.rstrip("\n")
        if s.startswith("- "):
            rows.append(s)
        if len(rows) >= n:
            break
    return rows


def ask(model, messages, timeout=600):
    payload = {"model": model, "stream": False, "think": False, "messages": messages,
               "options": {"temperature": 0.2, "num_ctx": 32768}}
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8"))
    return j, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=60)
    ap.add_argument("--slice", default=os.path.join("output", "days", "2026-09-14_slice01_units.md"))
    ap.add_argument("--model", default="qwen3.5:9b")
    a = ap.parse_args()
    p = a.slice if os.path.isabs(a.slice) else os.path.join(HERE, a.slice)
    if not os.path.exists(p):
        print("缺切片：%s" % p)
        return 2
    rows = pick_rows(p, a.rows)
    body = PROMPT + "\n".join(rows)
    print("切片：%s ｜ 取 %d 行 ｜ 提示词 %d 字符（≈%d token）｜ 模型 %s"
          % (os.path.basename(p), len(rows), len(body), len(body) // 2, a.model))
    j, sec = ask(a.model, [{"role": "user", "content": body}])
    txt = (j.get("message") or {}).get("content") or ""
    print("耗时 **%.1f 秒** ｜ prompt_eval=%s ｜ eval=%s ｜ 输出 %d 字符"
          % (sec, j.get("prompt_eval_count"), j.get("eval_count"), len(txt)))
    items = None
    m = re.search(r"\[.*\]", txt, re.S)
    if m:
        try:
            items = json.loads(m.group(0))
        except ValueError:
            items = None
    if items is None:
        print("\n!! 输出不是合法 JSON 数组，原文前 600 字：\n%s" % txt[:600])
        return 1
    print("\n它挑出 %d 条：" % len(items))
    for it in items:
        print("  [%-8s] %s  ｜ %s" % (it.get("kind"), str(it.get("head"))[:46], str(it.get("why"))[:34]))
    # 与 09-14 基线对照（关键词层面）
    base = os.path.join(HERE, "output", "daily", "2026-09-14", "items.json")
    if os.path.exists(base):
        B = json.load(io.open(base, encoding="utf-8"))
        print("\n对照 DSH 09-14 基线（%d 条）——看它们在这段里有没有东西是基线报过的：" % len(B))
        blob = "\n".join(rows)
        for b in B:
            head = str(b.get("text") or "").split("\n")[0]
            key = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", head)[:6]
            hit = bool(key) and key in re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", blob)
            print("  %s %s" % ("本段有" if hit else "本段无", head[:56]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())