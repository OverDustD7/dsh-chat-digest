# -*- coding: utf-8 -*-
"""read_chat_tail.py — 看主 agent 会话最近几条消息（只读，直接走 cf_api 的签名 cookie）。

用法:
    python tools\\read_chat_tail.py [条数] [每条字符数]
数据来源：插件 `GET /chat-feed/api/chat`（Host 读 sessionController.inspect 的最近 40 条）。
"""
import importlib.util
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CF_API = os.path.join(HERE, "docs", "agent", "cf_api.py")

spec = importlib.util.spec_from_file_location("cf_api", CF_API)
cf_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cf_api)

n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
width = int(sys.argv[2]) if len(sys.argv) > 2 else 700

status, body = cf_api.call("GET", "/chat-feed/api/chat")
if status != 200:
    print("HTTP", status, body[:400])
    sys.exit(1)
j = json.loads(body)
if not j.get("ok"):
    print("chat 返回错误：", json.dumps(j, ensure_ascii=False)[:400])
    sys.exit(1)
msgs = j.get("messages") or []
print("HTTP %s ｜ count=%s ｜ 显示最后 %d 条" % (status, j.get("count"), min(n, len(msgs))))
for i, m in enumerate(msgs[-n:], 1):
    t = (m.get("text") or "")
    print("-" * 100)
    print("[%d] %-9s %d 字" % (i, m.get("role"), len(t)))
    print(t[:width] + ("\n…（后略 %d 字）" % (len(t) - width) if len(t) > width else ""))
