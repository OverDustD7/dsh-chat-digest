# -*- coding: utf-8 -*-
"""watch_main.py — 一眼看主 agent 这一轮跑到哪了（只读）。

用法: python tools\\watch_main.py [DATE]
看四样：会话状态 / 面板状态 / 主 agent 最近一条 assistant 消息 / 今天该出现的产物
"""
import datetime as dt
import importlib.util
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = dt.timezone(dt.timedelta(hours=8))
DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-09-13"

spec = importlib.util.spec_from_file_location("cf_api", os.path.join(HERE, "docs", "agent", "cf_api.py"))
cf_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cf_api)


def mt(p):
    if not os.path.exists(p):
        return "—"
    return dt.datetime.fromtimestamp(os.path.getmtime(p), TZ).strftime("%H:%M:%S")


def lines(p):
    if not os.path.exists(p):
        return 0
    n = 0
    for line in io.open(p, encoding="utf-8", errors="replace"):
        if line.strip():
            n += 1
    return n


now = dt.datetime.now(TZ).strftime("%H:%M:%S")
print("=== %s CST ｜ 观察对象：主 agent 一轮（%s） ===" % (now, DATE))

# 1) 会话
st, body = cf_api.call("POST", "/chat-feed/api/ss", {})
try:
    j = json.loads(body)
    print("[会话] %s ｜ %s ｜ needWake=%s ｜ err=%r"
          % (j.get("sessionTitle"), "→".join(j.get("steps") or [])[-60:],
             j.get("needWake"), j.get("lastError")))
except Exception:  # noqa: BLE001
    print("[会话] HTTP %s %s" % (st, body[:200]))

# 2) 面板 + 主 agent 最近一条
st, body = cf_api.call("GET", "/chat-feed/api/state")
try:
    s = json.loads(body)
    items = s.get("items") or []
    new = [i for i in items if i.get("isNew")]
    done = [i for i in items if i.get("done")]
    kinds = {}
    for i in items:
        kinds[i.get("kind")] = kinds.get(i.get("kind"), 0) + 1
    print("[面板] %d 条 %s ｜【新】%d ｜已勾选 %d ｜ saveOk=%s err=%r ｜ lastCollectAt=%s"
          % (len(items), kinds, len(new), len(done), s.get("saveOk"), s.get("lastError"),
             dt.datetime.fromtimestamp((s.get("lastCollectAt") or 0) / 1000, TZ).strftime("%H:%M:%S")
             if s.get("lastCollectAt") else "—"))
    if new:
        print("       【新】: %s" % ", ".join("%s(%s)" % (i.get("id"), i.get("kind")) for i in new))
except Exception as e:  # noqa: BLE001
    print("[面板] 解析失败 %s / %s" % (e, body[:200]))

st, body = cf_api.call("GET", "/chat-feed/api/chat")
try:
    j = json.loads(body)
    msgs = j.get("messages") or []
    last_a = None
    for m in msgs:
        if m.get("role") == "assistant":
            last_a = m
    print("[对话] 共 %s 条 ｜ 最后一条 assistant：%s"
          % (j.get("count"), "无" if not last_a else "%d 字" % len(last_a.get("text") or "")))
    if last_a:
        t = (last_a.get("text") or "")
        print("  ┌" + t[:900].replace("\n", "\n  │"))
except Exception as e:  # noqa: BLE001
    print("[对话] 解析失败 %s" % e)

# 3) 产物
print("[产物]")
checks = [
    ("output/days/%s.jsonl" % DATE, True),
    ("output/days/%s_brief.md" % DATE, False),
    ("output/days/%s_images.json" % DATE, False),
    ("output/daily/%s/prep_report.md" % DATE, False),
    ("output/daily/%s/items.json" % DATE, True),
    ("docs/debug_%s.md" % DATE, False),
    ("docs/archive/%s_expired.md" % DATE, False),
    ("docs/信息列表.md", True),
]
for rel, show_lines in checks:
    p = os.path.join(HERE, rel)
    print("  %-42s %s %s" % (rel, mt(p), ("%d 行" % lines(p)) if show_lines and os.path.exists(p) else ""))
