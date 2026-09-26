# -*- coding: utf-8 -*-
r"""批量回写知识库：**一次调用写完多个文件**（省主 agent 的步数）。

为什么要有它（2026-09-17 夜，用户问"2.8 可以再节约吗"）：
  实测那一轮 paratera **119 步 / ¥2.80 ⇒ 一步 ≈ ¥0.024**，而每一步都要把整个上下文重读一遍。
  收尾要写 `knowledge\{people,channels,lessons,style,preferences,official_accounts}.md`
  ＋ `resources.md` ＋ `DEV_NOTES.md` —— 每个文件"read 一次 + edit 一次"＝**2 步**，
  一轮下来 12–20 步。合并成一次调用是**纯赚**（不改任何语义）。

用法（在本工具目录下）：
    ..\\venv\\Scripts\\python.exe tools\\kb_append.py spec.json
    ..\\venv\\Scripts\\python.exe tools\\kb_append.py spec.json --dry     # 只预览，不落盘

spec.json（UTF-8 数组；每项一条写入）：
    [
      {"file": "docs/knowledge/lessons.md",  "text": "- **A46 …**：…"},
      {"file": "docs/knowledge/people.md",   "text": "| 张三 | … |", "after": "| 李四 |"},
      {"file": "docs/knowledge/channels.md", "text": "…", "before": "## 三、"},
      {"file": "docs/DEV_NOTES.md",          "text": "…", "ensure_absent": "A46"}
    ]

字段：
  file           必填，工作区相对路径；**只允许 docs/ 下的 .md**（越界直接拒）
  text           必填，要插入的文本（可多行；末尾不必带换行）
  after          可选，插在**最后一条**包含该子串的行之后（不传＝追加到文件末尾）
  before         可选，插在**第一条**包含该子串的行之前
  ensure_absent  可选，文件里已含该子串就跳过（**幂等**：同一轮重跑不会写两遍）
  ensure_absent_any  可选，数组；**任何一个**子串已存在于该文件就跳过（用于"编号 A47 有没有被占用"这类查重）

内置闸门（都是项目既有硬规则，这里机器化）：
  1. **不许新开「补录块」**：text 里出现 `补录 / 二次补录 / <日期> …补（ / <日期> …新增（` 这类**新块标题** → 拒绝该条
     （口径与 `tools\\check_knowledge_style.py` 的 BAD 正则一致；**行内叙述不算**）；
  2. **只增不覆盖**：本脚本只做插入，从不改写既有行；
  3. **只写 docs/ 下的 .md**。

退出码：0 = 全部成功（含"按 ensure_absent 跳过"）；1 = 有条目被拒或失败（逐条打印原因，不静默）。
"""
import argparse
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))       # agent 根（＝包内 agent/ 或 <个人目录>）

# 与 check_knowledge_style.py 的 BAD 同口径：查"新块标题"，不查行内叙述
BAD = re.compile(r"^(#{2,4})\s*.*(补录|二次补录|(\d{2}-\d{2}|20\d{2}-\d{2}-\d{2}).{0,12}(补|新增|并入)\s*[（(])")


def _read(path):
    return io.open(path, encoding="utf-8", errors="replace").read()


def _write(path, text):
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)


def _insert(lines, text, after, before):
    """返回 (新行列表, 动作名)。after/before 都为空 ⇒ 追加到末尾。"""
    block = text.split("\n")
    if before:
        for i, ln in enumerate(lines):
            if before in ln:
                return lines[:i] + block + lines[i:], "inserted-before:%d" % (i + 1)
        return None, "anchor-not-found(before)"
    if after:
        hit = -1
        for i, ln in enumerate(lines):
            if after in ln:
                hit = i
        if hit < 0:
            return None, "anchor-not-found(after)"
        return lines[:hit + 1] + block + lines[hit + 1:], "inserted-after:%d" % (hit + 1)
    tail = list(lines)
    while tail and tail[-1].strip() == "":
        tail.pop()
    return tail + block + [""], "appended"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="JSON 文件（数组）；用 - 表示从 stdin 读")
    ap.add_argument("--dry", action="store_true", help="只预览，不落盘")
    a = ap.parse_args(argv)

    raw = sys.stdin.read() if a.spec == "-" else _read(a.spec)
    raw = raw.lstrip("\ufeff")                                  # 容忍 PowerShell 写出的 BOM
    try:
        spec = json.loads(raw)
    except Exception as e:                                     # noqa: BLE001
        print("spec 不是合法 JSON：%s" % e)
        return 1
    if not isinstance(spec, list):
        print("spec 必须是数组（每项一条写入）")
        return 1
    if not spec:
        # 2026-09-17 教训（别的项目）：**空列表会静默"全过"** ⇒ 必须显式报出来，别让它伪装成成功
        print("spec 是空数组：没有任何写入项（这不是成功，是没活干）")
        return 1

    ok, bad, skipped = 0, 0, 0
    for n, item in enumerate(spec, 1):
        tag = "#%d" % n
        if not isinstance(item, dict):
            print("%s  拒：不是对象" % tag)
            bad += 1
            continue
        rel = str(item.get("file") or "")
        text = str(item.get("text") or "")
        if not rel or not text.strip():
            print("%s  拒：file / text 必填" % tag)
            bad += 1
            continue
        rel = rel.replace("\\", "/")
        if not rel.startswith("docs/") or not rel.endswith(".md"):
            print("%s  拒：只允许写 docs/ 下的 .md（收到 %s）" % (tag, rel))
            bad += 1
            continue
        path = os.path.join(HERE, rel)
        if not os.path.exists(path):
            print("%s  拒：文件不存在 %s" % (tag, rel))
            bad += 1
            continue
        # 闸门 1：不许新开补录块
        hit_bad = [ln for ln in text.split("\n") if BAD.match(ln.rstrip())]
        if hit_bad:
            print("%s  拒：text 里出现了「补录块」式标题 ⇒ %s" % (tag, hit_bad[0].strip()[:60]))
            bad += 1
            continue
        cur = _read(path)
        # 幂等
        needle = str(item.get("ensure_absent") or "")
        if needle and needle in cur:
            print("%s  跳过（已存在 %s）：%s" % (tag, needle[:30], rel))
            skipped += 1
            continue
        # 查重（多个候选子串，任一命中即跳过）—— 2026-09-17 夜加：编号撞车（A46 已被占用）就是这么漏的
        anylist = item.get("ensure_absent_any") or []
        if isinstance(anylist, list):
            dup = [x for x in anylist if x and str(x) in cur]
            if dup:
                print("%s  跳过（已存在 %s）：%s" % (tag, str(dup[0])[:30], rel))
                skipped += 1
                continue
        lines = cur.split("\n")
        newlines, action = _insert(lines, text, str(item.get("after") or ""), str(item.get("before") or ""))
        if newlines is None:
            print("%s  拒：%s（%s）" % (tag, action, rel))
            bad += 1
            continue
        if not a.dry:
            _write(path, "\n".join(newlines))
        print("%s  %s  %s  +%d 行" % (tag, "预览" if a.dry else "已写", rel, len(text.split("\n"))))
        ok += 1

    print("—— 合计：成功 %d ／ 跳过 %d ／ 被拒 %d%s" % (ok, skipped, bad, "（--dry 预览，未落盘）" if a.dry else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
