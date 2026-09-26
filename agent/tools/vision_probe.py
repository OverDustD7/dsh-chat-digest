# -*- coding: utf-8 -*-
"""vision_probe.py — 小样本实测：本地 qwen3.5:9b（带 vision）能不能担起"读图"。

背景（用户 2026-09-14："回顾整个工作流程，看看还有没有可以用本地小模型降本增效的地方"）：
  图片 token 是全流程最贵的；现在"信息图/海报"都要强模型看图。本地模型 capabilities 里有 vision
  → 先按用户硬要求"**先小样本实测质量与延迟再定管线**"做这一轮探针。

做法：从 output/days/<date>_images.json 里挑**磁盘上真实存在**的图，逐张问本地模型：
  ① 这张图是什么（一句话）② 有没有需要人去做的事（行动项）③ 关键字段（时间/地点/截止/联系人/金额/链接）
  ④ 是不是表情包/梗图/无信息图
产出：output/window/_vision_probe.md（每张：路径/大小/秒数/模型原文），控制台给 ASCII 汇总。
用法：python tools\\vision_probe.py [YYYY-MM-DD] [张数=20]
"""
import base64
import io
import json
import os
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "output")
URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3.5:9b"

SYS = (
    "你在帮一位清华大一新生看群聊里的图片。只看图说话，不要猜。\n"
    "只输出一个 JSON 对象，字段固定：\n"
    '{"what":"这张图是什么（≤20字）","action":true/false,"fields":["时间/地点/截止/联系人/金额/链接里出现的，没有就不写"],'
    '"noise":true/false,"why":"判断依据（≤30字）"}\n'
    "action＝图里有没有需要他去做的具体事（报名/截止/填表/找谁/去哪/交材料）。\n"
    "noise＝表情包/梗图/纯风景/无信息截图。\n"
    "不要解释、不要输出 JSON 以外的任何字。"
)
IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")


def walk_paths(node, acc):
    if isinstance(node, str):
        if node.lower().endswith(IMG_EXT):
            acc.append(node)
    elif isinstance(node, dict):
        for v in node.values():
            walk_paths(v, acc)
    elif isinstance(node, list):
        for v in node:
            walk_paths(v, acc)


def find_images(date, n):
    p = os.path.join(OUT, "days", "%s_images.json" % date)
    if not os.path.exists(p):
        return [], "缺 %s" % p
    j = json.loads(io.open(p, encoding="utf-8", errors="replace").read())
    acc = []
    walk_paths(j, acc)
    # 2026-09-14 实测：索引里 **`path`** 才是真路径，形如 `["<群名>/<hash>.jpg"]`，
    # 真实文件在 `output/window/images/<群名>/<hash>.jpg`（md5 字段是另一种哈希，对不上文件名）
    for it in (j if isinstance(j, list) else []):
        if not isinstance(it, dict):
            continue
        for rel in (it.get("path") or []):
            cand = os.path.join(HERE, "output", "window", "images", rel.replace("/", os.sep))
            if os.path.exists(cand):
                acc.append(cand)
    seen, out = set(), []
    for a in acc:
        for cand in (a, os.path.join(HERE, a), os.path.join(HERE, "output", a)):
            if os.path.exists(cand) and cand not in seen:
                seen.add(cand)
                out.append(cand)
                break
    return out, "索引里提到 %d 个路径，磁盘上存在 %d 个" % (len(acc), len(out))


def ask(path):
    raw = io.open(path, "rb").read()
    b64 = base64.b64encode(raw).decode()
    payload = {"model": MODEL, "stream": False, "think": False,
               "options": {"temperature": 0, "num_predict": 300},
               "messages": [{"role": "system", "content": SYS},
                            {"role": "user", "content": "看这张图。", "images": [b64]}]}
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    dt = time.time() - t0
    txt = ((j.get("message") or {}).get("content") or "").strip()
    m = re.search(r"\{[\s\S]*\}", txt)
    obj = None
    if m:
        try:
            obj = json.loads(m.group(0))
        except Exception:
            obj = None
    return obj, dt, txt


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-09-13"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    imgs, note = find_images(date, n)
    print(note)
    if not imgs:
        return 1
    # 均匀取样（避免只取到开头那批）
    step = max(1, len(imgs) // n)
    pick = imgs[::step][:n]
    print("取样 %d 张（共 %d）" % (len(pick), len(imgs)))
    rows, ok, noise, act, tot, txts = [], 0, 0, 0, 0.0, []
    for i, p in enumerate(pick, 1):
        try:
            obj, dt, txt = ask(p)
        except Exception as e:
            obj, dt, txt = None, 0.0, "ERR:%s" % e
        tot += dt
        sz = os.path.getsize(p) // 1024
        tag = "?"
        if obj:
            ok += 1
            if obj.get("noise"):
                noise += 1
            if obj.get("action"):
                act += 1
            tag = ("noise" if obj.get("noise") else ("action" if obj.get("action") else "info"))
        print("  %2d/%d %5ds %6dKB %-6s %s" % (i, len(pick), round(dt), sz, tag, os.path.basename(p)[:44]))
        rows.append((p, sz, round(dt, 1), tag, json.dumps(obj, ensure_ascii=False) if obj else txt[:200]))
    out = os.path.join(OUT, "window", "_vision_probe.md")
    L = ["# 本地视觉实测（%s，取样 %d 张）" % (date, len(pick)), "",
         "> 模型：%s（本机 Ollama）｜解析成功 %d/%d｜判为 noise %d｜判为 action %d｜总耗时 %.1fs（均 %.1fs/张）"
         % (MODEL, ok, len(pick), noise, act, tot, tot / max(1, len(pick))), ""]
    for p, sz, dt, tag, body in rows:
        L.append("- `%s`（%dKB，%.1fs，**%s**）" % (os.path.relpath(p, HERE), sz, dt, tag))
        L.append("  %s" % body)
    io.open(out, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
    print("OK parsed=%d/%d noise=%d action=%d total=%.1fs avg=%.1fs -> %s"
          % (ok, len(pick), noise, act, tot, tot / max(1, len(pick)), out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
