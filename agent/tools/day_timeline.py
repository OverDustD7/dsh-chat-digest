# -*- coding: utf-8 -*-
"""day_timeline.py — 把一天**所有会话按时间合并**成一条时间轴（提炼用的"全集视图"）。

为什么需要它（2026-09-13 用户指出"跨会话建立时间轴和联系的能力太弱"）：
`days/<date>_brief.md` 是**按会话分组**的 → 同一件事的碎片落在不同章节、隔着几十行，
读的人看不见「01:28 舞培/正装团购 → 10:09 尤勇问舞会 → 11:05 尺码统计催办」是一条线。
本脚本产出**按时间排序**的单一时间轴，并把**跨群重复出现的话题词**标出来 → 联系一眼可见。

用法: python tools\\day_timeline.py [YYYY-MM-DD ...]
产出: output/days/<date>_timeline.md
"""
import datetime as dt
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = dt.timezone(dt.timedelta(hours=8))

DROP = [re.compile(r"^<(\?xml|msg|sysmsg|appmsg)"), re.compile(r"^eyJwaGFzaCI"),
        re.compile(r"拍了拍"), re.compile(r"撤回了一条消息"),
        re.compile(r"请注意隐私安全"), re.compile(r"与群里其他人"),
        re.compile(r"^\s*\[[^\]]{0,20}\]\s*$"), re.compile(r"^\s*[\W_]{0,8}\s*$")]
XML_MEDIA = re.compile(r"<(\?xml|msg|appmsg|sysmsg|emoji)")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
WXID_PREFIX = re.compile(r"^(wxid_[A-Za-z0-9]+|qq_[0-9]+|\d{5,}):\s*")
CJK_RUN = re.compile(r"[\u4e00-\u9fa5]+")
# 中文功能字：含这些字的 2 字片段几乎都是切分碎片（"体的/就这/妈的/是要"），不是话题词
FUNC = set("的了是在不我你他她它这那就都也很要会能有和与及或但而被把让给对从到向以为所之其此该着过们个上下里外中呢吧吗啊呀嘛哦还只真没想问说看做好多太小大")


# 2026-09-14：媒体消息的**原始 JSON / 图片 hash 占位**转短标记（与 split_day.py 同口径）。
# 实测 09-13 大群 76% 的字符是 `{'type':'msg_body'…}` 与 `[图片:<hash>.jpg]` —— 纯垃圾，转标记零信息损失。
_RAW_JSON = re.compile(r"^[\{\[]\s*['\"]type['\"]\s*:\s*['\"]msg_body")
_IMG_PH = re.compile(r"^\[图片:[0-9A-Fa-f]{6,}\.[A-Za-z]{3,4}\]$")
_STICKER = re.compile(r"['\"]video_text['\"]\s*:\s*['\"]([^'\"]{0,12})['\"]")


def _demedia(t):
    if _IMG_PH.match(t):
        return "【图片】"
    if _RAW_JSON.match(t):
        m = _STICKER.search(t)
        return ("【表情/动图：%s】" % m.group(1)) if m else "【富媒体】"
    return t


def ngrams(text, lo=2, hi=6):
    """中文没有空格，不能只抓"最长汉字串"——那样嵌在句子中间的词（如"我是说正式的**舞会**"）永远抓不到。
    改成在每段汉字上做 2–6 字滑窗，再用"功能字过滤 + 跨群 + 罕见"三层筛掉碎片。"""
    out = set()
    for run in CJK_RUN.findall(text):
        for n in range(lo, min(hi, len(run)) + 1):
            for i in range(len(run) - n + 1):
                out.add(run[i:i + n])
    return out


def wordish(w):
    if w in STOP or len(w) > 12:
        return False
    if len(w) >= 3:
        return True
    return not (set(w) & FUNC)          # 2 字词：不含功能字才算候选
# 跨群话题词里要排除的"人人都在说"的词
STOP = {"我们", "你们", "他们", "老师", "同学", "什么", "这个", "那个", "可以", "不是", "就是",
        "还是", "有没有", "请问", "大家好", "谢谢", "没有", "不知道", "感觉", "应该", "真的",
        "怎么", "为什么", "现在", "今天", "明天", "昨天", "一下", "一个", "有点", "然后",
        "直接", "已经", "还有", "这个", "时候", "地方", "问题", "东西", "怎么办",
        "所有人", "应该是", "时间为", "星期四", "各位同学好", "请注意隐私安全",
        "与群里其他人都不是朋友关系", "清华大学专场宣讲", "班团活动资源",
        "卡片", "确实", "好的", "推荐", "干嘛", "捂脸", "没事", "是吗", "哈哈", "谢谢", "可以"}


def clean(t):
    t = re.sub(r"\s+", " ", (t or "")).strip()
    t = _demedia(t)
    t = WXID_PREFIX.sub("", t)
    return t


def main(dates):
    # 群名解析：`session_meta.json` 能给"没名字的 chatroom"补显示名；补不上就用成员兜底
    #   （起因：`50062725365@chatroom` 在产物里 name 就是它自己的 id → 113 条 / 23.5K 字成了一块无名数据）
    meta = {}
    mp = os.path.join(HERE, "output", "window", "session_meta.json")
    if os.path.exists(mp):
        try:
            meta = json.load(io.open(mp, encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            meta = {}

    def is_idname(n):
        return n == "?" or bool(re.match(r"^[\w\-]+@chatroom$", n or ""))

    for DATE in dates:
        src = os.path.join(HERE, "output", "days", "%s.jsonl" % DATE)
        if not os.path.exists(src):
            print("缺 %s" % src)
            continue
        rows, dropped = [], 0
        for line in io.open(src, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            j = json.loads(line)
            t = clean(j.get("text")) or clean(j.get("raw"))
            if not t:
                continue
            m = TITLE_RE.search(t)
            if XML_MEDIA.search(t):
                if m:                                  # 卡片：只留标题，这是唯一有信息的部分
                    title = re.sub(r"&amp;", "&", m.group(1).strip())[:120]
                    t = "[卡片] " + title
                else:
                    dropped += 1
                    continue
            if any(p.search(t) for p in DROP) or len(t) < 5:
                dropped += 1
                continue
            rows.append({"ts": int(j.get("ts") or 0),
                         "chat": (j.get("chat_name") or j.get("chat") or "?").strip(),
                         "who": (j.get("sender_name") or j.get("sender") or "").strip(),
                         "text": t[:300], "n": 1})
        rows.sort(key=lambda r: r["ts"])

        # 无名群的成员兜底：谁在这个群说话最多
        spk = defaultdict(Counter)
        for r in rows:
            if is_idname(r["chat"]) and r["who"]:
                spk[r["chat"]][r["who"]] += 1

        def disp(chat):
            if not is_idname(chat):
                return chat
            nm = ((meta.get(chat) or {}) or {}).get("name") or ""
            if nm and nm != chat and not is_idname(nm):
                return nm
            top = "、".join(w for w, _ in spk[chat].most_common(3) if w)
            return "%s(群成员:%s)" % (chat.split("@")[0], top) if top else chat

        # 同一会话 + 同一句话在 60 分钟内重复 → 合并（水群刷屏）
        merged = []
        for r in rows:
            if merged:
                p = merged[-1]
                if p["chat"] == r["chat"] and p["text"] == r["text"] and r["ts"] - p["ts"] <= 3600:
                    p["n"] += 1
                    continue
            merged.append(r)
        rows = merged

        # ---- 跨群"线索"索引：只收**可精确判定**的两种，猜的不收 ----
        # A) 同一段文字出现在 >=2 个会话 = 同一份通知被多群转发（同一件事）
        # B) 同一个链接/域名出现在 >=2 个会话 = 同一件事被不同群提到
        def dupkey(t):
            return re.sub(r"[\s\W_]+", "", t)[:40]

        groups = defaultdict(set)
        for r in rows:
            k = dupkey(r["text"])
            if len(k) >= 12:
                groups[k].add(r["chat"])
        cross = {k for k, cs in groups.items() if len(cs) >= 2}
        # 纯语气词/闲聊句（"哈哈哈"）不算
        cross = {k for k in cross if len(k) >= 12}

        doms = defaultdict(set)
        for r in rows:
            for d in set(re.findall(r"https?://([^/\s\"]+)", r["text"])):
                doms[d].add(r["chat"])
        crossdom = {d for d, cs in doms.items() if len(cs) >= 2}

        index = []
        for r in rows:
            k = dupkey(r["text"])
            if k in cross:
                index.append(("同文转发", k, r))
        links = []
        for r in rows:
            for d in set(re.findall(r"https?://([^/\s\"]+)", r["text"])):
                if d in crossdom:
                    links.append((d, r))

        out = os.path.join(HERE, "output", "days", "%s_timeline.md" % DATE)
        with io.open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write("# %s 跨会话时间轴（全会话按时间合并、去噪、同句合并）\n\n" % DATE)
            f.write("> 行式 `★HH:MM [群] 人: 内容`；**★＝该行属于「同一段文字被多个群转发」**（多半是同一条待办 → 优先看）\n")
            f.write("> `(×N)`＝同一会话 1 小时内同一句话出现 N 次（水群刷屏已合并）\n")
            f.write("> 保留 %d 行（丢弃 %d 行）｜`tools\\day_timeline.py` 生成\n\n" % (len(rows), dropped))
            f.write("## 跨群线索索引（**先看这里**；只收能精确判定的两类，不猜）\n\n")
            f.write("### A. 同一段文字出现在多个会话（＝同一份通知被多群转发，多半是同一条待办）\n\n")
            if not index:
                f.write("- （无）\n")
            for _, k, r in sorted(index, key=lambda x: x[2]["ts"]):
                d = dt.datetime.fromtimestamp(r["ts"], TZ).strftime("%H:%M")
                f.write("- **%s [%s] %s**：%s\n" % (d, disp(r["chat"])[:16], r["who"][:10], r["text"][:150]))
            if links:
                f.write("\n### B. 同一个链接/域名出现在多个会话\n\n")
                for d, r in sorted(links, key=lambda x: x[1]["ts"]):
                    fs = dt.datetime.fromtimestamp(r["ts"], TZ).strftime("%H:%M")
                    f.write("- **%s**：%s [%s] %s\n" % (d, fs, disp(r["chat"])[:16], r["text"][:110]))
            f.write("\n---\n")
            cur = None
            for r in rows:
                d = dt.datetime.fromtimestamp(r["ts"], TZ)
                hh = d.strftime("%m-%d %H")
                if hh != cur:
                    cur = hh
                    f.write("\n## %s 时\n" % d.strftime("%m-%d %H"))
                mark = "★" if dupkey(r["text"]) in cross else " "
                rep = " (×%d)" % r["n"] if r["n"] > 1 else ""
                f.write("- %s%s [%s] %s: %s%s\n" % (mark, d.strftime("%H:%M"), disp(r["chat"])[:18],
                                                    r["who"][:12], r["text"][:220], rep))
        print("%s ｜ 保留 %d 行（丢弃 %d）｜ 跨群同文 %d 组 / 跨群链接 %d 个" %
              (DATE, len(rows), dropped, len({k for _, k, _ in index}), len(crossdom)))


if __name__ == "__main__":
    main(sys.argv[1:] or [dt.datetime.now(TZ).strftime("%Y-%m-%d")])
