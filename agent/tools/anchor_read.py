# -*- coding: utf-8 -*-
r"""回原文核 —— 按锚点（分片文件 + 行号）把原文片段取出来看，**阶段 5 逐条核候选就靠它**。

为什么必须有它：本地模型会编造（实测把「秀钟6字班通知群」发的 SRT 立项写成「经管学院」），
所以本地候选**一律不许直接进条目** —— 每条都要用锚点回来核：核得上才留，核不上就丢或回原文找。
它同时是"某块模型返回 0 条，到底是真没有还是模型崩了"的判据。

用法：
  python tools\anchor_read.py 2026-09-16_slice04_units.md --range 153-302 --kw "作业|截止|提交|报名|问卷|小测|考试"
  python tools\anchor_read.py 2026-09-16_slice04_units.md --line 414 --before 3 --after 5
  python tools\anchor_read.py 2026-09-16_slice02_units.md --chunk 6 --chunk-size 150    # 按初提的块号取
参数里的文件名可以只给后缀（自动到 output\days\ 下找），也可以给相对/绝对路径。
"""
import argparse
import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAYS = os.path.join(HERE, "output", "days")
DEFAULT_KW = "作业|截止|提交|上交|ddl|DDL|报名|小测|考试|第\d+页|问卷|招募|征集|志愿者|选拔|观众|接龙|收集表|报名表|自主报名|填写|调研"


def resolve(name):
    for cand in (name, os.path.join(HERE, name), os.path.join(DAYS, name)):
        if os.path.exists(cand):
            return cand
    hit = glob.glob(os.path.join(DAYS, "*%s*" % name))
    if len(hit) == 1:
        return hit[0]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--line", type=int)
    ap.add_argument("--lines", help="逗号分隔的多个行号（一次核多条锚点）")
    ap.add_argument("--range", dest="rng")
    ap.add_argument("--chunk", type=int, help="初提的块号（1 起）")
    ap.add_argument("--chunk-size", type=int, default=150)
    ap.add_argument("--before", type=int, default=0)
    ap.add_argument("--after", type=int, default=0)
    ap.add_argument("--kw", default=None, help="只看命中这个正则的行（默认＝动作/机会词表）")
    ap.add_argument("--all", action="store_true", help="不过滤，全打（默认打前 40 行）")
    ap.add_argument("--max", type=int, default=60)
    a = ap.parse_args()
    p = resolve(a.file)
    if not p:
        print("找不到文件：%s" % a.file)
        return 2
    lines = io.open(p, encoding="utf-8", errors="replace").read().split("\n")
    body = [i for i, s in enumerate(lines, 1) if s.startswith("- ")]   # 只算消息行
    if a.chunk:
        lo = (a.chunk - 1) * a.chunk_size
        hi = a.chunk * a.chunk_size
        sel = [body[i] for i in range(lo, min(hi, len(body)))]
        # 块号 → 全局行号区间（与 local_prepass.py 的编号一致）
        print("（块 %d ＝ 本文件消息行 %d–%d ⇒ 文件行 %s–%s）"
              % (a.chunk, lo + 1, min(hi, len(body)), sel[0] if sel else "-", sel[-1] if sel else "-"))
    elif a.rng:
        lo, hi = [int(x) for x in a.rng.split("-")]
        sel = list(range(lo, hi + 1))
    elif a.lines:
        sel = [int(x) for x in a.lines.split(",") if x.strip()]
    elif a.line:
        sel = list(range(a.line - a.before, a.line + a.after + 1))
    else:
        sel = body[:40] if not a.all else body
    kw = re.compile(a.kw if a.kw is not None else (DEFAULT_KW if not a.all else r"."))
    n, hits = 0, 0
    print("== %s ｜ 共 %d 消息行 ｜ 取 %d 行 ==" % (os.path.relpath(p, HERE), len(body), len(sel)))
    for i in sel:
        if i < 1 or i > len(lines):
            continue
        s = lines[i - 1]
        n += 1
        if s.startswith("- ") and kw.search(s):
            hits += 1
            if hits <= a.max:
                print("L%d: %s" % (i, s[:400]))
    print("（扫 %d 行，命中 %d 行%s）" % (n, hits, "；只打前 %d 条" % a.max if hits > a.max else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())