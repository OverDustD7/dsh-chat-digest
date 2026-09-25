# -*- coding: utf-8 -*-
"""dig_urls.py — 提取**某一天**的全部链接 + 上下文（KNOWN_ISSUES #30 的修复版）。

用法:
    python dig_urls.py                # 默认"今天"
    python dig_urls.py 2026-09-12     # 指定日期

数据源 = **当天全量产物** `output/days/<date>.jsonl`（由 step 3 `extract_day.py` 生成，
含 `src`(WX/QQ)/`chat`/`chat_name`/`ts`/`sender_name`/`type`/`text`/`raw`）。

历史坑（#6 / #30）：旧版读 `output/window/wx_raw.jsonl` —— 那是**跨天窗口快照**，
没有 `src` 字段、且当天部分只覆盖到下午（09-12 实测：当天唯一 URL 48 条，
而当天实际 159 条，漏 111 条）。现在只认当天产物，来源不符直接退出。

产出（路径保持原样，下游 verify_links.mjs / 账号筛选脚本 / tidy.py 无需改）:
    output/window/all_urls.jsonl     每次出现一行（src/group/ts/who/url/ctx）
    output/window/all_urls.txt       人类可读（资源型 + 其余）
    output/window/all_urls_meta.json **覆盖自检元数据**（daily_prep 用；见 #30）
"""
# ── 个人信息一律来自 pconf（<localDir>/pipeline.yaml）────────────────────────
# 这个文件里**不许写死任何路径 / 群名 / 账号**；缺键时 pconf 会打印缺哪个键、
# 去哪个文件填，并以退出码 2 结束。
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from pconf import C  # noqa: E402

WX_ACCOUNT_DIR = C.get("wx_account_dir")
WX_MSG_GLOB = C.get("wx_msg_glob")
WX_KEY_DIR = C.get("wx_key_dir")
QQ_DATA_DIR = C.get("qq_data_dir")
WORK_DIR = C.get("work_dir")
SELF_WXID = C.get("self_wxid")
MAIN_GROUP = C.get("main_group")

OUT_DIR = C.get("output_dir")
GROUPS = C.groups
# ────────────────────────────────────────────────────────────────────────────
import datetime as dt
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = dt.timezone(dt.timedelta(hours=8))

WIN = os.path.join(HERE, "output", "window")
OUT = os.path.join(WIN, "all_urls.txt")
OUTJ = os.path.join(WIN, "all_urls.jsonl")
OUTM = os.path.join(WIN, "all_urls_meta.json")

URL_RE = re.compile(r"https?://[^\s\"'<>\\）)】]+")
# QQ 的 `raw` 是**未解码的 JSON 文本**：URL 写成 `http:\/\/a.com\/x\u0026y=1`，
# 不先反转义就会被 `\` 截断（实测 09-12 有 22 条前缀残片，如 `http://wxapp.tc.`）。
_UNI = re.compile(r"\\u([0-9a-fA-F]{4})")


def unescape_blob(s):
    """把 JSON 转义还原成可正则的明文（\\uXXXX / \\/ / \\" 等）。"""
    if not s or "\\" not in s:
        return s or ""
    s = _UNI.sub(lambda m: chr(int(m.group(1), 16)), s)
    s = (s.replace("\\/", "/").replace('\\"', '"').replace("\\'", "'")
          .replace("\\r", " ").replace("\\n", " ").replace("\\t", " "))
    return s.replace("\\\\", "\\")


# 当天产物里被硬截断的字段长度（`text` 层：WX 走 wx_text_summary 截 800 / QQ 收在 2000）。
# 链接正好落在字段末尾 = 被砍掉后半截，是残片（如 `http://mmbiz.qpi`），必须丢弃。
# **2026-09-20 A12 后 6000 已移除**：extract_day 的 `raw` 不再截断，raw 里不存在"字段末尾"
# 这种假象，留着 6000 反而会把一条恰好 6000 字的完整正文的末条链接误判成残片。
TRUNC_CAPS = (800, 2000)
# 链接尾巴上粘的标点/闭合括号（JSON 数组、中文括号等），去掉后才是真链接
TRAIL = ".,)]}>'\"、。，）】"


def mine(blob, out):
    """从一段文本里取链接；返回被截断丢弃的条数。"""
    if not blob:
        return 0
    n = len(blob)
    dropped = 0
    for m in URL_RE.finditer(blob):
        u = m.group(0).rstrip(TRAIL)          # JSON 数组/引号尾巴：`…style/g-all]]`
        if not u or any(x in u for x in HOST_SKIP):
            continue
        if n in TRUNC_CAPS and m.end() == n:
            dropped += 1
            continue
        out.append(u)
    return dropped


# resource-ish keywords (what the user wants: things he can claim/join/download)
RES_KW = ("会员", "领取", "免费", "优惠", "注册", "报名", "下载", "申请", "申领", "开通",
          "兑换", "福利", "礼包", "额度", "试用", "活动", "比赛", "招募", "征", "赠")
# 戳一戳 / 表情素材，不是资源
HOST_SKIP = ("tianquan.gtimg.cn", "zb.vip.qq.com")


def hm(ts):
    if not ts:
        return "?"
    return dt.datetime.fromtimestamp(ts, TZ).strftime("%m-%d %H:%M")


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else dt.datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        __import__("datetime").datetime.strptime(date, "%Y-%m-%d")
    except Exception:
        raise SystemExit("dig_urls.py: 日期参数必须是 YYYY-MM-DD，收到 %r" % (date,))
    y, m, d = (int(x) for x in date.split("-"))
    start = int(dt.datetime(y, m, d, 0, 0, 0, tzinfo=TZ).timestamp())
    end = start + 86400

    rel = os.path.join("output", "days", "%s.jsonl" % date)
    src_path = os.path.join(HERE, rel)
    if not os.path.exists(src_path):
        print("[urls] FATAL 当天产物不存在：%s" % rel)
        print("[urls] 先跑 step 3：python extract_day.py %s" % date)
        sys.exit(2)

    rows = []
    source_rows = day_rows = 0
    dropped = 0
    day_min = None
    day_max = 0
    by_src = Counter()
    with open(src_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            source_rows += 1
            j = json.loads(line)
            try:
                ts = int(j.get("ts") or 0)
            except (TypeError, ValueError):
                ts = 0
            if not (start <= ts < end):
                continue                      # 来源里不该有别的天，有就落在窗口外
            day_rows += 1
            by_src[j.get("src") or "?"] += 1
            day_min = ts if day_min is None else min(day_min, ts)
            day_max = max(day_max, ts)
            group = j.get("chat_name") or j.get("chat") or "?"
            who = j.get("sender_name") or j.get("sender") or ""
            text = j.get("text") or ""
            hits = []
            dropped += mine(text, hits)
            dropped += mine(unescape_blob(j.get("raw") or ""), hits)
            for u in dict.fromkeys(hits):
                rows.append({"src": j.get("src") or "?", "group": group, "ts": ts,
                             "who": str(who), "url": u,
                             "ctx": re.sub(r"\s+", " ", text)[:160]})

    print("[urls] date=%s source=%s" % (date, rel))
    print("[urls] source_rows=%d day_rows=%d by_src=%s" % (source_rows, day_rows, dict(by_src)))
    print("[urls] 当天消息跨度 %s ~ %s" % (hm(day_min), hm(day_max)))
    print("[urls] url occurrences:", len(rows), "| 丢弃截断残片:", dropped)

    dom = Counter(re.sub(r"^https?://([^/]+).*$", r"\1", r["url"]) for r in rows)
    print("[urls] top domains:", dom.most_common(15))

    os.makedirs(WIN, exist_ok=True)
    with open(OUTJ, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # dedupe by url, keep first occurrence + count; flag resource-ish ones
    by = {}
    for r in rows:
        k = r["url"]
        if k not in by:
            by[k] = dict(r, n=1)
        else:
            by[k]["n"] += 1
    list_ = list(by.values())
    res = [r for r in list_ if any(k in (r["ctx"] or "") for k in RES_KW)]

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("日期 %s（来源 %s）全部链接（去重）共 %d 条；其中疑似资源型 %d 条\n"
                % (date, rel, len(list_), len(res)))
        f.write("当天消息 %d 条（%s），跨度 %s ~ %s\n"
                % (day_rows, dict(by_src), hm(day_min), hm(day_max)))
        f.write("域名分布: %s\n\n" % dom.most_common(20))
        f.write("=" * 100 + "\n【一】疑似资源型（可领取/报名/下载/申请）\n" + "=" * 100 + "\n")
        for r in sorted(res, key=lambda x: -(x["ts"] or 0)):
            f.write("[%s] %s %s | %s\n    %s\n    %s\n"
                    % (r["src"], hm(r["ts"]), r["group"][:18], r["who"][:12], r["url"], r["ctx"][:140]))
        f.write("\n" + "=" * 100 + "\n【二】其余链接（去重，按时间倒序）\n" + "=" * 100 + "\n")
        for r in sorted([x for x in list_ if x not in res], key=lambda x: -(x["ts"] or 0)):
            f.write("[%s] %s %s | %s\n    %s\n"
                    % (r["src"], hm(r["ts"]), r["group"][:18], r["who"][:12], r["url"]))

    max_url_ts = max((r["ts"] for r in rows), default=0)
    # 被截断的链接会表现为"自己是另一条 URL 的前缀"（如 http://wxapp.tc. 是 …/qq.com/… 的前缀）
    uset = {r["url"] for r in list_}
    prefix_susp = sorted(u for u in uset if any(v != u and v.startswith(u) for v in uset))
    if prefix_susp:
        print("[urls] WARN 疑似被截断的链接 %d 条：%s" % (len(prefix_susp), prefix_susp[:5]))
    meta = {"date": date, "source": rel, "source_rows": source_rows, "day_rows": day_rows,
            "by_src": dict(by_src), "day_min_ts": day_min, "day_max_ts": day_max,
            "day_min_hm": hm(day_min), "day_max_hm": hm(day_max),
            "occurrences": len(rows), "unique_urls": len(list_), "resource_ish": len(res),
            "truncated_dropped": dropped,
            "prefix_suspicious": len(prefix_susp), "prefix_samples": prefix_susp[:8],
            "max_url_ts": max_url_ts, "max_url_hm": hm(max_url_ts),
            "generated": dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S CST")}
    with open(OUTM, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("[urls] wrote %s | unique=%d resource-ish=%d | meta -> %s"
          % (OUTJ, len(list_), len(res), os.path.basename(OUTM)))


if __name__ == "__main__":
    main()
