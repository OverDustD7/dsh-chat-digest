#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""media_ledger.py —— 逐类媒体覆盖账本（只读，不联网，不抓取，不改既有产物）

用途
----
给定一个日期，读当天**已经存在的**产物，产出一份「逐类覆盖账本」：
每一类媒体（文章 / 图片 / 文件附件 / QQ 媒体 / 音视频）分别回答三个问题：
  1. 这一类当天一共有多少条？
  2. 其中多少条做到了**逐条状态**（能指到具体某一条、有明确结论）？
  3. 哪一类只有**总数**、哪一类**完全没接线**？

用法
----
    cd <个人目录>
    ..\\venv\\Scripts\\python.exe tools\\media_ledger.py 2026-09-17 [--json]

（必须用 ..\\venv\\Scripts\\python.exe；裸 python 不是本项目的 venv。）
产物：output\\days\\<date>_coverage.md（总是写）
      output\\days\\<date>_coverage.json（仅 --json）
stdout：始终打印那份 markdown 全文。

口径（重要）
------------
- 文章：主口径是机器解析 output\\days\\<date>_articles.md 的「一、带标题的文章卡片」小节，
  逐条读 `- ` 行，并按紧随其后的 `  - **有正文：...**` / `  - **本地无正文**` 标记分类。
  该 md 是人读 markdown，解析规则写死为「一级小节标题 + `- ` 条目 + 缩进标记行」；
  解析不到（小节缺失 / 标记一个都没有）时**不硬编造**，退化为「按 jsonl 里 http 出现次数」
  统计，并在报告里注明口径已退化。
- 图片：条数取 _images.json 数组长度；「有非空本地路径」取 path 为非空数组的条数。
  _vision.md 的三类计数用**关键词 grep**（关键词与口径在报告里原文列出），
  而不是假装能结构化解析这份人读 md。
- 文件附件：完全读 _files.json 的 summary / readable / read_status 字段（机器可解析）。
- QQ 媒体：只读打开 output\\qq\\nt_msg_export.db，统计 group_messages / c2c_messages
  的 content_type 分布。表不存在必须 try/except 兜住并如实写「表不存在」。
- 音视频：_files.json 里 readable == "av-unread" 的条数；本线不转写。

为什么「静默漏报边界」才是问题
------------------------------
这套流水线每天产出十几个文件，缺一个产物时最危险的失败模式不是报错，而是
**报告照样生成、只是那一类悄悄变成 0 或干脆不出现**：读者看到「0 条」会以为
「当天确实没有」，而真实情况是「那个索引文件今天没生成」。
所以本工具的硬规矩是：**存在才读，缺哪个必须在报告里显式写「缺，未统计」**，
并单独列出「未统计到的类 + 原因」。宁可报告长一点、丑一点，也不许把
「没查」伪装成「没有」——因为「没查」会被下游当成「没有」用来下结论。
"""

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import sqlite3
import sys

#: CST（+8）—— 本机时区不可信，一律显式偏移（与 daily_prep 同一口径）
TZ = dt.timezone(dt.timedelta(hours=8))

# ---------------------------------------------------------------- 基础工具

# 常量：缺产物时的统一措辞，保证报告里一定出现「缺，未统计」
MISSING_NOTE = "缺，未统计"


def _setup_stdout():
    """Windows 控制台默认不是 UTF-8，强制 stdout/stderr 用 UTF-8 输出中文。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def load_json(path):
    """读 JSON。返回 (数据, 错误说明)。不存在或读不动时数据为 None，错误说明非空。"""
    if not os.path.exists(path):
        return None, "%s（文件不存在）" % MISSING_NOTE
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh), ""
    except Exception as exc:
        return None, "%s（读取失败：%s）" % (MISSING_NOTE, exc)


def load_text(path):
    """读文本。返回 (文本, 错误说明)。"""
    if not os.path.exists(path):
        return None, "%s（文件不存在）" % MISSING_NOTE
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(), ""
    except Exception as exc:
        return None, "%s（读取失败：%s）" % (MISSING_NOTE, exc)


def read_jsonl(path):
    """逐行读 jsonl。返回 (记录列表, 坏行数, 错误说明)。"""
    if not os.path.exists(path):
        return [], 0, "%s（文件不存在）" % MISSING_NOTE
    rows, bad = [], 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    bad += 1
    except Exception as exc:
        return [], bad, "%s（读取失败：%s）" % (MISSING_NOTE, exc)
    return rows, bad, ""


def miss(msg):
    """统一构造「缺，未统计」措辞，并压掉嵌套产生的重复前缀。"""
    text = str(msg)
    if text.startswith(MISSING_NOTE):
        return text
    return "%s（%s）" % (MISSING_NOTE, text)


def open_ro(db_path):
    """只读打开 SQLite（mode=ro + uri=True）。返回 (连接, 使用的打开方式, 错误说明)。"""
    if not os.path.exists(db_path):
        return None, "", "%s（数据库不存在）" % MISSING_NOTE
    # 一律 mode=ro + uri=True。优先再叠加 immutable=1：
    # 纯 mode=ro 打开带 WAL 的库时 SQLite 仍会创建/触碰 -shm 文件，那也算动了别人的产物目录；
    # immutable=1 完全不碰 -shm / -wal（代价是假定该库在本进程读取期间不会被别的进程改写，
    # 对「只读账本」这个用途成立）。immutable 打开失败则回退纯 mode=ro，并如实记录用的是哪种。
    base = db_path.replace("\\", "/")
    attempts = [
        ("file:%s?mode=ro&immutable=1" % base, "mode=ro&immutable=1"),
        ("file:%s?mode=ro" % base, "mode=ro"),
    ]
    last_exc = None
    for uri, label in attempts:
        try:
            con = sqlite3.connect(uri, uri=True)
            # 触发一次真实读取，确认这个打开方式确实能用（immutable 下损坏/锁冲突会在此暴露）
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return con, label, ""
        except Exception as exc:
            last_exc = exc
            try:
                con.close()
            except Exception:
                pass
    return None, "", "%s（只读打开失败：%s）" % (MISSING_NOTE, last_exc)


def table_exists(con, name):
    try:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None
    except Exception:
        return False


def counter_to_sorted(counter):
    """Counter -> [[键, 条数], ...]，按条数降序、键字符串升序（保证可复现）。"""
    return [[str(k), v] for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))]


def fmt_counter(counter):
    if not counter:
        return "（无）"
    return "；".join("%s=%d" % (k, v) for k, v in counter_to_sorted(counter))


def show_val(v):
    """渲染一个统计值：None 一律显式写成「缺，未统计」，绝不静默留空。"""
    if v is None:
        return miss("未能从产物解析出该数字")
    return v


# ---------------------------------------------------------------- 1. 文章

ART_HEAD_RE = re.compile(r"^##\s+一、")
ART_SEC_RE = re.compile(r"^##\s+")
ART_ITEM_RE = re.compile(r"^-\s+")
ART_HAS_BODY_RE = re.compile(r"^\s+-\s+\*\*有正文")
ART_NO_BODY_RE = re.compile(r"^\s+-\s+\*\*本地无正文")
# 空占位行：`- （无）` / `- 无` / `- -`，是「本小节 0 条」的写法，不是条目，不能计进卡片数
ART_PLACEHOLDER_RE = re.compile(r"^-\s*[（(]?\s*(无|none|None|N/A|-|—|–)\s*[)）]?\s*$")
HTTP_RE = re.compile(r"http")


def section_articles(date, day_dir):
    """文章覆盖：主口径解析 _articles.md 第一节；解析不了则退化为 jsonl http 计数。"""
    md_path = os.path.join(day_dir, "%s_articles.md" % date)
    jsonl_path = os.path.join(day_dir, "%s.jsonl" % date)
    text, err = load_text(md_path)

    out = {
        "产物": md_path,
        "产物状态": err if err else "存在，已读",
        "口径": "",
        "卡片条数": None,
        "有正文条数": None,
        "缺正文条数": None,
        "缺正文占比": "",
        "解析退化": False,
        "占位行数": None,
        "jsonl_http_出现次数": None,
        "jsonl_含http消息条数": None,
        "jsonl_坏行数": None,
        "结论": "缺正文 ⇒ 不得据此下“已读”结论",
        "jsonl产物": jsonl_path,
        "jsonl产物状态": "",
    }

    # jsonl 口径（作为旁证/退化口径，永远尽量算）
    rows, bad, jerr = read_jsonl(jsonl_path)
    if not jerr:
        out["jsonl产物状态"] = "存在，已读（%d 条消息）" % len(rows)
        http_hits = 0
        msg_with = 0
        for rec in rows:
            t = rec.get("text") or ""
            c = len(HTTP_RE.findall(t))
            if c:
                msg_with += 1
                http_hits += c
        out["jsonl_http_出现次数"] = http_hits
        out["jsonl_含http消息条数"] = msg_with
        out["jsonl_坏行数"] = bad
    else:
        out["jsonl产物状态"] = jerr
        out["jsonl_http_出现次数"] = miss("jsonl " + jerr)
        out["jsonl_含http消息条数"] = miss("jsonl " + jerr)
        out["jsonl_坏行数"] = miss("jsonl " + jerr)

    if err:
        out["口径"] = "无法解析（_articles.md %s）；jsonl http 口径也不可用则本类完全未统计" % err
        return out

    lines = text.splitlines()
    # 定位「一、」小节
    start = None
    for i, ln in enumerate(lines):
        if ART_HEAD_RE.match(ln):
            start = i
            break
    if start is None:
        out["口径"] = "无法解析：_articles.md 里找不到「## 一、」小节"
        out["解析退化"] = True
        return out

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if ART_SEC_RE.match(lines[j]):
            end = j
            break

    items, has_body, no_body, placeholders = 0, 0, 0, 0
    for ln in lines[start + 1:end]:
        if ART_PLACEHOLDER_RE.match(ln):
            # `- （无）` 是「本小节 0 条」的占位写法，单独计数，不算卡片
            placeholders += 1
        elif ART_ITEM_RE.match(ln):
            items += 1
        elif ART_HAS_BODY_RE.match(ln):
            has_body += 1
        elif ART_NO_BODY_RE.match(ln):
            no_body += 1

    if items == 0 and has_body == 0 and no_body == 0:
        # 该小节是「- （无）」这种空占位，仍然算可解析的 0 条
        out["解析退化"] = False
        out["占位行数"] = placeholders
        out["口径"] = ("机器解析 _articles.md 的「## 一、带标题的文章卡片」小节："
                       "该小节只有空占位行（%d 行，已单独计数、不计为卡片），"
                       "既无条目也无正文标记，故当天卡片数为 0" % placeholders)
        out["卡片条数"] = 0
        out["有正文条数"] = 0
        out["缺正文条数"] = 0
        out["缺正文占比"] = "无卡片，不适用"
        return out

    out["占位行数"] = placeholders

    if has_body == 0 and no_body == 0:
        # 有条目但一个正文标记都没有 —— 不硬编造，退化为 jsonl http 口径
        out["解析退化"] = True
        out["口径"] = ("_articles.md 第一节有 %d 个条目，但一条正文标记（有正文 / 本地无正文）都解析不到；"
                       "不硬编造，退化为 jsonl 口径：text 里 http 出现 %s 次（含 http 的消息 %s 条）"
                       % (items, out["jsonl_http_出现次数"], out["jsonl_含http消息条数"]))
        out["卡片条数"] = items
        return out

    out["口径"] = ("机器解析 _articles.md 的「## 一、带标题的文章卡片」小节："
                   "`- ` 行为卡片条目，缩进标记 `**有正文：<路径>（N 字符）**` 记为有正文，"
                   "`**本地无正文**` 记为缺正文")
    out["卡片条数"] = items
    out["有正文条数"] = has_body
    out["缺正文条数"] = no_body
    if items:
        out["缺正文占比"] = "%.1f%%（%d/%d）" % (100.0 * no_body / items, no_body, items)
    else:
        out["缺正文占比"] = "无卡片，不适用"
    return out


# ---------------------------------------------------------------- 2. 图片

VISION_KEYWORDS = {
    "需回看": "需强模型回看",
    "判为无信息": "判为无信息",
    "解析失败": "解析失败",
    "细读失败": "细读失败",
    "必须回看原图": "必须回看原图",
}


def section_images(date, day_dir):
    """图片覆盖：_images.json 条数 + 非空路径数；_vision.md 关键词 grep 三类计数。"""
    img_path = os.path.join(day_dir, "%s_images.json" % date)
    vis_path = os.path.join(day_dir, "%s_vision.md" % date)

    data, err = load_json(img_path)
    out = {
        "产物": img_path,
        "产物状态": err if err else "存在，已读",
        "索引条数": None,
        "有非空本地路径条数": None,
        "无本地路径条数": None,
        "path字段类型异常条数": None,
        "分诊产物": vis_path,
        "分诊产物状态": "",
        "grep关键词": VISION_KEYWORDS,
        "grep口径": ("在 _vision.md 全文上做**中文子串计数**（无大小写问题，直接 str.count）："
                     "需回看=出现「需强模型回看」的次数；判为无信息=出现「判为无信息」的次数；"
                     "解析失败=出现「解析失败」的次数；另附「细读失败」「必须回看原图」两个辅助关键词。"
                     "注意这是**关键词出现次数**（同一数字会同时出现在表头引用行与末尾自证表里，"
                     "所以天然会重复计数），**不等于条目数**；"
                     "故同时给出「小节条目数」（去重后的条目）与「自证表原值」两列交叉校验，"
                     "读数以交叉校验为准，关键词计数只用于确认「这几个词确实出现过」。"),
        "关键词计数": {},
        "小节条目数": {},
        "自证表数字": {},
        "必须回看原图条目数": None,
    }

    if err:
        out["索引条数"] = miss(err)
        out["有非空本地路径条数"] = miss(err)
        out["无本地路径条数"] = miss(err)
        out["path字段类型异常条数"] = miss(err)
    elif not isinstance(data, list):
        out["索引条数"] = miss("_images.json 顶层不是数组，实际是 %s" % type(data).__name__)
        out["有非空本地路径条数"] = miss("形状不符")
        out["无本地路径条数"] = miss("形状不符")
        out["path字段类型异常条数"] = miss("形状不符")
    else:
        nonempty = 0
        weird = 0
        for rec in data:
            if not isinstance(rec, dict):
                weird += 1
                continue
            p = rec.get("path")
            if isinstance(p, list):
                if len(p) > 0:
                    nonempty += 1
            elif isinstance(p, str):
                if p.strip():
                    nonempty += 1
            elif p is None:
                pass
            else:
                weird += 1
        out["索引条数"] = len(data)
        out["有非空本地路径条数"] = nonempty
        out["无本地路径条数"] = len(data) - nonempty
        out["path字段类型异常条数"] = weird

    vtext, verr = load_text(vis_path)
    if verr:
        out["分诊产物状态"] = verr
        for k in VISION_KEYWORDS:
            out["关键词计数"][k] = miss(verr)
        out["小节条目数"] = miss(verr)
        out["自证表数字"] = miss(verr)
        out["必须回看原图条目数"] = miss(verr)
        return out

    out["分诊产物状态"] = "存在，已读"
    for label, kw in VISION_KEYWORDS.items():
        out["关键词计数"][label] = vtext.count(kw)
    out["必须回看原图条目数"] = sum(
        1 for ln in vtext.splitlines()
        if ln.startswith("  - ") and VISION_KEYWORDS["必须回看原图"] in ln
    )

    # 小节条目数：`- ` 开头且带「｜」分隔的条目行，按 ## 小节归集
    sec_counts = collections.Counter()
    cur = None
    for ln in vtext.splitlines():
        if ln.startswith("## "):
            cur = ln[3:].strip()
            sec_counts.setdefault(cur, 0)
        elif cur is not None and ln.startswith("- ") and "｜" in ln:
            sec_counts[cur] += 1
    out["小节条目数"] = dict(sec_counts)

    # 自证表：抓「| 需回看 | 75 |」这类行
    selfcheck = {}
    for ln in vtext.splitlines():
        m = re.match(r"^\|\s*\**([^|*]+?)\**\s*\|\s*([^|]+?)\s*\|\s*$", ln)
        if m:
            selfcheck[m.group(1).strip()] = m.group(2).strip()
    out["自证表数字"] = selfcheck
    return out


# ---------------------------------------------------------------- 3. 文件附件

def section_files(date, day_dir):
    """文件附件覆盖：_files.json 的 summary + readable 分布 + read_status 分布。"""
    path = os.path.join(day_dir, "%s_files.json" % date)
    data, err = load_json(path)
    out = {
        "产物": path,
        "产物状态": err if err else "存在，已读",
        "summary": None,
        "referenced": None,
        "found": None,
        "missing": None,
        "files数组条数": None,
        "readable分布": None,
        "read_status分布": None,
        "readable与read_status交叉": None,
        "missing口径": "missing 是“本机没有”，不是“没查”",
    }
    if err:
        for k in ("summary", "referenced", "found", "missing", "files数组条数",
                  "readable分布", "read_status分布", "readable与read_status交叉"):
            out[k] = miss(err)
        return out
    if not isinstance(data, dict):
        msg = miss("_files.json 顶层不是对象，实际是 %s" % type(data).__name__)
        for k in ("summary", "referenced", "found", "missing", "files数组条数",
                  "readable分布", "read_status分布", "readable与read_status交叉"):
            out[k] = msg
        return out

    summary = data.get("summary")
    out["summary"] = summary if summary is not None else miss("无 summary 字段")
    if isinstance(summary, dict):
        out["referenced"] = summary.get("referenced", miss("summary 无 referenced"))
        out["found"] = summary.get("found", miss("summary 无 found"))
        out["missing"] = summary.get("missing", miss("summary 无 missing"))
    else:
        out["referenced"] = miss("summary 形状不符")
        out["found"] = miss("summary 形状不符")
        out["missing"] = miss("summary 形状不符")

    files = data.get("files")
    if not isinstance(files, list):
        msg = miss("无 files 数组或形状不符")
        out["files数组条数"] = msg
        out["readable分布"] = msg
        out["read_status分布"] = msg
        out["readable与read_status交叉"] = msg
        return out

    out["files数组条数"] = len(files)
    rd = collections.Counter()
    rs = collections.Counter()
    cross = collections.Counter()
    for rec in files:
        if not isinstance(rec, dict):
            rd["<非对象条目>"] += 1
            continue
        a = rec.get("readable")
        b = rec.get("read_status")
        rd["<缺失>" if a is None else str(a)] += 1
        rs["<缺失>" if b is None else str(b)] += 1
        cross["%s / %s" % ("<缺失>" if a is None else a, "<缺失>" if b is None else b)] += 1
    out["readable分布"] = counter_to_sorted(rd)
    out["read_status分布"] = counter_to_sorted(rs)
    out["readable与read_status交叉"] = counter_to_sorted(cross)
    return out


# ---------------------------------------------------------------- 4. QQ 媒体

QQ_TABLES = ("group_messages", "c2c_messages")


def _ts_unit(con, table):
    """判断 `timestamp` 是**秒**还是**毫秒**。

    实测 2026-09-22：两表都是**秒级**（`group_messages` max=1789665646 → 2026-09-18 01:20；
    `c2c_messages` max=1789643956 → 2026-09-17 19:19）。写成自适应（>1e11 视为毫秒），
    这样导出器将来换单位也不会把"当天"算成 1970 年。
    """
    try:
        mx = con.execute("SELECT max(timestamp) FROM %s" % table).fetchone()[0] or 0
    except Exception:
        return 1
    try:
        return 1000 if float(mx) > 1e11 else 1
    except (TypeError, ValueError):
        return 1


def section_qq(date, db_path):
    """QQ 媒体：只读打开 nt_msg_export.db，统计两表 content_type 分布 **＋ 当天那一份**。

    A13 验收里的"QQ 媒体实际定位"原先只给了**整库**分布（理由是"没有日索引列、按天切不安全"）——
    但 2026-09-22 实测两表的 `timestamp` 都是**秒级**且可用，所以现在**按天切**：
    `WHERE timestamp >= 当天0点 AND < 次日0点`，并同时保留整库分布做对照。
    仍然如实写明"QQ 的图片/视频/语音**没有**与微信同等的日索引接线"（这是接线事实，不是数据问题）。
    """
    day_lo_ms = int(dt.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=TZ).timestamp() * 1000)
    day_hi_ms = day_lo_ms + 86400 * 1000
    out = {
        "产物": db_path,
        "产物状态": "",
        "打开方式": "",
        "表": {},
        "接线事实": "QQ 的图片/视频/语音没有与微信同等的日索引接线",
        "口径": ("只读打开（sqlite3.connect('file:...?mode=ro', uri=True)）；"
                 "**同时给整库与当天的 content_type 分布**："
                 "整库＝`GROUP BY content_type`；当天＝`WHERE timestamp >= 当天0点 AND < 次日0点`。"
                 "timestamp 单位自适应（实测两表均为**秒级**，>1e11 时按毫秒处理）"),
    }
    con, open_mode, err = open_ro(db_path)
    if err:
        out["产物状态"] = err
        out["打开方式"] = miss("未能打开")
        for t in QQ_TABLES:
            out["表"][t] = {"状态": err}
        return out

    try:
        out["打开方式"] = open_mode
        out["产物状态"] = "存在，已只读打开（%s，未创建 -shm / -wal）" % open_mode
        for t in QQ_TABLES:
            entry = {"状态": "", "总条数": None, "content_type分布": None,
                     "当天条数": None, "当天content_type分布": None}
            if not table_exists(con, t):
                entry["状态"] = "表不存在（%s），本表未统计" % t
                entry["总条数"] = miss("表不存在")
                entry["content_type分布"] = miss("表不存在")
                entry["当天条数"] = miss("表不存在")
                entry["当天content_type分布"] = miss("表不存在")
                out["表"][t] = entry
                continue
            try:
                total = con.execute("SELECT count(*) FROM %s" % t).fetchone()[0]
                rows = con.execute(
                    "SELECT content_type, count(*) FROM %s GROUP BY content_type" % t
                ).fetchall()
                cnt = collections.Counter()
                for ct, n in rows:
                    cnt["<NULL>" if ct is None else str(ct)] += n
                entry["状态"] = "已统计"
                entry["总条数"] = total
                entry["content_type分布"] = counter_to_sorted(cnt)
                # ---- 当天那一份（A13「实际定位」）----
                # 边界换算：`day_lo_ms/day_hi_ms` 是**毫秒**，而表里的 timestamp 可能是秒。
                # 写成 `//unit` 是错的（unit=1 时等于没换算 ⇒ 边界成了 1.79e12，永远 0 条）。
                unit = _ts_unit(con, t)                  # 1＝秒，1000＝毫秒
                lo = day_lo_ms // 1000 if unit == 1 else day_lo_ms
                hi = day_hi_ms // 1000 if unit == 1 else day_hi_ms
                entry["当天条数"] = con.execute(
                    "SELECT count(*) FROM %s WHERE timestamp >= ? AND timestamp < ?" % t, (lo, hi)
                ).fetchone()[0]
                day_rows = con.execute(
                    "SELECT content_type, count(*) FROM %s WHERE timestamp >= ? AND timestamp < ? "
                    "GROUP BY content_type" % t, (lo, hi)
                ).fetchall()
                dcnt = collections.Counter()
                for ct, n in day_rows:
                    dcnt["<NULL>" if ct is None else str(ct)] += n
                entry["当天content_type分布"] = counter_to_sorted(dcnt) if dcnt else miss("当天 0 条")
            except Exception as exc:
                entry["状态"] = "查询失败：%s" % exc
                for k in ("总条数", "content_type分布", "当天条数", "当天content_type分布"):
                    entry[k] = miss("查询失败")
            out["表"][t] = entry
    finally:
        try:
            con.close()
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- 5. 音视频

def section_av(files_sec):
    """音视频：_files.json 里 readable == 'av-unread' 的条数。本线不转写。"""
    out = {
        "口径": "读 _files.json 的 files 数组，统计 readable == \"av-unread\" 的条数",
        "av-unread条数": None,
        "其他readable取值": None,
        "不转写声明": "本线不转写（音视频只登记可读性，不做语音转写 / 视频转写）",
    }
    rd = files_sec.get("readable分布")
    if not isinstance(rd, list):
        out["av-unread条数"] = miss("_files.json 的 readable 分布不可用")
        out["其他readable取值"] = miss("_files.json 的 readable 分布不可用")
        return out
    av = 0
    others = []
    for k, v in rd:
        if k == "av-unread":
            av = v
        else:
            others.append("%s=%d" % (k, v))
    out["av-unread条数"] = av
    out["其他readable取值"] = "；".join(others) if others else "（无）"
    return out


# ---------------------------------------------------------------- 报告渲染

def render_markdown(date, sec_art, sec_img, sec_files, sec_qq, sec_av, gaps):
    L = []
    L.append("# %s 逐类媒体覆盖账本" % date)
    L.append("")
    L.append("> 由 `tools/media_ledger.py` 只读生成（不联网、不重新抓取、不修改任何既有产物）。")
    L.append("> 规矩：**存在才读；缺哪个必须显式写“缺，未统计”，不许静默跳过**。")
    L.append("")

    # ---- 0. 产物到位情况
    L.append("## 零、输入产物到位情况")
    L.append("")
    L.append("| 产物 | 状态 |")
    L.append("|---|---|")
    L.append("| `output\\days\\%s.jsonl` | %s |" % (date, sec_art["jsonl产物状态"]))
    L.append("| `output\\days\\%s_articles.md` | %s |" % (date, sec_art["产物状态"]))
    L.append("| `output\\days\\%s_images.json` | %s |" % (date, sec_img["产物状态"]))
    L.append("| `output\\days\\%s_vision.md` | %s |" % (date, sec_img["分诊产物状态"]))
    L.append("| `output\\days\\%s_files.json` | %s |" % (date, sec_files["产物状态"]))
    L.append("| `output\\qq\\nt_msg_export.db` | %s |" % sec_qq["产物状态"])
    L.append("")

    # ---- 1. 文章
    L.append("## 一、文章")
    L.append("")
    L.append("- 口径：%s" % sec_art["口径"])
    L.append("- 当天文章卡片条数：**%s**" % show_val(sec_art["卡片条数"]))
    L.append("- 空占位行数（`- （无）` 这类「本小节 0 条」写法，已剔除、不计为卡片）：%s"
             % show_val(sec_art["占位行数"]))
    L.append("- 有本地正文的条数：**%s**" % show_val(sec_art["有正文条数"]))
    L.append("- 缺正文的条数：**%s**" % show_val(sec_art["缺正文条数"]))
    L.append("- 缺正文占比：%s" % (sec_art["缺正文占比"] or "缺，未统计（正文标记未解析到，分母口径不成立）"))
    L.append("- 旁证（jsonl 口径）：`http` 出现次数 = %s；含 `http` 的消息条数 = %s；坏行数 = %s"
             % (sec_art["jsonl_http_出现次数"], sec_art["jsonl_含http消息条数"], sec_art["jsonl_坏行数"]))
    if sec_art["解析退化"]:
        L.append("- **解析已退化**：_articles.md 无法机器解析到正文标记，已改用 jsonl 口径并在此注明。")
    L.append("- 结论：**缺正文 ⇒ 不得据此下“已读”结论**。")
    L.append("")

    # ---- 2. 图片
    L.append("## 二、图片")
    L.append("")
    L.append("- `_images.json` 条数：**%s**" % sec_img["索引条数"])
    L.append("- 其中有非空本地路径的条数：**%s**" % sec_img["有非空本地路径条数"])
    L.append("- 无本地路径的条数：%s；`path` 字段形状异常条数：%s"
             % (sec_img["无本地路径条数"], sec_img["path字段类型异常条数"]))
    L.append("- `_vision.md` 状态：%s" % sec_img["分诊产物状态"])
    L.append("- grep 关键词与口径：%s" % sec_img["grep口径"])
    kwc = sec_img["关键词计数"]
    L.append("- grep 计数（关键词出现次数）：")
    for label in ("需回看", "判为无信息", "解析失败", "细读失败", "必须回看原图"):
        L.append("  - 「%s」（关键词 `%s`）：%s" % (label, VISION_KEYWORDS[label], kwc.get(label)))
    L.append("- 交叉校验（`## ` 小节内 `- ` 条目数，去重后）：%s" % json.dumps(sec_img["小节条目数"], ensure_ascii=False))
    L.append("- 交叉校验（`必须回看原图` 条目行数）：%s" % sec_img["必须回看原图条目数"])
    L.append("- 交叉校验（自证表原值）：%s" % json.dumps(sec_img["自证表数字"], ensure_ascii=False))
    L.append("")

    # ---- 3. 文件附件
    L.append("## 三、文件附件")
    L.append("")
    L.append("- summary：%s" % json.dumps(sec_files["summary"], ensure_ascii=False))
    L.append("- referenced = %s；found = %s；missing = %s"
             % (sec_files["referenced"], sec_files["found"], sec_files["missing"]))
    L.append("- `files` 数组条数：%s" % sec_files["files数组条数"])
    L.append("- 按 `readable` 分类计数：%s"
             % (fmt_counter(collections.Counter(dict(sec_files["readable分布"])))
                if isinstance(sec_files["readable分布"], list) else sec_files["readable分布"]))
    L.append("- 按 `read_status` 分类计数：%s"
             % (fmt_counter(collections.Counter(dict(sec_files["read_status分布"])))
                if isinstance(sec_files["read_status分布"], list) else sec_files["read_status分布"]))
    if isinstance(sec_files["readable与read_status交叉"], list):
        L.append("- readable / read_status 交叉计数：%s"
                 % fmt_counter(collections.Counter(dict(sec_files["readable与read_status交叉"]))))
    else:
        L.append("- readable / read_status 交叉计数：%s" % sec_files["readable与read_status交叉"])
    L.append("- 结论：**missing 是“本机没有”，不是“没查”**。")
    L.append("")

    # ---- 4. QQ 媒体
    L.append("## 四、QQ 媒体")
    L.append("")
    L.append("- 口径：%s" % sec_qq["口径"])
    for t in QQ_TABLES:
        e = sec_qq["表"].get(t, {})
        L.append("- `%s`：状态 %s；总条数 %s" % (t, e.get("状态"), show_val(e.get("总条数"))))
        dist = e.get("content_type分布")
        if isinstance(dist, list):
            L.append("  - `content_type` 分布（整库）：%s" % fmt_counter(collections.Counter(dict(dist))))
        else:
            L.append("  - `content_type` 分布（整库）：%s" % dist)
        # A13「实际定位」：当天那一份（2026-09-22 起按天切，之前只有整库口径）
        L.append("  - **当天条数：%s**" % show_val(e.get("当天条数")))
        ddist = e.get("当天content_type分布")
        if isinstance(ddist, list):
            L.append("  - `content_type` 分布（当天）：%s" % fmt_counter(collections.Counter(dict(ddist))))
        else:
            L.append("  - `content_type` 分布（当天）：%s" % ddist)
    L.append("- 结论：**%s**（当天切片给的是「这一天 QQ 有多少条各类媒体」，"
             "接线仍与微信不同 —— 微信有逐条索引与本地视觉，QQ 没有）。" % sec_qq["接线事实"])
    L.append("")

    # ---- 5. 音视频
    L.append("## 五、音视频")
    L.append("")
    L.append("- 口径：%s" % sec_av["口径"])
    L.append("- `readable == \"av-unread\"` 条数：**%s**" % show_val(sec_av["av-unread条数"]))
    L.append("- 其他 readable 取值：%s" % sec_av["其他readable取值"])
    L.append("- 结论：**本线不转写**。")
    L.append("")

    # ---- 未统计到的类
    L.append("## 六、未统计到的类（显式声明）")
    L.append("")
    if gaps:
        for g in gaps:
            L.append("- %s —— 原因：%s" % (g["类"], g["原因"]))
    else:
        L.append("- （无：本次所有目标类都有产物且都统计到了）")
    L.append("")

    # ---- 覆盖结论
    L.append("## 七、本轮覆盖结论")
    L.append("")
    L.append("- 做到了逐条状态的类：%s" % CONCLUSION["per_item"])
    L.append("- 只有总数的类：%s" % CONCLUSION["total_only"])
    L.append("- 完全没接线的类：%s" % CONCLUSION["unwired"])
    L.append("")
    return "\n".join(L)


# 结论文本（在 main 里按实际统计结果填充）
CONCLUSION = {"per_item": "", "total_only": "", "unwired": ""}


def build_conclusion(date, sec_art, sec_img, sec_files, sec_qq, sec_av):
    per_item, total_only, unwired = [], [], []

    # 文章：逐条状态取决于 md 是否解析成功
    if sec_art["有正文条数"] is not None and sec_art["缺正文条数"] is not None:
        per_item.append("文章（逐条：有正文 %s 条 / 缺正文 %s 条，缺正文者明确不可下已读结论）"
                        % (sec_art["有正文条数"], sec_art["缺正文条数"]))
    else:
        total_only.append("文章（只有总数：卡片 %s 条，正文到位与否未能逐条判定）" % show_val(sec_art["卡片条数"]))

    # 图片：逐条路径 + 三类 grep 计数
    if isinstance(sec_img["有非空本地路径条数"], int):
        per_item.append("图片（逐条：索引 %s 条，其中非空本地路径 %s 条，无路径 %s 条）"
                        % (sec_img["索引条数"], sec_img["有非空本地路径条数"], sec_img["无本地路径条数"]))
    else:
        total_only.append("图片（只有总数或未统计：%s）" % sec_img["索引条数"])

    # 文件附件：逐条 readable / read_status
    if isinstance(sec_files["readable分布"], list):
        per_item.append("文件附件（逐条：%d 条各自带 readable / read_status，missing=%s）"
                        % (sec_files["files数组条数"], sec_files["missing"]))
    else:
        total_only.append("文件附件（只有 summary 总数：%s）" % json.dumps(sec_files["summary"], ensure_ascii=False))

    # QQ：整库 content_type 分布（逐行有 content_type，但不是当天切片）
    qq_ok = any(isinstance(sec_qq["表"].get(t, {}).get("content_type分布"), list) for t in QQ_TABLES)
    if qq_ok:
        total_only.append("QQ 媒体（有整库与**当天**的 content_type 分布，但**没有**与微信同等的逐条日索引接线）")
    else:
        unwired.append("QQ 媒体（未统计：%s）" % sec_qq["产物状态"])

    # 音视频
    if isinstance(sec_av["av-unread条数"], int):
        total_only.append("音视频（只有总数 %d 条，且本线不转写，没有逐条转写状态）" % sec_av["av-unread条数"])
    else:
        unwired.append("音视频（未统计：%s）" % sec_av["av-unread条数"])

    # 微信侧的图片/语音/视频原始消息（jsonl 里的 type=图片/语音/视频）没有逐条索引接线
    unwired.append("微信侧音视频原始消息的逐条接线（本工具未统计：无对应日索引产物；"
                   "jsonl 只有消息行，图片走 _images.json、音视频只在 _files.json 里以 av-unread 出现）")

    CONCLUSION["per_item"] = "；".join(per_item) if per_item else "（无）"
    CONCLUSION["total_only"] = "；".join(total_only) if total_only else "（无）"
    CONCLUSION["unwired"] = "；".join(unwired) if unwired else "（无）"
    return CONCLUSION


def collect_gaps(date, sec_art, sec_img, sec_files, sec_qq, sec_av):
    """汇总「没能统计到的类 + 原因」。"""
    gaps = []
    if sec_art["卡片条数"] is None:
        gaps.append({"类": "文章", "原因": sec_art["口径"]})
    elif sec_art["解析退化"]:
        gaps.append({"类": "文章（正文到位与否）", "原因": sec_art["口径"]})
    if not isinstance(sec_img["索引条数"], int):
        gaps.append({"类": "图片索引", "原因": str(sec_img["索引条数"])})
    if sec_img["分诊产物状态"] != "存在，已读":
        gaps.append({"类": "图片分诊（_vision.md 三类计数）", "原因": str(sec_img["分诊产物状态"])})
    if not isinstance(sec_files["readable分布"], list):
        gaps.append({"类": "文件附件（readable / read_status 分布）", "原因": str(sec_files["readable分布"])})
    for t in QQ_TABLES:
        e = sec_qq["表"].get(t, {})
        if e.get("状态") != "已统计":
            gaps.append({"类": "QQ 表 %s" % t, "原因": str(e.get("状态"))})
    if not isinstance(sec_av["av-unread条数"], int):
        gaps.append({"类": "音视频（av-unread）", "原因": str(sec_av["av-unread条数"])})
    return gaps


# ---------------------------------------------------------------- main

def main(argv=None):
    _setup_stdout()
    ap = argparse.ArgumentParser(
        description="逐类媒体覆盖账本（只读已有产物，不联网，不修改既有文件）"
    )
    ap.add_argument("date", help="日期，形如 2026-09-17")
    ap.add_argument("--json", action="store_true", help="同时写 output\\days\\<date>_coverage.json")
    args = ap.parse_args(argv)

    date = args.date
    # 脚本位于 <root>\tools\，output 在 <root>\output\
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    day_dir = os.path.join(root, "output", "days")
    qq_db = os.path.join(root, "output", "qq", "nt_msg_export.db")

    sec_art = section_articles(date, day_dir)
    sec_img = section_images(date, day_dir)
    sec_files = section_files(date, day_dir)
    sec_qq = section_qq(date, qq_db)
    sec_av = section_av(sec_files)
    conclusion = build_conclusion(date, sec_art, sec_img, sec_files, sec_qq, sec_av)
    gaps = collect_gaps(date, sec_art, sec_img, sec_files, sec_qq, sec_av)

    md = render_markdown(date, sec_art, sec_img, sec_files, sec_qq, sec_av, gaps)

    # 写产物
    os.makedirs(day_dir, exist_ok=True)
    md_path = os.path.join(day_dir, "%s_coverage.md" % date)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)

    json_path = None
    if args.json:
        payload = {
            "date": date,
            "generated_by": "tools/media_ledger.py",
            "articles": sec_art,
            "images": sec_img,
            "files": sec_files,
            "qq": sec_qq,
            "av": sec_av,
            "uncovered": gaps,
            "conclusion": conclusion,
        }
        json_path = os.path.join(day_dir, "%s_coverage.json" % date)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)

    sys.stdout.write(md)
    sys.stdout.write("\n---\n")
    sys.stdout.write("已写入：%s\n" % md_path)
    if json_path:
        sys.stdout.write("已写入：%s\n" % json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
