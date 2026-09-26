# -*- coding: utf-8 -*-
r"""zcode_prep.py —— 给 ZCode 闲时任务备料：核对输入、补齐分片、写"当天专属的现成指令"。

用法:
    python tools\zcode_prep.py 2026-09-15

它做四件事（都是机械的，不花 token）：
 1. 核对当天产物是否齐（缺哪个就明说，不猜、不自作主张去取数）；
 2. 分片缺失或比语料旧 → 重切（`split_day.py <date> 600 --units`）；
 3. 跑语料覆盖自检（FAIL 就拒绝，别让闲时任务在坏语料上跑）；
 4. 生成两个文件（**都在 output\zcode\<date>\，不碰 output\daily\**）：
      · `TASK-BRIEF.md`      —— 当天入口简报（≤150 行：输入清单 + 分片表 + 禁用项）
      · `INSTRUCTION-READY.md` —— **可直接整份粘贴**进 ZCode「闲时任务 → 指令」框

为什么要有它：官方要求闲时任务的指令"尽量完整、自足"（无人值守）。
把"当天是哪天、有哪些输入、几片、产出写哪里"这些会变的东西，交给脚本填好，
通用规则留在 `docs\zcode\IDLE-TASK-EXTRACT.md`（改规则只改那一份）。
"""
import datetime as dt
import io
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAYS = os.path.join(HERE, "output", "days")
ZC = os.path.join(HERE, "output", "zcode")
GEN = os.path.join(HERE, "docs", "zcode", "IDLE-TASK-EXTRACT.md")
PY = sys.executable

# 必须有这些才算"够提炼"（缺一个就拒绝——尤其 units/slices，那是全覆盖的载体）
REQUIRED = [
    ("%s.jsonl", "当天消息原文（提取步的产物）"),
    ("%s_units.md", "话语单元化（3g）"),
    ("%s_units_filtered.md", "本地小模型过筛（3i）——**提炼的输入必须是筛后**"),
    ("%s_brief.md", "按会话分组的简报"),
    ("%s_timeline.md", "跨会话时间轴（索引，不是读物）"),
    ("%s_articles.md", "文章卡片清单（有本地正文的必须读）"),
    ("%s_threads.md", "主题跨天回溯"),
    ("%s_images.json", "图片索引（4）"),
    ("%s_vision.md", "图片分诊（3j）"),
    ("%s_units_dropped.md", "被小模型丢掉的原文（抽检用）"),
]


def sz(p):
    return os.path.getsize(p) if os.path.exists(p) else -1


def lines(p):
    if not os.path.exists(p):
        return -1
    with io.open(p, encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f)


def run(args, timeout=180):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=HERE, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def slice_index(date):
    """分片清单**以索引 `<date>_slices.md` 为准**，不是"目录里所有 slice 文件"。

    为什么（实测踩过）：09-15 的目录里同时躺着一代**旧分片**（`_slice01..04_清华大学2026级新.md`，
    1,690 行，非 `--units` 模式产物）和一代**新分片**（`_slice01/02_units.md`，940 行，权威）。
    按目录 glob 会把两代都算进去 → 让执行者**白读一倍**、还会把两代口径混在一起。
    索引是 `split_day.py` 每次重切时重写的，是唯一权威清单。
    """
    p = os.path.join(DAYS, "%s_slices.md" % date)
    if not os.path.exists(p):
        return p, []
    txt = io.open(p, encoding="utf-8", errors="replace").read()
    files = re.findall(r"`output/days/([^`]+)`", txt)
    if not files:                                    # 兜底：老格式可能不带反引号
        files = re.findall(r"(%s_slice\S+?\.md)" % date, txt)
    return p, [f for f in files if not f.endswith("_slices.md")]


def main(argv):
    if not argv:
        print("用法: python tools\\zcode_prep.py <YYYY-MM-DD>")
        return 2
    date = argv[0]
    try:
        dt.datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        print("日期必须是 YYYY-MM-DD，收到 %r" % date)
        return 2
    # 分片口径（第二个参数）：units＝3i 筛后（索引口径，默认）；full＝全量分片（＝DSH 那一轮实际读的 4 片）
    mode = (argv[1] if len(argv) > 1 else "units").lower()
    if mode not in ("units", "full"):
        print("第二个参数只能是 units 或 full，收到 %r" % mode)
        return 2
    tag = argv[2] if len(argv) > 2 else ""
    run_name = date + ("-" + tag if tag else "")
    outdir = os.path.join(ZC, run_name)

    print("== 1. 核对输入（%s）==" % date)
    missing = []
    for pat, why in REQUIRED:
        p = os.path.join(DAYS, pat % date)
        if os.path.exists(p):
            print("   OK   %-34s %10d B  %5d 行" % (pat % date, sz(p), lines(p)))
        else:
            print("   缺   %-34s —— %s" % (pat % date, why))
            missing.append(pat % date)
    if missing:
        print("\n拒绝备料：缺 %d 个必需产物（%s）。" % (len(missing), ", ".join(missing)))
        print("这是**上游前置条件缺失**（不是本脚本的错）：先在 DSH 侧跑")
        print("  python scripts\\daily_prep.py %s" % date)
        print("（取数需要微信在线；未登录时报告会显示「待微信登录」而不是失败。）")
        return 3

    print("\n== 2. 分片（口径 %s：%s）=="
          % (mode, "full＝全量分片（含未被 3i 筛掉的大群）" if mode == "full" else "units＝3i 筛后分片（索引口径）"))
    units_m = os.path.getmtime(os.path.join(DAYS, "%s_units.md" % date))
    idx_p, indexed = slice_index(date)
    if mode == "units":
        slices = indexed
        need_cut = (not slices) or (not os.path.exists(idx_p)) \
            or any(not os.path.exists(os.path.join(DAYS, s)) for s in slices) \
            or os.path.getmtime(idx_p) < units_m
        if need_cut:
            print("   索引缺失 / 分片缺失 / 比语料旧 → 重切：split_day.py %s 600 --units" % date)
            rc, out = run([PY, os.path.join(HERE, "tools", "split_day.py"), date, "600", "--units"])
            print("   rc=%d ｜ %s" % (rc, out.strip().splitlines()[-1] if out.strip() else ""))
            idx_p, slices = slice_index(date)
        else:
            print("   索引与分片都是最新的，无需重切")
    else:
        # full 口径：**不重切**（重切会重写共享的 <date>_slices.md 索引，把另一口径的清单覆盖掉），
        # 直接用磁盘上那批非 `_units` 后缀的分片（＝DSH 那一轮实际读过的 4 片）。
        slices = sorted(f for f in os.listdir(DAYS)
                        if f.startswith("%s_slice" % date)
                        and not f.endswith("_units.md") and not f.endswith("_slices.md"))
        if slices:
            print("   full 口径分片已在磁盘上，**不重切**（保住共享索引不动）")
        else:
            print("   full 口径分片不存在 → 生成：split_day.py %s 600（⚠ 会重写 <date>_slices.md 索引）" % date)
            rc, out = run([PY, os.path.join(HERE, "tools", "split_day.py"), date, "600"])
            print("   rc=%d ｜ %s" % (rc, out.strip().splitlines()[-1] if out.strip() else ""))
            slices = sorted(f for f in os.listdir(DAYS)
                            if f.startswith("%s_slice" % date)
                            and not f.endswith("_units.md") and not f.endswith("_slices.md"))
    if not slices:
        print("\n拒绝备料：拿不到分片清单（口径 %s）。" % mode)
        return 5
    print("   另一口径的清单（仅供对照，本次不读）：%s" % (", ".join(indexed) or "（无）"))
    slice_rows = 0
    for s in slices:
        n = lines(os.path.join(DAYS, s))
        slice_rows += max(0, n)
        print("     %-46s %5d 行" % (s, n))
    # 另一口径的分片摆在同一目录里：**明说本次不读**（否则执行者会白读一倍、还把两种口径混在一起）
    extra = [f for f in sorted(os.listdir(DAYS))
             if f.startswith("%s_slice" % date) and not f.endswith("_slices.md") and f not in slices]
    if extra:
        print("    另有 %d 个**本次不读**的分片（另一口径产物）：%s"
              % (len(extra), ", ".join(extra[:4]) + ("…" if len(extra) > 4 else "")))

    print("\n== 3. 语料覆盖自检（FAIL 就不许提炼）==")
    rc, out = run([PY, os.path.join(HERE, "tools", "check_corpus_coverage.py"), date,
                   "--quiet", "--require-slices"])
    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-2:]
    for ln in tail:
        print("   " + ln)
    if rc != 0:
        print("\n拒绝备料：语料覆盖自检 FAIL（上面就是原因）。先修语料，别在坏语料上提炼。")
        return 4

    print("\n== 4. 生成当天专属文件 ==")
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    gen = io.open(GEN, encoding="utf-8").read()
    units_n = lines(os.path.join(DAYS, "%s_units.md" % date))
    b = sz(os.path.join(DAYS, "%s_brief.md" % date))
    t = sz(os.path.join(DAYS, "%s_timeline.md" % date))
    imgs = lines(os.path.join(DAYS, "%s_images.json" % date))

    brief = [
        "# %s 提炼任务 · 当天简报（给执行者）" % date,
        "",
        "- 生成时间：%s" % dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        '- 工作区（也是本任务的「项目」）：`<个人目录>`',
        "- **今天要提炼的就是 %s 这一天**；产出全部写到 `output\\zcode\\%s\\`。" % (date, run_name),
        "- **分片口径：%s**（%s）；每片派一个前台子智能体逐条读完。"
        % (mode, "full＝全量分片，含未被 3i 筛掉的大群" if mode == "full" else "units＝3i 筛后分片"),
        "",
        "## 输入清单（**都给路径，别整读**）",
        "",
        "| 文件 | 体积/行数 | 怎么用 |",
        "|---|---|---|",
        "| `output\\days\\%s_sliceNN_*.md` | **%d 片 / 约 %d 行** | **阅读单位**：每片派一个前台子智能体逐条读完 |"
        % (date, len(slices), slice_rows),
        "| `output\\days\\%s_timeline.md` | %d B | **索引不是读物**：只读开头的「跨群线索索引」A/B 两节；要线索 `grep -n` 定位 |" % (date, t),
        "| `output\\days\\%s_units.md` | %d 行 | 检索/分片数据源（**不要整读**） |" % (date, units_n),
        "| `output\\days\\%s_brief.md` | %d B | **不要整读**；`grep -n` 定位到会话段后只读片段 |" % (date, b),
        "| `output\\days\\%s_articles.md` | — | 可以直接读；**本地有正文的文章必须读完**再写条目 |" % date,
        "| `output\\days\\%s_threads.md` | — | 直接读（标出「同一 URL/标题前几天也出现过」） |" % date,
        "| `output\\days\\%s_vision.md` + `%s_images.json` | %d 条图片 | 分诊结论可直接读；要回看的图交能读图的子智能体 |" % (date, date, max(0, imgs)),
        "| `output\\days\\%s_units_dropped.md` | — | 被本地小模型丢掉的原文，**抽 20 条**估漏率 |" % date,
        "",
        "## 分片表（每片一个前台子智能体）",
        "",
    ]
    for i, s in enumerate(slices, 1):
        brief.append("- 第 %02d 片：`output\\days\\%s`（%d 行）" % (i, s, lines(os.path.join(DAYS, s))))

    brief += [
        "",
        "## 明令禁止（越界即失败）",
        "",
        "1. **不许读** `output\\daily\\%s\\items.json`" % date,
        "   —— 那是 DSH 侧另一条线的产出，读了就等于抄，会让「双轨对比」失去意义。",
        "2. **不许**打任何 `/chat-feed` 的 HTTP、不许碰面板、不许改规范/脚本/文档。",
        "3. **不许删除任何文件**；只准在 `output\\zcode\\%s\\` 下写。" % run_name,
        "4. **不许用后台子智能体**（闲时通道不支持后台派发）——要并行就用**前台**。",
        "5. **不许整读**上表里标注「不要整读」的大文件。",
        "6. **不许**用关键字过滤决定「读不读」某一片（关键字只能排优先级）。",
        "7. **只读本简报列出的那 %d 片**（口径＝%s）；目录里另有 %d 个**本次不读**的分片（另一口径产物）。"
        % (len(slices), mode, len(extra)),
        "",
        "## 规则去哪查（**grep 定位，不要整读**）",
        "",
        "- 产出形态与硬性纪律：`grep -n \"硬性纪律\" docs\\output_format.md`",
        "- 三问与原则：`grep -n \"三问\\|原则 2[0-9]\" docs\\guidelines.md`",
        "- 子代理四条纪律与派活：`grep -n \"省 token 的固定四条\\|分片全覆盖\" docs\\task_daily_template.md`",
        "- 通用冷启动卡：`COLD-START.md`（≤150 行，可整读）",
        "",
        "## 产出（四个文件，都在 `output\\zcode\\%s\\`）" % run_name,
        "",
        "`items.json` ｜ `ACTION-LEDGER.md` ｜ `SUMMARY.md`（≤30 行）｜ `DROPPED-SAMPLE.md`",
        "",
        "收尾自检与报告格式见**指令正文**（`INSTRUCTION-READY.md`）的 §6/§7。",
        "",
    ]
    io.open(os.path.join(outdir, "TASK-BRIEF.md"), "w", encoding="utf-8", newline="\n").write("\n".join(brief))

    head = [
        "<!-- 本文件由 tools\\zcode_prep.py 生成，**整份粘贴**进 ZCode「闲时任务 → 指令」框即可 -->",
        "",
        "**任务日期：%s**（就提炼这一天；产出写 `output\\zcode\\%s\\`）" % (date, run_name),
        "",
        "**进去先读这一份（≤150 行，可直接整读）：`output\\zcode\\%s\\TASK-BRIEF.md`**" % run_name,
        "（它给了当天全部输入路径、分片表、禁用项与规则查找方式。）",
        "",
        "---",
        "",
    ]
    ready = "\n".join(head) + gen
    io.open(os.path.join(outdir, "INSTRUCTION-READY.md"), "w", encoding="utf-8", newline="\n").write(ready)

    print("   + %s（%d 行）" % (os.path.join("output", "zcode", run_name, "TASK-BRIEF.md"),
                                len(brief)))
    print("   + %s（%d 行，**整份粘贴**）" % (os.path.join("output", "zcode", run_name, "INSTRUCTION-READY.md"),
                                             ready.count("\n") + 1))
    print("\n下一步（人做）——**两条路选一条**：")
    print("  A) **夜间免费档（23:00-09:00，GLM-5.3-Flash 额度 0）= 首选**：ZCode 里开**正常会话**、")
    print("     模型选 GLM-5.3-Flash，把指令整份粘贴即可 —— 不用排队、不受「只跑一次」限制、支持后台子智能体；")
    print("     **注意窗口**：过了 09:00 之后的调用按正常计费。")
    print("  B) 闲时任务（无人值守 / 不在免费窗口时）：左侧「自动化」→「闲时任务」→ 权限选**自动执行** + 打开「保持唤醒」；")
    print("     限制：只跑一次、不承诺开始时间、**只许前台子智能体**。")
    print("  两条路都要：ZCode 里打开项目 <个人目录>（**项目创建后不可改**）")
    print("  指令整份粘贴：output\\zcode\\%s\\INSTRUCTION-READY.md" % run_name)
    print("  结果出来后：python tools\\compare_daily_items.py %s --a output\\zcode\\%s\\items.json" % (date, run_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))