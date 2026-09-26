# -*- coding: utf-8 -*-
"""一轮收尾的机械自检：**一次调用跑完**（省主 agent 的步数）。

为什么要有它（2026-09-17 夜，用户问"2.8 可以再节约吗"）：
  实测那一轮 **119 步 / ¥2.80 ⇒ 一步 ≈ ¥0.024**，而收尾这几件机械活原来要分别调 5–6 个脚本
  （镜像 / 读 `/state` 回读 / `mem_audit` / `check_knowledge_style` / `check_step_count` /
  `export_day_items`），各占 1–3 步。合并成一次调用**判据一条不减**，纯粹省步数。

用法（在本工具目录下）：
    ..\\venv\\Scripts\\python.exe tools\\round_finish.py --since "2026-09-17 22:50" --require 3
        [--date 2026-09-17] [--no-mirror] [--no-step-count] [--full]

做的事：
  1. `export_list_mirror.py` —— 刷新 `docs\\信息列表.md` 镜像，回条数
  2. 读 `/chat-feed/api/state` —— `persist` / `busy` / `items` / `done` / `isNew` / `lastError`
  3. `mem_audit.py --since <t> --require <n>` —— **双写自证**
  4. `check_knowledge_style.py` —— 知识库 0 违规
  5. `check_step_count.py` —— 步数口径（以 `prep_report.md` 行数为准）
  6. 给了 `--date` 就确认 `output\\daily\\<date>\\items.json` 存在并报条数

输出一段紧凑结论（默认每项一行）；退出码 0＝全部通过、1＝有未过（逐项写明）。

实现说明：全部**在进程内 import 调用**（`redirect_stdout` 收口），**不起子进程** ——
  沙箱下 piped stdio 会踩 EPERM 边界（历史实测），in-process 调用绕开它。
"""
import argparse
import contextlib
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))       # agent 根（＝包内 agent/ 或 <个人目录>）
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.path.insert(0, os.path.join(HERE, "docs", "agent"))

import cf_api          # noqa: E402
import mem_audit       # noqa: E402
import check_knowledge_style as cks   # noqa: E402
import check_step_count as csc        # noqa: E402
import export_list_mirror as elm      # noqa: E402


def _run(mod, argv):
    """在进程内调 mod.main()，把它的 stdout 收回来（不进终端，避免刷屏）。返回 (rc, 文本)。"""
    buf = io.StringIO()
    old = sys.argv
    sys.argv = [getattr(mod, "__name__", "mod")] + list(argv)
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main()
    except SystemExit as e:                                    # 脚本自己 raise SystemExit
        rc = int(e.code or 0)
    except Exception as e:                                     # noqa: BLE001
        rc, buf = 1, buf
        buf.write("EXC %s: %s" % (type(e).__name__, e))
    finally:
        sys.argv = old
    return rc, buf.getvalue()


def _tail(text, n=1):
    lines = [x.rstrip() for x in text.split("\n") if x.strip()]
    return " ｜ ".join(lines[-n:]) if lines else "(无输出)"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="本轮开始时刻（CST），传给 mem_audit")
    ap.add_argument("--require", type=int, default=3, help="mem_audit 窗口内至少 N 条（默认 3）")
    ap.add_argument("--date", default="", help="给了就核对 output\\daily\\<date>\\items.json")
    ap.add_argument("--no-mirror", action="store_true", help="跳过镜像刷新")
    ap.add_argument("--no-step-count", action="store_true", help="跳过步数口径自检")
    ap.add_argument("--full", action="store_true", help="把每个脚本的原始输出也打出来（排错用）")
    a = ap.parse_args(argv)

    rows, fails, raws = [], [], []

    # 1) 镜像
    if not a.no_mirror:
        rc, out = _run(elm, [])
        rows.append(("镜像", "OK" if rc == 0 else "FAIL", _tail(out)))
        raws.append(("export_list_mirror", rc, out))
        if rc != 0:
            fails.append("镜像")
    else:
        rows.append(("镜像", "跳过", "--no-mirror"))

    # 2) 面板现状（读 /state，不看正文，省 token）
    try:
        st, body = cf_api.call("GET", "/chat-feed/api/state")
        d = json.loads(body) if st == 200 else {}
        items = d.get("items") or []
        ok = (st == 200 and not d.get("lastError"))
        detail = ("persist=%s ｜ busy=%s ｜ items=%d ｜ done=%d ｜ isNew=%d ｜ lastError=[%s]"
                  % ("saved" if d.get("saveOk") else "?", d.get("busy"), len(items),
                     sum(1 for x in items if x.get("done")), sum(1 for x in items if x.get("isNew")),
                     d.get("lastError") or ""))
        rows.append(("面板", "OK" if ok else "FAIL", detail))
        if not ok:
            fails.append("面板")
    except Exception as e:                                     # noqa: BLE001
        rows.append(("面板", "FAIL", "读 /state 失败：%s" % e))
        fails.append("面板")

    # 3) 双写自证
    rc, out = _run(mem_audit, ["--since", a.since, "--require", str(a.require)])
    rows.append(("双写", "OK" if rc == 0 else "FAIL", _tail(out, 2)))
    raws.append(("mem_audit", rc, out))
    if rc != 0:
        fails.append("双写(mem_audit)")

    # 4) 知识库风格
    rc, out = _run(cks, [])
    rows.append(("知识库", "OK" if rc == 0 else "FAIL", _tail(out, 2)))
    raws.append(("check_knowledge_style", rc, out))
    if rc != 0:
        fails.append("知识库风格")

    # 5) 步数口径
    if not a.no_step_count:
        rc, out = _run(csc, [])
        rows.append(("步数口径", "OK" if rc == 0 else "FAIL", _tail(out, 2)))
        raws.append(("check_step_count", rc, out))
        if rc != 0:
            fails.append("步数口径")

    # 6) 当日交付文件
    if a.date:
        p = os.path.join(HERE, "output", "daily", a.date, "items.json")
        if os.path.exists(p):
            try:
                n = len(json.loads(io.open(p, encoding="utf-8").read()))
            except Exception:                                  # noqa: BLE001
                n = -1
            rows.append(("交付", "OK" if n > 0 else "FAIL", "%s（%s 条）" % (os.path.relpath(p, HERE), n)))
            if n <= 0:
                fails.append("交付 items.json")
        else:
            rows.append(("交付", "FAIL", "缺 %s" % os.path.relpath(p, HERE)))
            fails.append("交付 items.json")

    print("== 收尾自检（%s 起）==" % a.since)
    for name, verdict, detail in rows:
        print("  %-6s %-4s %s" % (name, verdict, detail))
    if a.full:
        for name, rc, out in raws:
            print("\n---- %s（rc=%d）----\n%s" % (name, rc, out.rstrip()))
    print("结论：" + ("全部通过" if not fails else "有 %d 项未过 ⇒ %s" % (len(fails), "、".join(fails))))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
