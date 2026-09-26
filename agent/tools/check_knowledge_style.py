# -*- coding: utf-8 -*-
"""check_knowledge_style.py — 知识库文档的**写法自检**：禁止"补录块"（2026-09-15）。

规则出处（用户 2026-09-12 原话，记在 `docs/EVOLUTION.md` §六）：
> **维护文档补录的信息直接加进条目即可，不然格式有点混乱**。
> ❌ **禁止**：在文件末尾追加「XX 补录 / 二次补录 / 09-02 新增」这类**新块** —— 它会让同一类信息散在多处。

为什么要有这个脚本：**这条规则 2026-09-15 又被违反了**（`people.md` 3 个补录块、`channels.md` 2 个、
`resources.md` 3 个）。只写进规范、没有任何东西能检查的约束，迟早会被重新破坏 —— 所以把它变成一条能跑出 FAIL 的命令。

用法:
    python tools\\check_knowledge_style.py          # 检查 docs\\knowledge\\*.md + docs\\resources.md
    python tools\\check_knowledge_style.py --all    # 连 docs\\*.md 一起检查（DEV_NOTES/EVOLUTION 里的"补"编号也算）
退出码：0 = 干净；1 = 有违规标题（把行号打出来）
"""
import argparse
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 违规标题：二级/三级标题里出现「补录 / 二次补录 / <日期> 补（ / <日期> 新增（」
# 2026-09-15 收紧：原来要求日期与"新增/补录"之间只有空格 → 漏掉了 `## 2026-09-13 增量轮新增（…）` 这种写法
#   （lessons.md 里真实存在过，靠人工才发现的）。现在允许中间有别的字（如"增量轮"）。
BAD = re.compile(r"^(#{2,4})\s*.*(补录|二次补录|(\d{2}-\d{2}|20\d{2}-\d{2}-\d{2}).{0,12}(补|新增|并入)\s*[（(])")
# 允许的白名单（维护日志用"补录 09-01"这种**行内**叙述是可以的，标题不行；这里只查标题）
OK_HINT = "把内容并进对应条目（人物并进该人的行、群并进该群的行、资源并进对应小节），并在「维护日志」加一行说明"


def scan(path):
    out = []
    for i, ln in enumerate(io.open(path, encoding="utf-8", errors="replace"), 1):
        if BAD.match(ln.rstrip()):
            out.append((i, ln.rstrip()[:120]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="连 docs\\*.md 一起检查")
    a = ap.parse_args()

    files = []
    kd = os.path.join(HERE, "docs", "knowledge")
    if os.path.isdir(kd):
        files += [os.path.join(kd, f) for f in sorted(os.listdir(kd)) if f.endswith(".md")]
    for extra in ("resources.md",):
        p = os.path.join(HERE, "docs", extra)
        if os.path.exists(p):
            files.append(p)
    if a.all:
        # 2026-09-15：排除证据层日志 docs\debug_*.md —— 它的节标题本来就是"按日期/事件连续追加"的形态，
        # 而且会出现「知识库『补录块』清理（2026-09-15）」这种**描述这件事**的标题，被 BAD 正则误判成违规。
        files += [os.path.join(HERE, "docs", f) for f in sorted(os.listdir(os.path.join(HERE, "docs")))
                  if f.endswith(".md") and not f.startswith("debug_")]

    bad_total = 0
    for p in files:
        hits = scan(p)
        if hits:
            print("FAIL  %s" % os.path.relpath(p, HERE))
            for ln, text in hits:
                print("   :%-4d %s" % (ln, text))
            bad_total += len(hits)

    print("\n检查 %d 个文件 ｜ 违规标题 %d 个" % (len(files), bad_total))
    if bad_total:
        print("修法：%s" % OK_HINT)
        print("（规则：`docs/EVOLUTION.md` §六，用户原话「维护文档补录的信息直接加进条目即可，不然格式有点混乱」）")
        return 1
    print("OK：没有「补录 / 二次补录 / XX 补（ / XX 新增（」这类新块。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
