# -*- coding: utf-8 -*-
r"""audit_promises.py — 通读权威文档，把「承诺了但没实现 / 还没做完」的东西扫出来（2026-09-15）。

起因（用户原话）：「**还有什么要改的，通读文档，看那些像这样一样没有实现**」
—— "这样"＝「每天检查有没有有价值的公众号作者」这种**用户提过、文档里也写了、却从来没有落地的东西**。
同一天已经栽两次（动作项被当"已知"滤掉、公众号作者检查漏了两周），所以把它做成一条命令。

扫三类信号：
  ① **未完成的措辞**（tier1）：`未实现 | 未做 | 尚未 | 待补 | 待接入 | 待实现 | 未接进 | 未纳入 | 没纳入 | 未验证 | 待验证 | TODO | 待定 | 待修`
  ② **KNOWN_ISSUES 里状态不是 ✅ 的行**（待修/观察/补做中/已改待重启…）—— 天然就是"没做完"的清单
  ③ **文档里的「待办 / 待补充 / 下一步」小节**

用法: python tools\audit_promises.py [--out output\window\_promises_audit.md]
"""
import argparse
import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(HERE, "docs")

TIER1 = re.compile(r"未实现|未做|尚未|待补|待接入|待实现|未接进|未纳入|没纳入|未验证|待验证|TODO|待定|待修|还没|待建|未建")
TIER2 = re.compile(r"建议|应该|计划|下次|以后|将来|待确认")
SKIP = re.compile(r"\.before-|archive[\\/]|_merge_check|before-3j|before-")

FILES = ["MAIN_AGENT_SPEC.md", "agent/WORKING.md", "output_format.md", "guidelines.md",
         "task_daily_template.md", "INDEX.md", "EVOLUTION.md", "KNOWN_ISSUES.md",
         "DEV_NOTES.md", "resources.md", "PLUGIN_BLUEPRINT.md",
         "knowledge/lessons.md", "knowledge/official_accounts.md", "knowledge/preferences.md",
         "knowledge/people.md", "knowledge/channels.md"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "output", "window", "_promises_audit.md"))
    a = ap.parse_args()

    hits, t2 = [], {}
    for rel in FILES:
        p = os.path.join(DOCS, rel.replace("/", os.sep))
        if not os.path.exists(p):
            hits.append((rel, 0, "（文件不存在）"))
            continue
        for i, ln in enumerate(io.open(p, encoding="utf-8", errors="replace"), 1):
            s = ln.rstrip()
            if not s.strip():
                continue
            if TIER1.search(s):
                hits.append((rel, i, s.strip()[:200]))
            if TIER2.search(s):
                t2[rel] = t2.get(rel, 0) + 1

    # KNOWN_ISSUES 里状态列不是 ✅ 的
    open_rows = []
    kp = os.path.join(DOCS, "KNOWN_ISSUES.md")
    if os.path.exists(kp):
        for i, ln in enumerate(io.open(kp, encoding="utf-8", errors="replace"), 1):
            if not ln.strip().startswith("|"):
                continue
            cols = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cols) < 4 or cols[0] in ("#", "---") or set(cols[0]) <= {"-"}:
                continue
            st = cols[-2]
            if st and "✅" not in st:
                open_rows.append((cols[0], st[:18], cols[1][:70], i))

    lines = ["# 承诺 / 未完项审计（2026-09-15）", "",
             "> 用法：`python tools\\audit_promises.py` —— 扫权威文档里「未完成」的措辞 + KNOWN_ISSUES 里非 ✅ 的行。",
             "> 规矩：**每条规范里的承诺，要么有工具/管线步骤/断言，要么进这份清单**；两边都没有 = 迟早静默漏掉。", ""]
    lines.append("## 一、KNOWN_ISSUES 里状态不是 ✅ 的行（%d 条）" % len(open_rows))
    for num, st, title, i in open_rows:
        lines.append("- #%s [%s] %s" % (num, st, title))
    lines += ["", "## 二、文档里「未完成」措辞（tier1，%d 处）" % len(hits)]
    cur = None
    for rel, i, s in hits:
        if rel != cur:
            cur = rel
            lines.append("\n### %s" % rel)
        lines.append("- :%d %s" % (i, s))
    lines += ["", "## 三、弱信号计数（建议/应该/计划/下次/以后/待确认，仅供人工挑）"]
    for rel, c in sorted(t2.items(), key=lambda kv: -kv[1]):
        lines.append("- %-34s %d" % (rel, c))

    with io.open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print("KNOWN_ISSUES 未完成行：%d" % len(open_rows))
    for num, st, title, i in open_rows:
        print("   #%-3s [%-8s] %s" % (num, st, title[:70]))
    print("\ntier1 未完成措辞：%d 处（明细见文件）" % len(hits))
    print("清单 -> %s" % os.path.relpath(a.out, HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())