# -*- coding: utf-8 -*-
"""test_prep_wiring.py — 在**临时目录**里跑一遍 daily_prep.main()，只验证"接线"（不真跑任何步骤）。

做法：把模块级 HERE 指到临时目录（真实项目树一个字节都不动），把 `run()` 打桩成
"只记录 argv、不执行"，于是所有步骤都不会真的跑；再检查
  ① 第 6 步的 argv 是 [.., 'dig_urls.py', '<date>']（带日期）
  ② 第 6 步的受检产物含 all_urls_meta.json
  ③ check_url_coverage 的"覆盖"备注进了报告（证明自检被调用）
  ④ 报告落在临时目录里
  ⑤ **A08/A17（2026-09-20 审计）新增**：报告里有"整体："结论行；同目录 `_run.json` 落盘且含
     `failed`/`degraded`/`steps`；`run()` 的打桩签名必须能收下 `critical`/`empty_ok`/`status_map`/
     `freshness_grace`（否则接线一改这里就 TypeError —— 旧版就是这样悄悄腐烂的）。

**日期不再写死**（A16）：旧版硬编 `DATE = "2026-09-12"`，与那份 all_urls_meta.json 绑死，
换个日期就假失败。现在从 meta 自己读 `date` 与统计值，meta 刷新后测试自动跟上。
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REAL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REAL, "scripts"))
import daily_prep  # noqa: E402

META_SRC = os.path.join(REAL, "output", "window", "all_urls_meta.json")
try:
    META = json.loads(io.open(META_SRC, encoding="utf-8").read())
except (OSError, ValueError) as e:
    raise SystemExit("读不到 %s：%s（先跑一次 daily_prep 的第 6 步）" % (META_SRC, e))
DATE = str(META.get("date") or "")
if not DATE:
    raise SystemExit("%s 里没有 date 字段，无法自证" % META_SRC)
WANT_COVER = "覆盖 %s ~ %s" % (META.get("day_min_hm"), META.get("day_max_hm"))
WANT_UNIQ = "唯一URL=%s" % META.get("unique_urls")

fails = []
tmp = tempfile.mkdtemp(prefix="cfprep-")
try:
    # 临时树里只放 check_url_coverage 需要的那两个文件（真 meta 的直接拷贝）
    win = os.path.join(tmp, "output", "window")
    os.makedirs(win)
    shutil.copy2(META_SRC, os.path.join(win, "all_urls_meta.json"))
    io.open(os.path.join(win, "all_urls.jsonl"), "w", encoding="utf-8").write("{}\n")

    daily_prep.HERE = tmp

    calls = []

    def fake_run(label, argv, check_paths=(), check_lines=(0, None), timeout=1800,
                 status_map=None, critical=True, empty_ok=False, freshness_grace=300):
        """签名必须与 `daily_prep.run` 一致（多出来的 kwargs 全部收下）。"""
        calls.append({"label": label, "argv": list(argv), "checks": list(check_paths),
                      "critical": critical})
        notes = []
        for cp in check_paths:                     # 让"产物存在"这半边也照实走
            p = cp if os.path.isabs(cp) else os.path.join(tmp, cp)
            if not os.path.exists(p):
                notes.append("MISSING %s" % cp)
        return {"step": label, "status": "ok", "seconds": 0, "notes": notes, "critical": critical}

    daily_prep.run = fake_run
    old_argv = sys.argv
    sys.argv = ["daily_prep.py", DATE]
    try:
        rc = daily_prep.main()
    finally:
        sys.argv = old_argv

    s6 = [c for c in calls if c["label"].startswith("6-")]
    print("date (from meta):", DATE, "| steps recorded:", len(calls), "| main() rc:", rc)
    if not s6:
        fails.append("no step-6 recorded")
    else:
        argv = s6[0]["argv"]
        print("step6 label :", s6[0]["label"].encode("ascii", "replace").decode())
        print("step6 argv  :", [os.path.basename(a) if i else a for i, a in enumerate(argv)])
        if argv[-1] != DATE:
            fails.append("argv 末尾不是日期: %r" % argv[-1])
        if "dig_urls.py" not in " ".join(argv):
            fails.append("argv 里没有 dig_urls.py")
        if "output/window/all_urls_meta.json" not in s6[0]["checks"]:
            fails.append("受检产物缺 all_urls_meta.json")
    # A01②：附件索引那一步必须真的接线（丢了它"文件线"又断）
    if not [c for c in calls if c["label"].startswith("4b-")]:
        fails.append("没有 4b-文件附件索引 这一步（A01② 接线丢了）")
    else:
        fstep = [c for c in calls if c["label"].startswith("4b-")][0]
        if "find_attachments.py" not in " ".join(fstep["argv"]):
            fails.append("4b 步的 argv 里没有 find_attachments.py")
        if "output/days/%s_files.json" % DATE not in fstep["checks"]:
            fails.append("4b 步没把 <date>_files.json 列为受检产物")

    rep = os.path.join(tmp, "output", "daily", DATE, "prep_report.md")
    if not os.path.exists(rep):
        fails.append("报告没生成")
    else:
        txt = io.open(rep, encoding="utf-8").read()
        print("report bytes:", len(txt.encode("utf-8")))
        if WANT_COVER not in txt:
            fails.append("报告里没有覆盖自检备注 %r（check_url_coverage 没被调用？）" % WANT_COVER)
        if WANT_UNIQ not in txt:
            fails.append("报告里没有 %r" % WANT_UNIQ)
        if "MISSING output/window/all_urls.jsonl" in txt or \
                "MISSING output/window/all_urls_meta.json" in txt:
            fails.append("第 6 步自己的受检产物 MISSING")
        # A08：整体结论行必须在报告里（关键/可选分级）
        if "整体：" not in txt:
            fails.append("报告里没有「整体：」结论行（A08 分级丢了）")
        row6 = [l for l in txt.splitlines() if l.startswith("| 6-")]
        print("step6 row   :", row6[0].encode("ascii", "replace").decode() if row6 else "N/A")
        # 其余步骤的 MISSING 是本测试的环境所致（临时树里只有 all_urls* 两个文件），不算失败
        print("other-steps MISSING (stub artifact):",
              len([l for l in txt.splitlines() if "MISSING" in l]))
        print("report has coverage note:", WANT_COVER in txt)
        print("report has unique url   :", WANT_UNIQ in txt)

    # A08：机器可读的本轮记录（上游据此判"取数与交付是否通过"）
    rj = os.path.join(tmp, "output", "daily", DATE, "_run.json")
    if not os.path.exists(rj):
        fails.append("_run.json 没生成（A08 的机器可读记录）")
    else:
        rec = json.loads(io.open(rj, encoding="utf-8").read())
        print("run.json    :", {k: rec.get(k) for k in ("date", "ok", "n_msg", "failed", "degraded")})
        for k in ("date", "ok", "failed", "degraded", "steps"):
            if k not in rec:
                fails.append("_run.json 缺字段 %s" % k)
        if rec.get("date") != DATE:
            fails.append("_run.json 的 date 不对: %r" % rec.get("date"))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    print("temp tree removed:", not os.path.exists(tmp))

print("FAILS:", len(fails), fails)
sys.exit(1 if fails else 0)
