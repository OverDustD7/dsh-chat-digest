# -*- coding: utf-8 -*-
r"""阶段 2 的自检 —— 本地初提产物（`<date>_candidates.json`）到底靠不靠得住。

为什么要它：本地模型省钱但**会编造**，而"编造"不会自己喊出来。这个脚本只做**客观可判**的检查，
判不了的（"这条到底有没有用"）留给阶段 5 人/云端筛，别的都不许在这里下结论。

六项检查（**每一项都必须打印，不许静默跳过** —— 2026-09-15 的教训：条件式自检遇空列表会假装 OK）：
  1 分块完整性：应有的块 / 已落盘的块（缺块 = 有语料没读）
  2 语料覆盖：语料行数 vs 分片口径（是否与覆盖自检同一批文件）
  3 锚点完整性：无锚点条数、**引用了不存在行号**（`_badLines`）的条数
  4 锚点真实性：把每条锚点**回原文重读**，与落盘时记的原文片段逐字比（防漂移/防伪造）
  5 密度异常：每块候选数（0 条或特别多的块要看一眼）
  6 与基线对账（有 `output\daily\<date>\items.json` 才做）：n-gram 覆盖 —— **只是线索，不是判据**
     （2026-09-17 实测：同一份候选，n-gram 算 0/14，人工核至少 13/14。短句在数学上覆盖不了长句。）

用法：python tools\prepass_audit.py 2026-09-16 [--tag tail] [--chunk 150] [--baseline-skip]
"""
import argparse
import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAYS = os.path.join(HERE, "output", "days")
LOGS = os.path.join(HERE, "output", "logs")
ROW = re.compile(r"^- \d\d:\d\d\s")


def corpus_rows(files):
    n = 0
    for f in files:
        for ln in io.open(f, encoding="utf-8", errors="replace"):
            if ROW.match(ln.rstrip("\n")):
                n += 1
    return n


def norm(t):
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", str(t or ""))


def grams(t, n=6):
    t = norm(t)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))} if len(t) >= n else ({t} if t else set())


def cover(a, b):
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / float(len(gb)) if gb else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--tag", default="")
    ap.add_argument("--chunk", type=int, default=150)
    ap.add_argument("--baseline-skip", action="store_true", help="不做基线对账（基线本身可疑时用）")
    a = ap.parse_args()
    sfx = ("_" + a.tag) if a.tag else ""
    cpath = os.path.join(DAYS, "%s_candidates%s.json" % (a.date, sfx))
    if not os.path.exists(cpath):
        print("MISSING %s（先跑 tools\\local_prepass.py %s%s）" % (os.path.relpath(cpath, HERE), a.date,
                                                                  (" --tag " + a.tag) if a.tag else ""))
        return 2
    cands = json.load(io.open(cpath, encoding="utf-8"))
    files = sorted(p for p in glob.glob(os.path.join(DAYS, "%s_slice*" % a.date)) if not p.endswith("_slices.md"))
    # 2026-09-20：**优先读 local_prepass 写下的本次口径**（sidecar meta）。
    #   为什么：原来只按"当天全部分片"算应有块数 —— 增量轮（--include/--only-include）只读一部分语料，
    #   却被按全天算 ⇒ 每次都误报"缺 N 块"（KNOWN_ISSUES #131）。没有 sidecar 时退回旧口径（向后兼容）。
    mpath = os.path.join(DAYS, "%s_candidates%s.meta.json" % (a.date, sfx))
    meta = None
    if os.path.exists(mpath):
        try:
            meta = json.load(io.open(mpath, encoding="utf-8"))
        except Exception:
            meta = None
    if meta and meta.get("rows"):
        rows = int(meta["rows"])
        expect_chunks = int(meta.get("chunks") or ((rows + a.chunk - 1) // a.chunk))
        scope = "本次语料"
    else:
        rows = corpus_rows(files)
        expect_chunks = (rows + a.chunk - 1) // a.chunk
        scope = "当天全部分片（无 meta，退回旧口径）"
    cdir = os.path.join(LOGS, "_prepass_%s%s" % (a.date, sfx))
    disk = sorted(glob.glob(os.path.join(cdir, "chunk*.json"))) if os.path.isdir(cdir) else []
    L, bad = [], 0

    def say(s):
        print(s)
        L.append(s)

    L.append("# %s 本地初提 · 阶段 2 自检%s" % (a.date, ("（tag=%s）" % a.tag) if a.tag else ""))
    L.append("")
    say("== 1 分块完整性 ==")
    say("   语料 %d 行（%s）｜ 每块 %d 行 ⇒ 应有 %d 块 ｜ 已落盘 %d 块" % (rows, scope, a.chunk, expect_chunks, len(disk)))
    if len(disk) < expect_chunks:
        bad += 1
        say("   **缺块**：%d 块没读（有语料没进模型）—— 补跑 tools\\local_prepass.py %s --resume"
            % (expect_chunks - len(disk), a.date))
    else:
        say("   分块完整（无未读语料）")

    say("")
    say("== 2 语料覆盖 ==")
    say("   取语料文件 %d 个：%s" % (len(files), ", ".join(os.path.basename(f) for f in files)))
    others = [p for p in sorted(glob.glob(os.path.join(DAYS, "%s_slice*" % a.date))) if p.endswith("_slices.md")]
    say("   注：`%s_slices.md` 是索引（%d 个），按 `check_corpus_coverage.py` 口径不计入语料行"
        % (a.date, len(others)))

    say("")
    say("== 3 锚点完整性 ==")
    unanch = [c for c in cands if c.get("_unanchored")]
    withbad = [c for c in cands if c.get("_badLines")]
    say("   候选 %d 条 ｜ 无锚点 %d 条 ｜ 引用了不存在行号 %d 条" % (len(cands), len(unanch), len(withbad)))
    for c in unanch[:15]:
        say("     [无锚] %s" % str(c.get("head"))[:60])
    for c in withbad[:15]:
        say("     [坏行号 %s] %s" % (c["_badLines"], str(c.get("head"))[:50]))
    if unanch or withbad:
        bad += 1
        say("   ⇒ 这些**不许直接进条目**：阶段 5 要么回原文找到出处，要么丢。")

    say("")
    say("== 4 锚点真实性（回原文重读逐字比）==")
    tot_a, drift, missing = 0, [], []
    for c in cands:
        for an in c.get("_anchors") or []:
            tot_a += 1
            p = os.path.join(HERE, an["file"])
            if not os.path.exists(p):
                missing.append((an, c))
                continue
            lines = io.open(p, encoding="utf-8", errors="replace").read().split("\n")
            i = int(an["line"]) - 1
            if i < 0 or i >= len(lines):
                missing.append((an, c))
                continue
            got = lines[i]
            if not got.startswith("- "):
                drift.append((an, c, got[:80]))
            elif an.get("snippet") and an["snippet"][:60] not in got:
                drift.append((an, c, got[:80]))
    say("   锚点 %d 个 ｜ 回读对得上 %d ｜ **对不上 %d** ｜ 文件/行号不存在 %d"
        % (tot_a, tot_a - len(drift) - len(missing), len(drift), len(missing)))
    for an, c, got in drift[:10]:
        say("     [漂移] %s:%s ← 原文「%s」" % (an["src"], an["line"], got))
    for an, c in missing[:10]:
        say("     [不存在] %s:%s" % (an.get("file"), an.get("line")))
    if drift or missing:
        bad += 1

    say("")
    say("== 5 密度异常（每块候选数）==")
    per = {}
    for c in cands:
        per[c.get("_chunk")] = per.get(c.get("_chunk"), 0) + 1
    zero = [i for i in range(1, expect_chunks + 1) if per.get(i, 0) == 0]
    say("   有候选的块 %d/%d ｜ 0 条的块 %s" % (len([i for i in per if per[i]]), expect_chunks, zero or "无"))
    if zero:
        say("   （0 条可能是真的没有内容，也可能是模型崩了；看一眼那块的原文再判）")
    say("   每块：%s" % ", ".join("%d:%d" % (i, per.get(i, 0)) for i in range(1, expect_chunks + 1)))
    kd = {}
    for c in cands:
        kd[c.get("kind")] = kd.get(c.get("kind"), 0) + 1
    say("   分类分布：%s" % ", ".join("%s %d" % (k, v) for k, v in sorted(kd.items(), key=lambda t: -t[1])))

    say("")
    say("== 6 与基线对账（**n-gram 只是线索，不是判据**）==")
    base = os.path.join(HERE, "output", "daily", a.date, "items.json")
    if a.baseline_skip or not os.path.exists(base):
        say("   跳过（%s）" % ("--baseline-skip" if a.baseline_skip else "无基线 items.json"))
    else:
        B = json.load(io.open(base, encoding="utf-8"))
        hit = []
        for b in B:
            head = str(b.get("text") or b.get("head") or "").split("\n")[0]
            best = max((cover(str(c.get("head", "")) + str(c.get("why", "")), head) for c in cands), default=0)
            hit.append((head, best))
        n = len([1 for _, s in hit if s >= 0.4])
        say("   基线条目 %d 条 ｜ n-gram 认为覆盖 %d 条（%.0f%%）" % (len(B), n, 100.0 * n / max(1, len(B))))
        for h, s in hit:
            if s < 0.4:
                say("     n-gram 说漏？ %s（%.2f）" % (h[:52], s))
        say("   ⇒ **这一节只用来找「值得人工看一眼」的条目**；判覆盖率必须人工抽检。")

    L.append("")
    L.append("**结论：%s**（FAIL 项 %d）" % ("有需要处理的问题" if bad else "六项通过", bad))
    out = os.path.join(DAYS, "%s_prepass_audit%s.md" % (a.date, sfx))
    io.open(out, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
    print("\n自检视图：%s" % os.path.relpath(out, HERE))
    print("FAIL 项：%d" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())