"""A线第一步取证：QQ 导出库覆盖到哪一天（判断 step 2 失败有没有造成数据缺口）。

用法：python tools\\check_qq_range.py
读 output\\qq\\nt_msg_export.db，打印 09-10..09-13 的 QQ 消息条数与最早/最新时间。
只读，不改任何东西。
"""
import io
import os
import sqlite3
import sys
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "output", "qq", "nt_msg_export.db")
CST = datetime.timezone(datetime.timedelta(hours=8))

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
except Exception:  # noqa: BLE001
    pass


def main():
    if not os.path.exists(DB):
        print("MISSING", DB)
        return 1
    print("db =", DB, os.path.getsize(DB), "bytes, mtime",
          datetime.datetime.fromtimestamp(os.path.getmtime(DB), CST).strftime("%Y-%m-%d %H:%M:%S"))
    con = sqlite3.connect(DB)
    tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print("tables:", tabs)
    # nt_msg.db 的群/好友消息通常在同一张表里，带 40001/40002 之类 msg_type
    for t in tabs:
        cols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % t)]
        if t.endswith("_fts") or "_fts_" in t:
            continue
        print("\n[%s] cols=%s" % (t, cols))
        tcol = next((c for c in cols if "time" in c.lower()), None)
        if not tcol:
            print("   (没有时间列，跳过)")
            continue
        n = con.execute('SELECT count(*) FROM "%s"' % t).fetchone()[0]
        print("   rows=%d, tcol=%s" % (n, tcol))
        try:
            for day in ("2026-09-10", "2026-09-11", "2026-09-12", "2026-09-13"):
                d0 = int(datetime.datetime.fromisoformat(day + "T00:00:00+08:00").timestamp())
                d1 = d0 + 86400
                c = con.execute('SELECT count(*) FROM "%s" WHERE %s>=? AND %s<?' % (t, tcol, tcol),
                                (d0, d1)).fetchone()[0]
                print("   %s : %d 条" % (day, c))
            lo, hi = con.execute('SELECT min(%s), max(%s) FROM "%s"' % (tcol, tcol, t)).fetchone()
            for label, v in (("min", lo), ("max", hi)):
                if v:
                    print("   %s = %s" % (label, datetime.datetime.fromtimestamp(v, CST).strftime("%Y-%m-%d %H:%M:%S")))
        except Exception as exc:  # noqa: BLE001
            print("   range query failed:", exc)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
