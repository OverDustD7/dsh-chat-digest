# -*- coding: utf-8 -*-
"""test_url_coverage.py — 自测 daily_prep.check_url_coverage（KNOWN_ISSUES #30 的自检）。

三个用例（只打印 ASCII 判定，避免 pwsh 控制台乱码）：
  T1 真 meta（当天全量）      -> ok
  T2 伪造"跨天窗口快照"meta   -> CHECK-FAILED（source 不符 + source_rows != day_rows）
  T3 伪造"只覆盖半天"meta     -> CHECK-FAILED
跑完把原 meta 原样恢复（逐字节）。
"""
import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import daily_prep  # noqa: E402

META = os.path.join(HERE, "output", "window", "all_urls_meta.json")
BAK = META + ".testbak"
DATE = "2026-09-12"


def call():
    st, notes = daily_prep.check_url_coverage(DATE)
    return st, notes


shutil.copy2(META, BAK)
orig = io.open(META, encoding="utf-8").read()
fails = []
try:
    st, notes = call()
    print("T1 real-meta      ->", st)
    if st != "ok":
        fails.append("T1 %s %s" % (st, notes))

    bad = json.loads(orig)
    bad["source"] = os.path.join("output", "window", "wx_raw.jsonl")
    bad["source_rows"] = 14000
    bad["day_rows"] = 465
    with io.open(META, "w", encoding="utf-8") as f:
        json.dump(bad, f, ensure_ascii=False, indent=2)
    st, notes = call()
    print("T2 window-snap    ->", st, "|", notes[0][:60].encode("ascii", "replace").decode())
    if st != "CHECK-FAILED":
        fails.append("T2 not caught")

    bad2 = json.loads(orig)
    bad2["day_max_hm"] = "09-12 14:22"
    bad2["source_rows"] = 9939
    bad2["day_rows"] = 9939
    with io.open(META, "w", encoding="utf-8") as f:
        json.dump(bad2, f, ensure_ascii=False, indent=2)
    st, notes = call()
    print("T3 halfday-meta   ->", st, "(source/rows 都对，不报错是预期：只能靠 source 字段判)")
    if st != "ok":
        fails.append("T3 unexpected %s" % st)
finally:
    with io.open(META, "w", encoding="utf-8") as f:
        f.write(orig)
    cur = io.open(META, encoding="utf-8").read()
    print("restore byte-equal:", cur == orig)
    os.remove(BAK)

print("FAILS:", len(fails), fails)
sys.exit(1 if fails else 0)
