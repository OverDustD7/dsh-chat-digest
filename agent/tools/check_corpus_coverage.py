# -*- coding: utf-8 -*-
"""check_corpus_coverage.py — 语料覆盖自检（2026-09-15）。

为什么要有它（起因）：09-14 那轮 `_units_filtered.md` 只装了大群（`llm_filter.py --chat <群名>`），
而 `split_day.py` 靠"筛过哪些群"来补其余群，判据是**所有方括号内容**——`[卡片]`/`[问]` 这种标记
也会被当成"群名"，于是含这些标记的行被误排除出语料。语料不完整 → "分片全覆盖"名不副实。

它做什么：把 `<date>_units.md` 里的**每个群**与语料（`_units_filtered.md` + 其余群 + 分片文件）逐一对照，
缺群或缺行就 `COVERAGE FAIL` 并返回非零（可直接当管线步骤的自检）。

用法:
  python tools\\check_corpus_coverage.py 2026-09-14
  python tools\\check_corpus_coverage.py 2026-09-14 --quiet
"""
import argparse
import datetime as dt
import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAYS = os.path.join(HERE, "output", "days")
# 群名 = 行首那串方括号里的**最后一个**（`[问]/[答]/[卡片]` 这些标记在前，群名在后）
LEAD = re.compile(r"^(?:\d\d:\d\d\s+)?((?:\[[^\]]*\]\s*)*)")


def group_of(body):
    m = LEAD.match(body)
    if not m:
        return "(none)"
    tags = re.findall(r"\[([^\]]+)\]", m.group(1))
    return tags[-1] if tags else "(none)"


def units(path):
    if not os.path.exists(path):
        return None
    out = []
    for ln in io.open(path, encoding="utf-8", errors="replace"):
        ln = ln.rstrip("\n")
        if ln.startswith("- "):
            out.append(ln[2:])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--quiet", action="store_true")
    # 默认只**告警**：管线里的 3i-b 在"分片还没切"时跑，那是正常时序
    # （分片是提炼前才切的）。2026-09-16 实测：给它判 FAIL ⇒ 每一轮管线都报假失败。
    # 真正需要"必须有分片"的调用方（如 zcode_prep 要发菜给提炼方）加这个开关。
    ap.add_argument("--require-slices", action="store_true")
    a = ap.parse_args()

    corpus_src = units(os.path.join(DAYS, "%s_units.md" % a.date))
    if corpus_src is None:
        print("MISSING %s_units.md（先跑 3g）" % a.date)
        return 1
    filtered = units(os.path.join(DAYS, "%s_units_filtered.md" % a.date)) or []
    # 分片要按**实际命名**收（2026-09-15 晚修）：
    #   `split_day.py` 有两种产物名 —— `--units` 模式叫 `<date>_slice0N_units.md`，
    #   非 units 模式叫 `<date>_slice0N_<群名>.md`。原来这里只 glob 前者，
    #   于是 09-13 / **09-15** 这种带群名的分片**一个都收不到** → `slices` 为空 →
    #   下面整段"分片 vs 理想语料"被 `if slices:` **静默跳过**，报告却照样 COVERAGE OK。
    #   ⇒ 这是"自检静默失效"，比报错危险得多。
    slice_files = [p for p in sorted(glob.glob(os.path.join(DAYS, "%s_slice*" % a.date)))
                   if not p.endswith("_slices.md")]
    slices = []
    for p in slice_files:
        slices += units(p) or []

    src_groups = {}
    for b in corpus_src:
        g = group_of(b)
        src_groups.setdefault(g, []).append(b)

    def covered_by(rows):
        s = {}
        for b in rows:
            s.setdefault(group_of(b), []).append(b)
        return s

    flt = covered_by(filtered)
    slc = covered_by(slices)
    # 语料 = 筛过的群（filtered）+ 其余群（units.md 里 filtered 没出现过的群）的全部行
    flt_groups = set(flt)
    corpus_bodies = set(filtered)
    for g, rows in src_groups.items():
        if g not in flt_groups:
            corpus_bodies.update(rows)

    print("== %s 语料覆盖自检" % a.date)
    print("units.md: %d 行 / %d 个群 ｜ _units_filtered.md: %d 行 / %d 个群 ｜ 分片合计: %d 行 / %d 个群（%d 个文件）"
          % (len(corpus_src), len(src_groups), len(filtered), len(flt), len(slices), len(slc), len(slice_files)))

    missing_groups, thin_groups = [], []
    for g, rows in sorted(src_groups.items(), key=lambda kv: -len(kv[1])):
        have = sum(1 for b in rows if b in corpus_bodies)
        if have == 0:
            missing_groups.append((g, len(rows)))
        elif have < len(rows) and g not in flt_groups:
            # 注意：**在 `_units_filtered.md` 里出现过的群本来就该是薄的**（3i 只筛那个群），
            # 所以"薄"只对**没被筛过**的群才算异常。
            thin_groups.append((g, have, len(rows)))
        if not a.quiet and len(rows) >= 3:
            mark = "MISSING" if have == 0 else ("FILTERED" if g in flt_groups else ("THIN" if have < len(rows) else "ok"))
            print("  %-7s %-34s %4d/%4d" % (mark, g[:34], have, len(rows)))

    print("\nCOVERAGE %s  群缺失 %d ｜ 行缺失的群 %d ｜ 语料行数 %d / 源 %d"
          % ("OK" if not missing_groups and not thin_groups else "FAIL",
             len(missing_groups), len(thin_groups), len(corpus_bodies), len(corpus_src)))
    for g, n in missing_groups:
        print("  整群缺失: %s (%d 行)" % (g, n))
    for g, have, tot in thin_groups:
        print("  行缺失: %s (%d/%d)" % (g, have, tot))

    # 分片文件是否真的覆盖了理想语料（split_day 的实现 bug 会在这里现形：它把 `[卡片]` 这类
    # 标记也当成"已筛群名"，于是含这些标记的行被误排除）
    slice_gap = 0
    missing_rows = []
    if not slice_files:
        # **不许静默**（2026-09-15 实测：`if slices:` 让整段静默跳过、报告照样 COVERAGE OK —— 最危险的失效方式），
        # 但**默认只告警**：管线里的 3i-b 在"分片还没切"时跑，那是**正常时序**（分片是提炼前才切的）。
        # 2026-09-16 实测：给它判 FAIL ⇒ **每一轮管线的报告都出现一条假失败**（真正的失败会被这条噪音盖掉）。
        # 真正需要"必须有分片"的调用方（`zcode_prep.py` 要发菜给提炼方）加 `--require-slices`。
        if a.require_slices:
            slice_gap = len(corpus_bodies)
            print("**分片维度缺失**：没找到 `%s_slice*` → 这一维**没有被验证**，且本次要求必须有分片"
                  "（重切：python tools\\split_day.py %s 600 --units）" % (a.date, a.date))
        else:
            print("**分片维度缺失（告警，不算 FAIL）**：没找到 `%s_slice*` —— 管线里这是正常时序"
                  "（分片在提炼前才切）；要把它当硬条件就加 `--require-slices`" % a.date)
    elif slices:
        # 2026-09-15 加护栏：**分片比语料旧**（3i 刚重跑、还没重切）不算错 → 只提示"待重切"。
        # 否则每次重跑管线都必 FAIL（实测：3i 产出 1565 行、分片还是上一版）→ 真错会被这个噪音盖掉。
        fp_p = os.path.join(DAYS, "%s_units_filtered.md" % a.date)
        if not os.path.exists(fp_p):
            print("分片 vs 理想语料：**这一维跳过**（缺 _units_filtered.md）—— 不算 FAIL，但要知道这是个盲区")
        else:
            fp_m = os.path.getmtime(fp_p)
            sl_m = max(os.path.getmtime(p) for p in slice_files)
            if sl_m < fp_m:
                print("分片比语料旧（分片 %s / 语料 %s）→ 待重切：python tools\\split_day.py %s 600 --units（不算 FAIL）"
                      % (dt.datetime.fromtimestamp(sl_m).strftime("%H:%M"),
                         dt.datetime.fromtimestamp(fp_m).strftime("%H:%M"), a.date))
            else:
                missing_rows = [b for b in sorted(corpus_bodies) if b not in set(slices)]
                slice_gap = len(missing_rows)
                print("分片 vs 理想语料：分片 %d 行 ｜ 理想 %d 行 ｜ **分片少了 %d 行**"
                      % (len(slices), len(corpus_bodies), slice_gap))
    for b in missing_rows[:5]:
        print("   少了> [%s] %s" % (group_of(b), b[:110]))

    bad = bool(missing_groups or thin_groups or slice_gap)
    if bad:
        print("结论：语料不完整 —— 分片全覆盖名不副实，先修 split_day / 3i 再提炼。")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
