# -*- coding: utf-8 -*-
"""panel_fmt.py — 面板条目 `text` 的**唯一**格式化口径（所有写入面板的通道都必须过它）。

为什么要它（2026-09-13 用户报"舞会那一条中间插了一堆空行，排版不一样"）：
面板 `.cfw-txt` 是 `white-space:pre-wrap` —— **正文里多写一个空行，屏幕上就真空一行**。
实测口径：所有条目都是「一句话总结 + **恰好 1 个空行** + 正文（正文内部**单换行**）」，
只有舞会那条正文内部用了双换行（double-newline 计数 8 vs 其余全部 1），一眼看出不一致。

规则（normalize_text）：
  1. 换行统一成 `\\n`；行尾空格去掉；首尾空白去掉；
  2. **正文内部的多空行一律压成单换行**（`\\n\\n+` → `\\n`）；
  3. 保留**总结与正文之间那一个**空行。
"""
import re

_SEP = "\n\n"


def normalize_text(t):
    t = (t or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in t.split("\n")]
    t = "\n".join(lines).strip()
    if not t:
        return ""
    head, sep, body = t.partition(_SEP)
    head = head.strip()
    if not sep:
        # 没有空行 → 只有一句话总结（或缺分隔），保持原样
        return re.sub(r"\n{2,}", "\n", head)
    body = re.sub(r"\n{2,}", "\n", body).strip()
    return head + (_SEP + body if body else "")


def stats(t):
    """给自检用：字数 / 换行数 / 双换行数。"""
    t = t or ""
    return {"len": len(t), "nl": t.count("\n"), "dbl": t.count("\n\n")}
