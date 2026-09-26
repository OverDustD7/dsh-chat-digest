# -*- coding: utf-8 -*-
"""mem_audit.py — **审计长期记忆（Mnemon insights）到底写了什么**：用来回答"这一轮的提取内容同步到记忆了吗"。

为什么要有它（2026-09-15）：规范要求每轮第二轮「每条新知识 + 关于他本人的一切 → `mnemon_remember`」，
但**没有任何一处能证明它真的写了** —— 09-14 原轮与重做轮的知识库文档都写了（people/channels/resources/lessons/
DEV_NOTES/preferences 的 mtime 都能看到），而 insights 里查不到那两轮的任何内容
（`院长下午茶` / `同心圆` / `ESG` / `AI批改` 命中 **0**）。于是把这次的取证脚本固化成工具，
让"写没写记忆"变成**一条能跑出数字的命令**，写进每轮收尾的固定清单。

用法:
    python tools\\mem_audit.py                      # 概览：总条数 + 最近 12 条写入
    python tools\\mem_audit.py --since "09-15 01:00"  # 该时刻（CST）之后写入的条目
    python tools\\mem_audit.py --grep 院长下午茶 同心圆   # 按内容搜（判断某条知识有没有进记忆）
    python tools\\mem_audit.py --since "09-14 23:30" --require 3   # 少于 3 条就非零退出（当收尾自检用）
只读（`mode=ro`），不写、不删任何记忆。
"""
import argparse
import datetime as dt
import os
import re
import shutil
import sqlite3
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
TZ = dt.timezone(dt.timedelta(hours=8))
DB = os.path.join(os.environ["USERPROFILE"], ".dsh", "mnemon", "data", "default", "mnemon.db")


def open_db():
    """只读打开记忆库。

    2026-09-20 修：**WAL 模式下 `mode=ro` 仍要读写 `-shm`** —— 记忆插件正在写时就会
    `unable to open database file`（09-20 那轮收尾就撞上，主 agent 只能手工复制库绕过）。
    这里把它做成兜底：只读打开失败 ⇒ 把 db(+wal+shm) 复制到临时目录再读。
    """
    uri = "file:%s?mode=ro" % DB.replace("\\", "/")
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
        con.execute("SELECT COUNT(*) FROM insights").fetchone()   # 真正触发打开
        return con
    except sqlite3.OperationalError as e:
        print("（只读打开失败：%s ⇒ 复制一份再读）" % e)
    tmp = tempfile.mkdtemp(prefix="mnemon_audit_")
    for suf in ("", "-wal", "-shm"):
        if os.path.exists(DB + suf):
            shutil.copy2(DB + suf, os.path.join(tmp, "mnemon.db" + suf))
    return sqlite3.connect(os.path.join(tmp, "mnemon.db"), timeout=5)


def parse_when(s, now=None):
    """接受 'YYYY-MM-DD HH:MM' / 'MM-DD HH:MM' / 'HH:MM'（CST）或纯 epoch 秒/毫秒。"""
    now = now or dt.datetime.now(TZ)
    s = s.strip()
    if s.replace(".", "").isdigit():
        v = float(s)
        return dt.datetime.fromtimestamp(v / 1000 if v > 1e12 else v, TZ)
    # 补年份后再交给 strptime —— 否则 Python 会对"没有年份"的格式发 DeprecationWarning
    if re.match(r"^\d\d-\d\d \d\d:\d\d$", s):
        s = "%d-%s" % (now.year, s)
    elif re.match(r"^\d\d:\d\d$", s):
        s = now.strftime("%Y-%m-%d ") + s
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except ValueError:
        raise SystemExit("看不懂的时间：%r（试试 '09-15 01:00'）" % s)


def stamp(v):
    """stored_at 可能是 ISO(UTC) 或 epoch。"""
    if isinstance(v, str) and not v.replace(".", "").isdigit():
        t = v.rstrip("Z").replace("T", " ")
        d = dt.datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
        return d.astimezone(TZ)
    f = float(v)
    return dt.datetime.fromtimestamp(f / 1000 if f > 1e12 else f, TZ)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="只看这个时刻（CST）之后写入的")
    ap.add_argument("--grep", nargs="*", default=None, help="按内容搜关键词（判断某条知识进没进记忆）")
    ap.add_argument("--require", type=int, default=None, help="--since 窗口内至少 N 条，否则非零退出")
    ap.add_argument("--limit", type=int, default=12)
    a = ap.parse_args()

    if not os.path.exists(DB):
        print("找不到记忆库：%s" % DB)
        return 1
    con = open_db()
    n = con.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
    print("记忆库：%s\n总条数：%d" % (DB, n))

    if a.grep is not None:
        if not a.grep:
            print("--grep 没给词")
            return 2
        print("\n内容命中（忽略空格：`AI批改` 能命中 `AI 批改`）：")
        zero = 0
        for k in a.grep:
            # 2026-09-15 踩过：`--grep AI批改` 对记忆里的「AI 批改」命中 0 → 差点误报"没写"。
            # 比对时把两边的**空格/全角空格**都去掉，避免这种假阴性。
            pat = "%" + k.replace(" ", "").replace("\u3000", "") + "%"
            rows = con.execute(
                "SELECT content, stored_at FROM insights WHERE REPLACE(REPLACE(content,' ','' ),'\u3000','') LIKE ? "
                "ORDER BY stored_at DESC LIMIT 5", (pat,)).fetchall()
            print("  [%s] %d 条" % (k, len(rows)))
            if not rows:
                zero += 1
            for c, s in rows:
                print("      %s  %s" % (stamp(s).strftime("%m-%d %H:%M"), c.replace("\n", " ")[:100]))
        con.close()
        return 0

    rows = con.execute("SELECT content, stored_at, category, source FROM insights ORDER BY stored_at DESC LIMIT ?",
                       (max(a.limit, 200),)).fetchall()
    if a.since:
        cut = parse_when(a.since)
        rows = [r for r in rows if stamp(r[1]) >= cut]
        print("\n--since %s（CST）之后写入：**%d 条**" % (cut.strftime("%m-%d %H:%M"), len(rows)))
    else:
        rows = rows[:a.limit]
        print("\n最近 %d 条：" % len(rows))
    for c, s, cat, src in rows[:a.limit]:
        print("  %s [%s/%s] %s" % (stamp(s).strftime("%m-%d %H:%M"), cat, src, c.replace("\n", " ")[:96]))
    con.close()

    if a.require is not None and a.since:
        cnt = len(rows)
        if cnt < a.require:
            print("\n自检 FAIL：窗口内只写入 %d 条，要求 ≥%d —— 这一轮的「双写记忆」很可能没做。" % (cnt, a.require))
            return 1
        print("\n自检 OK：窗口内写入 %d 条（要求 ≥%d）。" % (cnt, a.require))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
