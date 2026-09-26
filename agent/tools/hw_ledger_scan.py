# -*- coding: utf-8 -*-
r"""hw_ledger_scan.py —— 动作项机械扫描（硬性纪律 12 指定的 `rg -N "作业|截止|…"` 的本机等价物）。

为什么需要：本机**没有 `rg` 可执行文件**（`rg : The term 'rg' is not recognized...`），
而 `output_format.md` 硬性纪律 12 要求对当天语料做一次机械扫描、并让每条命中都有台账处置。
本脚本用 Python 正则完成同一件事，输出一份**可逐行核对**的清单（含文件、时间、原文）。

用法:
    python tools\hw_ledger_scan.py 2026-09-14
    python tools\hw_ledger_scan.py --file output\days\2026-09-13_tail_2346.md
产出: output\days\<date>_action_scan.md（每个文件的命中数 + 全部命中行）
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 动作项（硬性纪律 12 的原词表）
PAT = re.compile(r"作业|截止|提交|上交|ddl|DDL|报名|小测|考试|第\d+页")
# 机会项（2026-09-15 晚新增）：**用户报的漏报正是落在这个盲区里** ——
#   AI 大赛那条消息里的「**招募问卷**」（参与清小搭团队 / AI 生态建设 / 赛事筹办）
#   以及「观众招募」「志愿者招募」「征集」这类，原词表里**一个都没有**。
#   与 PAT 分开成两节输出，是为了让两类各自都被逐条处置，而不是混在一堆里被顺手划掉。
PAT_CHANCE = re.compile(r"问卷|招募|征集|志愿者|选拔|观众|接龙|收集表|报名表|自主报名|填写|调研")
DEFAULT = ["%s_units.md", "%s_slice01_units.md", "%s_slice02_units.md", "%s_slice03_units.md",
           "%s_slice04_units.md", "%s_slice05_units.md", "%s_slice06_units.md"]


def day_files(date):
    """当天要扫的语料：units.md + **实际存在的**所有分片。

    2026-09-15 修：原来只按 `%s_slice0N_units.md` 拼死名单，而分片命名在不同轮次里变过
    （09-13 那批叫 `2026-09-13_slice01_清华大学2026级新.md`，带群名）→ **09-13 的分片一个都没扫到**，
    自检却因为"扫了 1 个文件"而看着正常。改成 glob `<date>_slice*`，并存一份文件清单进产出，便于自证。
    """
    import glob
    hits = [os.path.join(HERE, "output", "days", p % date) for p in DEFAULT]
    hits = [p for p in hits if os.path.exists(p)]
    globbed = sorted(glob.glob(os.path.join(HERE, "output", "days", "%s_slice*" % date)))
    for g in globbed:
        if g not in hits and not g.endswith("_slices.md"):
            hits.append(g)
    return hits


def scan(path):
    if not os.path.exists(path):
        return None
    acts, chances = [], []
    for i, ln in enumerate(io.open(path, encoding="utf-8", errors="replace"), 1):
        ln = ln.rstrip("\n")
        if PAT.search(ln):
            acts.append((i, ln))
        elif PAT_CHANCE.search(ln):
            # elif：已被动作项命中的行不再重复列（同一行两节都出现会让人以为有两条）
            chances.append((i, ln))
    return acts, chances


def main(argv):
    d = os.path.join(HERE, "output", "days")
    if argv and argv[0] == "--file":
        files = [os.path.join(HERE, argv[1]) if not os.path.isabs(argv[1]) else argv[1]]
        tag = os.path.basename(argv[1]).replace(".md", "")
    else:
        date = argv[0] if argv else "2026-09-14"
        files = day_files(date)
        tag = date
    res = [(p, scan(p)) for p in files]
    res = [(p, r) for p, r in res if r is not None]
    out = os.path.join(d, "%s_action_scan.md" % tag)
    t_act = t_chan = 0
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("# %s 动作项 / 机会项 机械扫描\n\n" % tag)
        f.write("- 动作项正则（硬性纪律 12）：`%s`\n" % PAT.pattern)
        f.write("- 机会项正则（硬性纪律 13）：`%s`\n" % PAT_CHANCE.pattern)
        f.write("> 用法：**每条命中都要有台账处置**（进了哪条 / 为什么不进）；理由里不许出现「他可能已知」。\n"
                "> 机会项命中默认进 **二、机会与招募**；需要他在某个时刻做一次动作的才进待办。\n\n")
        for p, (acts, chances) in res:
            f.write("## %s —— 动作 %d 条 / 机会 %d 条\n\n" % (os.path.basename(p), len(acts), len(chances)))
            t_act += len(acts)
            t_chan += len(chances)
            for i, ln in acts:
                f.write("- [动作] L%d ｜ %s\n" % (i, ln[:200]))
            for i, ln in chances:
                f.write("- [机会] L%d ｜ %s\n" % (i, ln[:200]))
            f.write("\n")
        f.write("**合计 动作 %d 条 / 机会 %d 条（%d 个文件）**\n" % (t_act, t_chan, len(res)))
    print("wrote %s ｜ 动作 %d 条 / 机会 %d 条 / %d 个文件" % (out, t_act, t_chan, len(res)))
    for p, (acts, chances) in res:
        print("  %-46s 动作 %-4d 机会 %d" % (os.path.basename(p), len(acts), len(chances)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
