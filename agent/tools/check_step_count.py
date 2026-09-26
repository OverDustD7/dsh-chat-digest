# -*- coding: utf-8 -*-
"""check_step_count.py — 管线步数口径自检（治"数字写死在文档里然后腐烂"）。

用法:
    python tools\\check_step_count.py            # 检查并打印
    python tools\\check_step_count.py --fix-hint  # 额外给出建议改法

权威口径（**只有这两个，别的都是抄的**）:
  A. `scripts\\daily_prep.py` 里 `run(...)` 的调用次数（注意第 6 步写作 `s6 = run(...)`，只数
     `steps.append(run(` 会漏一个）；
  B. 最新一份 `output\\daily\\<date>\\prep_report.md` 的表格数据行数（**实际跑出来的行数**）。

然后扫"活文档"里**现状式**的步数断言（`现 N 步` / `当前 N 步` / `内部 N 步` / `（**N 步**）`），
与权威值不一致就报 WARN 并非零退出。

为什么不扫历史文件：`HANDOFF-2026-09-1x-*.md`、`docs\\archive\\*`、`chat-feed\\STATUS.md`、
`EVOLUTION.md` 是**日志**（记录当时是多少步），改它们等于篡改历史；本工具只盯"会被当成现状读"的文档。
`knowledge\\lessons.md` 里"那是 11 步时代"这种**带历史标记**的句子也不报。

背景（2026-09-15）：文档里长期写着"19 步"，实际 `prep_report.md` 已经是 **21 行**（3i-b 与
3k-b 加进去后没人更新数字）。所以规范应当是"以产物行数为准"，而不是在文档里再抄一个数。
"""
import glob
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 只扫"会被当成现状读"的文件（相对 ROOT）。历史/日志类一律不扫。
LIVE = [
    os.path.join("scripts", "daily_prep.py"),
    os.path.join("docs", "MAIN_AGENT_SPEC.md"),
    os.path.join("docs", "agent", "WORKING.md"),
    os.path.join("docs", "INDEX.md"),
    os.path.join("docs", "DEV_NOTES.md"),
    os.path.join("docs", "PLUGIN_BLUEPRINT.md"),
    os.path.join("docs", "guidelines.md"),
    os.path.join("docs", "output_format.md"),
    os.path.join("docs", "knowledge", "lessons.md"),
    os.path.join("docs", "knowledge", "channels.md"),
    os.path.join("docs", "knowledge", "preferences.md"),
]

# 现状式断言（历史句如"那是 11 步时代"不匹配）
PATTERNS = [
    re.compile(r"(?:现|现在|当前|内部)\s*(?:是)?\s*\*{0,2}(\d{1,2})\s*步"),
    re.compile(r"（\*\*(\d{1,2})\s*步\*\*"),
    re.compile(r"\*\*(\d{1,2}) 步\*\*管线"),
    # "**19 个计时步骤**" 这种变体（2026-09-15 实测漏网过一次）
    re.compile(r"(\d{1,2})\s*个?(?:计时)?步骤"),
]
# 命中处**附近**出现这些词＝在讲历史，不算现状断言。
# （为什么看附近而不是整行：`INDEX.md` 有一行同时写着"现 19 步"和"那是 11 步时代"，
#   整行过滤会把真问题一起放过 —— 2026-09-15 实测踩到。）
HIST_MARK = ("步时代", "当时", "历史", "曾经", "变成", "→", "改为", "改成", "旧")
HIST_WINDOW = 14

#: **带日期的标题＝历史小节**，其正文整段跳过。
#: 为什么需要：`WORKING.md` 里既有"现状章节"也有大量「## 十一octies、2026-09-14 分片全覆盖轮」
#: 这种带日期的轮次记录；后者写"当时跑了 17 个计时步骤"是对的，不该报（2026-09-15 实测）。
DATED_HEADING = re.compile(r"^#{2,3}\s*.*20\d\d-\d\d-\d\d")


def count_run_calls():
    """只数"真的调用一步"的地方：`steps.append(run(…)` 与 `sN = run(…)`。

    别用 `run\\(` 裸数 —— 会多算 `def run(`、`subprocess.run(`（虽然负向断言能挡掉这个）和
    docstring 里那句 `run(...)`（2026-09-15 实测：裸数得 23，真值 21）。
    """
    src = open(os.path.join(ROOT, "scripts", "daily_prep.py"), encoding="utf-8").read()
    return len(re.findall(r"(?:steps\.append\(|=)\s*run\(", src))


def count_report_rows():
    reports = sorted(glob.glob(os.path.join(ROOT, "output", "daily", "*", "prep_report.md")))
    if not reports:
        return None, None
    newest = reports[-1]
    n = 0
    with open(newest, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith("|") and not s.startswith("| 步骤") and not set(s) <= set("|- "):
                n += 1
    return n, newest


def main():
    n_run = count_run_calls()
    n_rows, newest = count_report_rows()
    print("权威口径 A（daily_prep.py 的 run( 调用数） = %d" % n_run)
    print("权威口径 B（最新 prep_report.md 表行数） = %s  ← %s"
          % (n_rows, os.path.relpath(newest, ROOT) if newest else "(没有报告)"))

    if n_rows is not None and n_run != n_rows:
        print("  **两个口径不一致** —— 先查是不是有步骤没走 run(...) / 报告被改过")

    expect = {n_run, n_rows} - {None}
    bad = []
    for rel in LIVE:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            in_dated = False
            for i, line in enumerate(f, 1):
                if line.startswith("#"):
                    in_dated = bool(DATED_HEADING.match(line))
                    continue
                if in_dated:
                    continue
                for pat in PATTERNS:
                    for m in pat.finditer(line):
                        near = line[max(0, m.start() - HIST_WINDOW): m.end() + HIST_WINDOW]
                        if any(mk in near for mk in HIST_MARK):
                            continue
                        v = int(m.group(1))
                        if v not in expect:
                            bad.append((rel, i, v, line.strip()[:110]))

    if bad:
        print("\n**过时的步数断言 %d 处**（文档里的数 ≠ 权威值 %s）：" % (len(bad), sorted(expect)))
        for rel, i, v, txt in bad:
            print("  %s:%d  写的是 %d 步\n      %s" % (rel, i, v, txt))
        print("\n口径：不要写死步数 —— 写「以 `prep_report.md` 的表行数为准（当前 %d）」。" % n_run)
        return 1

    print("\nOK：活文档里没有过时的现状式步数断言（权威值 %s）" % sorted(expect))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
