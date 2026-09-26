# -*- coding: utf-8 -*-
"""say_to_main.py — 把一段文本作为用户消息发给「聊天情报 · 主 Agent」（走插件的 /say）。

用法:
    python tools\\say_to_main.py <文本文件.md>
    python tools\\say_to_main.py --dry-run <文本文件.md>      # 只打印将发送的内容

原理：`POST /chat-feed/api/say {text}` → Host 里 `sessionController.prompt(...)` 把它排进主 agent 会话，
它就会跑一个 turn（这就是面板输入框那条链路）。认证走 `docs\\agent\\cf_api.py` 的签名 cookie。
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

argv = [a for a in sys.argv[1:] if a]
dry = "--dry-run" in argv
argv = [a for a in argv if a != "--dry-run"]
if not argv:
    print(__doc__)
    sys.exit(2)

path = argv[0] if os.path.isabs(argv[0]) else os.path.join(HERE, argv[0])
text = io.open(path, encoding="utf-8").read().strip()
if not text:
    print("文本为空，不发")
    sys.exit(2)
print("将发送 %d 字 → 主 agent（来源 %s）" % (len(text), os.path.relpath(path, HERE)))
if dry:
    print("-" * 100)
    print(text)
    sys.exit(0)

status, body = cf_api.call("POST", "/chat-feed/api/say", {"text": text})
print("HTTP", status)
print(body[:800])
j = None
try:
    j = json.loads(body)
except Exception:  # noqa: BLE001
    pass
if not (isinstance(j, dict) and j.get("ok")):
    print("发送失败")
    sys.exit(1)
print("已投递（主 agent 会跑一个 turn；用 tools\\read_chat_tail.py 看它的进度）")
