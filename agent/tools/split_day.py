# -*- coding: utf-8 -*-
"""split_day.py — 把一天切成 N 个**分片**，供多个子代理"分片全覆盖、逐条读"。

为什么需要它（2026-09-13 用户追问"不逐条读会不会漏信息"）：
关键字粗筛**必然漏**（没有关键词的纠正/警告/事实变更、措辞意外的干货、要靠多句才看出的共识）。
正确做法是**分片 + 每片逐条读完**：范围小到能塞进一个上下文，但覆盖是完整的。

切法（保留上下文，不打散会话）：
  · 每个会话一行，**大群按时间再切成多片**；片内按时间排序，带群名与发言人。
  · 每片目标 ~350 行（可用第二个参数改）。

用法:  python tools\\split_day.py [YYYY-MM-DD] [片数]
产出:  output/days/<date>_slices.md         ← 索引（哪片、哪些群、多少行）——派活时照它分
       output/days/<date>_sliceNN_<群摘要>.md ← 每片正文（子代理读这个）
"""
import datetime as dt
import io
import json
import os
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = dt.timezone(dt.timedelta(hours=8))

DROP = [re.compile(r"^<(\?xml|msg|sysmsg|appmsg)"), re.compile(r"^eyJwaGFzaCI"),
        re.compile(r"拍了拍"), re.compile(r"撤回了一条消息"), re.compile(r"请注意隐私安全"),
        re.compile(r"与群里其他人"), re.compile(r"^\s*\[[^\]]{0,20}\]\s*$"), re.compile(r"^\s*[\W_]{0,8}\s*$")]
# 行首方括号串（`[问] [群名] 发言人: …`）—— 群名取其中**最后一个**
LEAD_BRACKETS = re.compile(r"^(?:\d\d:\d\d\s+)?((?:\[[^\]]*\]\s*)*)")


def group_of(body):
    """取单元行的**群名**（行首方括号串里的最后一个）。

    2026-09-15 修 bug：`load_units_corpus` 原来把**所有**方括号内容都当"已筛群名"，
    于是 `[问]`/`[答]`/`[卡片]` 这些标记也算群名 → **含这些标记的其他群的行被误排除**出语料
    （实测 09-14：分片少了 59 行，全是带 `[问]/[答]` 的行，含崔老师群那条）。
    自检工具：`python tools\\check_corpus_coverage.py <date>`。
    """
    m = LEAD_BRACKETS.match(body)
    if not m:
        return ""
    tags = re.findall(r"\[([^\]]+)\]", m.group(1))
    return tags[-1] if tags else ""
XML_MEDIA = re.compile(r"<(\?xml|msg|appmsg|sysmsg|emoji)")
# QQ 的原始媒体消息（单引号/双引号 dict 形式的 msg_body）+ 图片占位文本 + 表情名
RAW_JSON = re.compile(r"^[\{\[]\s*['\"]type['\"]\s*:\s*['\"]msg_body")
IMG_PH = re.compile(r"^\[图片:[0-9A-Fa-f]{6,}\.[A-Za-z]{3,4}\]$")
STICKER = re.compile(r"['\"]video_text['\"]\s*:\s*['\"]([^'\"]{0,12})['\"]")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
WXID_PREFIX = re.compile(r"^(wxid_[A-Za-z0-9]+|qq_[0-9]+|\d{5,}):\s*")

# 长消息**不许静默截断**（2026-09-15 事故，用户问「这个招募问卷不应该是重要信息吗」）：
#   一条 525 字的公告（AI 大赛入围名单 + 报销 + 反馈问卷 + **招募问卷**）在**三个层**被砍过：
#     split_day.load `t[:300]` → units_day 输出 `[:260]` → split_day 写分片 `[:240]`
#   而子代理读的正是**分片**、台账扫描读的也是它 → 尾部（**动作与链接通常就在这里**）整段丢失。
#   现在的规则：**头 CLIP_HEAD + 尾 CLIP_TAIL，中间显式标出省略了多少字**，并在产出里计数。
CLIP_HEAD, CLIP_TAIL = 400, 400


def clip(t):
    """返回 (视图文本, 省略字数)；不超过 HEAD+TAIL 时原样返回（不截断）。"""
    n = len(t)
    if n <= CLIP_HEAD + CLIP_TAIL:
        return t, 0
    head, tail = t[:CLIP_HEAD], t[-CLIP_TAIL:]
    omitted = n - len(head) - len(tail)
    return head + (" ……[省略 %d 字]…… " % omitted) + tail, omitted


def clean(t):
    t = re.sub(r"\s+", " ", (t or "")).strip()
    return WXID_PREFIX.sub("", t)


def load(date, min_len=4):
    """读当天语料。`min_len`＝正文长度下界（默认 4，**所有既有调用者行为不变**）。

    2026-09-18 新增这个参数：`vision_triage` 的「回语境」需要**短消息**。
    起因（实测）：09-17 那条"产业生态学"误报的截图，配文是两句 —— 「坏了」（**2 字**）＋
    「你给我留了多少算力呢」（14 字）。2 字那句被这里的 `len(t) < 4` **静默滤掉**，
    于是"图是开玩笑发的"这个信号少了一半（正是 A46「静默截断＝漏报」那一类）。
    ⇒ 语境线显式传 `min_len=2`；**读语料的视图仍用默认 4**（别顺手改默认值 —— 那会动到覆盖率自检）。
    """
    p = os.path.join(HERE, "output", "days", "%s.jsonl" % date)
    if not os.path.exists(p):
        return None
    rows = []
    for line in io.open(p, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        j = json.loads(line)
        t = clean(j.get("text")) or clean(j.get("raw"))
        if not t:
            continue
        m = TITLE_RE.search(t)
        if XML_MEDIA.search(t):
            if m:
                t = "[卡片] " + re.sub(r"&amp;", "&", m.group(1).strip())[:120]
            else:
                continue
        # 2026-09-13 实测（用户："进一步缩减水群无用消息数量"）：
        #   QQ 的**原始 JSON 媒体消息**漏进来了 —— `{'type': 'msg_body', 'segments': […]}` 单引号 dict，
        #   只挡 `<xml>` 是挡不住的。实测 09-13 大群：QQ5/8 200 条(均 290 字) + QQ2/6 160 条(均 182 字)
        #   共 **~87,000 字符纯 JSON**；另有 QQ2/2 595 条 `[图片:<hash>.jpg]`（~20,000 字符无用 hash）。
        #   这两类占该群 76% 的字符，去掉**零信息损失**（保留"这里有个图/表情"的标记）。
        if IMG_PH.match(t):
            t = "【图片】"
        elif RAW_JSON.match(t):
            mm = STICKER.search(t)
            t = ("【表情/动图：%s】" % mm.group(1)) if mm else "【富媒体】"
        if any(x.search(t) for x in DROP) or len(t) < min_len:
            continue
        rows.append({"ts": int(j.get("ts") or 0),
                     "chat": (j.get("chat_name") or j.get("chat") or "?").strip(),
                     "who": (j.get("sender_name") or j.get("sender") or "").strip(),
                     # **不在加载层截断**（2026-09-15 修）：原来这里是 `t[:300]`，
                     #   而 `units_day` 用的就是这个 loader → 截断发生在**任何视图之前**，
                     #   于是"把 units 的输出上限调大"根本无效（实测重切后仍找不到那条公告的尾巴）。
                     #   语料在内存里保持**完整**，要不要省略由各个**视图**自己决定（见 clip()）。
                     "text": t})
    rows.sort(key=lambda r: r["ts"])
    return rows


def load_units_corpus(date):
    """「分片全覆盖」要读的语料（2026-09-14 新增）。

    为什么不是直接用 `<date>.jsonl`：机械降噪（`units_day.py`）已把当天折成"话语单元"，
    本地小模型（`llm_filter.py`）又对大群做了一层"留/丢"（被丢的全文留在 `<date>_units_dropped.md`，可回查+抽检漏率）。
    ⇒ 需要逐条读完的语料＝**过滤后留下的单元（被筛过的那个群）+ 其余会话的全部单元**（其余群没筛，一条不少）。
    判据用"群名"而不是写死某个群：`_units_filtered.md` 里出现过哪些群名，就认为那些群已被筛过。
    """
    d = os.path.join(HERE, "output", "days")
    fp = os.path.join(d, "%s_units_filtered.md" % date)
    up = os.path.join(d, "%s_units.md" % date)
    kept, covered = [], set()
    if os.path.exists(fp):
        for ln in io.open(fp, encoding="utf-8", errors="replace"):
            ln = ln.rstrip("\n")
            if not ln.startswith("- "):
                continue
            kept.append(ln[2:])
            g = group_of(ln[2:])
            if g:
                covered.add(g)
    rest = []
    for ln in io.open(up, encoding="utf-8", errors="replace"):
        ln = ln.rstrip("\n")
        if not ln.startswith("- "):
            continue
        body = ln[2:]
        if covered and group_of(body) in covered:
            continue
        rest.append(body)
    return kept, rest


def main():
    args = [a for a in sys.argv[1:] if a]
    units_mode = "--units" in args
    args = [a for a in args if a != "--units"]
    date = args[0] if args else dt.datetime.now(TZ).strftime("%Y-%m-%d")
    target = int(args[1]) if len(args) > 1 else 350

    if units_mode:
        kept, rest = load_units_corpus(date)
        lines = kept + rest
        if not lines:
            print("没有单元语料（先跑 units_day.py / llm_filter.py）")
            return 1
        lines.sort(key=lambda s: s[:5])          # 行首 HH:MM → 时间序
        slices = [lines[i:i + target] for i in range(0, len(lines), target)]
        outdir = os.path.join(HERE, "output", "days")
        idx = ["# %s 分片索引 · 话语单元语料（%d 行 → %d 片，每片 ~%d 行）" % (date, len(lines), len(slices), target), "",
               "> 语料＝小模型过筛后保留的大群单元（%d 条）+ 其余会话全部单元（%d 条）。" % (len(kept), len(rest)),
               "> **每片派一个子代理逐条读完**；被小模型丢掉的原文在 `%s_units_dropped.md`（可回查、抽检）。" % date,
               "> 子代理回报固定三样：① 留了什么 ② 这段的共性（被反复问到的同类问题）③ 明确说「这段没有可留的」。", ""]
        for i, sl in enumerate(slices, 1):
            fn = "%s_slice%02d_units.md" % (date, i)
            lo, hi = sl[0][:5], sl[-1][:5]
            with io.open(os.path.join(outdir, fn), "w", encoding="utf-8", newline="\n") as f:
                f.write("# %s 第 %d/%d 片（%d 行 ｜ %s ~ %s）\n\n" % (date, i, len(slices), len(sl), lo, hi))
                for ln in sl:
                    f.write("- " + ln + "\n")
            idx.append("- 第 %02d 片：**%d 行** ｜ %s ~ %s ｜ `output/days/%s`" % (i, len(sl), lo, hi, fn))
        with io.open(os.path.join(outdir, "%s_slices.md" % date), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(idx) + "\n")
        print("%s ｜ 单元语料 %d 行（筛后大群 %d + 其余 %d）→ %d 片 ｜ 索引 output/days/%s_slices.md"
              % (date, len(lines), len(kept), len(rest), len(slices), date))
        # 覆盖自证（2026-09-15）：源里每个群都必须在语料里出现，否则"分片全覆盖"名不副实
        up = os.path.join(outdir, "%s_units.md" % date)
        src_groups = set()
        if os.path.exists(up):
            for ln in io.open(up, encoding="utf-8", errors="replace"):
                if ln.startswith("- "):
                    src_groups.add(group_of(ln[2:]))
        corp_groups = set(group_of(b) for b in lines)
        miss = src_groups - corp_groups
        print("语料覆盖：源群 %d ｜ 语料群 %d%s" % (
            len(src_groups), len(corp_groups),
            ("  ｜ **缺群 %d**：%s —— 立刻查 tools\\check_corpus_coverage.py" % (len(miss), ", ".join(sorted(miss)[:4]))) if miss else "  ｜ 无缺群"))
        return 0

    rows = load(date)
    if rows is None:
        print("缺 output/days/%s.jsonl" % date)
        return 1

    by = defaultdict(list)
    for r in rows:
        by[r["chat"]].append(r)
    # 大群按时间拆成若干段，其余整群一片
    units = []
    for chat, rs in by.items():
        n = len(rs)
        if n <= target:
            units.append((chat, rs))
        else:
            parts = (n + target - 1) // target
            size = (n + parts - 1) // parts
            for i in range(0, n, size):
                units.append(("%s(第%d段)" % (chat, i // size + 1), rs[i:i + size]))
    units.sort(key=lambda u: -len(u[1]))

    # 装箱：贪心塞进 N 片（每片 <= target*1.3）
    cap = int(target * 1.3)
    slices = []
    for chat, rs in units:
        placed = False
        for s in slices:
            if s["n"] + len(rs) <= cap:
                s["chats"].append(chat); s["rows"].extend(rs); s["n"] += len(rs); placed = True
                break
        if not placed:
            slices.append({"chats": [chat], "rows": list(rs), "n": len(rs)})

    outdir = os.path.join(HERE, "output", "days")
    idx = ["# %s 分片索引（%d 行 → %d 片，每片 ~%d 行）" % (date, len(rows), len(slices), target), "",
           "> **每片派一个子代理逐条读完**（不是关键字筛）——片小到能进一个上下文，但覆盖是完整的。",
           "> 子代理回报：留了什么 + 这个群/这段有没有共性问题。", ""]
    for i, s in enumerate(slices, 1):
        s["rows"].sort(key=lambda r: r["ts"])
        names = "、".join(c[:14] for c in s["chats"][:3]) + ("…" if len(s["chats"]) > 3 else "")
        fn = "%s_slice%02d_%s.md" % (date, i, re.sub(r"\W+", "", s["chats"][0])[:10] or "part")
        with io.open(os.path.join(outdir, fn), "w", encoding="utf-8", newline="\n") as f:
            f.write("# %s 第 %d/%d 片（%d 行；%s）\n\n" % (date, i, len(slices), s["n"], names))
            n_clip = 0
            for r in s["rows"]:
                hm = dt.datetime.fromtimestamp(r["ts"], TZ).strftime("%H:%M")
                txt, elided = clip(r["text"])
                if elided:
                    n_clip += 1
                f.write("- %s [%s] %s: %s\n" % (hm, r["chat"][:18], r["who"][:12], txt))
            if n_clip:
                f.write("\n> 本片有 **%d 条**长消息只保留「头 %d + 尾 %d」、中间显式标了省略字数"
                        "（公告类的动作与链接通常在末尾）。\n" % (n_clip, CLIP_HEAD, CLIP_TAIL))
        idx.append("- 第 %02d 片：**%d 行** ｜ %s ｜ `output/days/%s`" % (i, s["n"], names, fn))
    with io.open(os.path.join(outdir, "%s_slices.md" % date), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(idx) + "\n")
    print("%s ｜ %d 行 → %d 片（每片均 ~%d 行）｜ 索引 output/days/%s_slices.md"
          % (date, len(rows), len(slices), len(rows) // max(1, len(slices)), date))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
