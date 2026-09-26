# -*- coding: utf-8 -*-
"""llm_filter.py — 用**本地小模型**（Ollama）把水群单元再筛一层，不花 API token。

为什么要它（2026-09-13 用户："水消息还是多，想办法筛掉一些。现在本地有一个小模型"）：
机械手段已饱和（折叠 -20%、去重 -2.7%、清垃圾 -66%），再往下就得**读懂内容**才知道该丢谁。
本地 9B 足够干"**逐条二分类**"这种枯燥活，前提是——任务窄、输出格式死、不确定就留。

设计要点（防漏优先）：
  · 每批 20 条，让模型只回"**该留的编号**"（JSON 数组），一句话理由都不要 → 9B 也能稳定遵守
  · **解析失败 / 超时 / 空回复 → 整批全留**（fail-open：宁可多留，不许因模型抽风而丢信息）
  · 判据与产品口径一致：留"事实/安排/时间地点/规则/数字/链接/经验/踩坑/评价/问答"，丢"纯情绪/玩梗/复读/寒暄/表情标记"
  · 先小样本（--sample）实测质量与延迟，再决定要不要进管道 —— 这是用户的硬要求

用法:
  python tools\\llm_filter.py --date 2026-09-13 --sample 60          # 小样本实测
  python tools\\llm_filter.py --date <日期> --chat <群名>    # 只筛某个群
  python tools\\llm_filter.py --date 2026-09-13                      # 全量（慢）
产出: output/days/<date>_units_filtered.md（保留下来的单元）+ 控制台打印统计（ASCII）
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3.5:9b"
BATCH = 20

SYS = (
    "你在给一位清华大一新生筛群聊记录。他只关心**对他有用的信息**，不关心闲聊。\n"
    "对每条消息判断：**留** 还是 **丢**。\n"
    "【留】出现下列任一：具体事实或安排；时间/地点/截止；规则或流程；数字或价格；链接/资源/工具；"
    "别人的经验或踩坑；对课/老师/平台/事项的评价；求助与解答；与课业/宿舍/办事有关的通知。\n"
    "【丢】纯情绪或附和（哈哈、确实、太强、+1）；玩梗、复读、接龙；寒暄招呼；只有表情/图片标记；"
    "与这位学生无关的闲聊（游戏、追星、别人的私事）。\n"
    "**拿不准就留。漏掉有用信息的代价远大于多留一条。**\n"
    "只输出一个 JSON 数组，元素是【留】的消息编号，例如：[1,3,7]。不要解释、不要输出别的字。"
)
LINE = re.compile(r"^\[(\d+)\]\s*(.*)$")
# 白名单兜底（2026-09-13 实测漏率约 5% 后加的）：模型判"丢"但命中下列**特定**信号 → 强制留。
# 只收"低噪声、专指"的词（教务/教室/thuinfo 这类水群很少提到）；故意**不收** 怎么/哪里/有没有
# —— 那类在大群里太常见，收了等于白筛。命中即 rescued，单独计数便于复核。
RESCUE = re.compile(
    r"(https?://|thuinfo|学在清华|网络学堂|雨课堂|树洞|学堂在线|超星|"
    r"选课|绩点|学分|教务|注册|退课|补选|考试|大作业|作业|课本|第\d+页|上交|提交|习题|课件|勘误|预习|复习|实验报告|ddl|DDL|截止|报名|预约|缴费|"
    r"教室|[一二三四五六]教|校医院|报销|图书馆|宿舍|食堂|"
    r"周[一二三四五六日]|星期[一二三四五六日]|\d{1,2}月\d{1,2}|\d{1,2}[:：]\d{2}|"
    r"避雷|踩坑|听说|据说)")


def body(t):
    """剥掉 `HH:MM [问] [群名] 发言人: ` 前缀，只留消息正文。
    **必须这样做**：否则白名单里的 `\\d{1,2}:\\d{2}` 会命中每行开头的时间戳 → 全部强制保留
    （2026-09-13 实测踩过：rescued 153/153、drop 0%）。"""
    s = re.sub(r"^\d\d:\d\d\s*", "", t)
    s = re.sub(r"^(?:\[[^\]]*\]\s*)+", "", s)
    s = re.sub(r"^[^:：]{0,28}[:：]\s*", "", s, count=1)
    return s


def load_units(date, chat=None):
    p = os.path.join(HERE, "output", "days", "%s_units.md" % date)
    out = []
    for ln in io.open(p, encoding="utf-8", errors="replace"):
        ln = ln.rstrip("\n")
        if not ln.startswith("- "):
            continue
        body = ln[2:]
        if chat:
            # 2026-09-14 修 bug：原来只取**第一个**方括号，而 `units_day.py` 会给问/答行加 `[问]`/`[答]` 前缀
            #   → 这些行第一个方括号是 tag，按群名匹配就漏掉了（实测 09-14 大群 3301 单元只筛到 2666，
            #   漏掉的 635 条正是[问]/[答]——最该筛的一批）。改成扫**所有**方括号。
            names = re.findall(r"\[([^\]]+)\]", body)
            if not any(chat in nm for nm in names):
                continue
        out.append(body)
    return out


def ask(batch_lines, timeout=180, nudge=False):
    user = "消息列表：\n" + "\n".join("[%d] %s" % (i + 1, t) for i, t in enumerate(batch_lines)) + \
           "\n\n只回【留】的编号 JSON 数组："
    if nudge:
        # 空数组保护用的"反问"（2026-09-15）：模型回 [] 会整批清空，反问一次更稳妥
        user += "\n注意：这一批里只要出现事实、安排、时间、数字、通知、作业、链接就必须保留；只有整批确实全是玩梗/寒暄才回 []。"
    payload = {"model": MODEL, "stream": False, "think": False,
               "options": {"temperature": 0, "num_predict": 400},
               "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": user}]}
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    dt = time.time() - t0
    txt = ((j.get("message") or {}).get("content") or "").strip()
    m = re.search(r"\[[\s\d,]*\]", txt)
    if not m:
        # 宽容解析：只有当整段回复**几乎只由数字/分隔符组成**时才按编号读
        # （否则会有"把散文里的数字当编号"的风险 → 宁可 fail-open 全留）
        if txt and re.fullmatch(r"[\s\d,，、\[\]【】()]+", txt):
            keep = set(int(x) for x in re.findall(r"\d+", txt) if 1 <= int(x) <= len(batch_lines))
            if keep:
                return keep, dt, txt
        try:   # 解析不了就把模型原文落盘，便于诊断（曾经"三批全 fail-open"就是这么查出来的）
            io.open(os.path.join(HERE, "output", "window", "_llm_last_raw.txt"), "w",
                    encoding="utf-8", newline="\n").write(
                (txt or "(空回复)") + "\n\n[thinking] " + str(((j.get("message") or {}).get("thinking") or ""))[:500])
        except Exception:
            pass
        return None, dt, txt
    try:
        idx = json.loads(m.group(0))
    except Exception:
        return None, dt, txt
    keep = set(int(x) for x in idx if isinstance(x, (int, float)) and 1 <= int(x) <= len(batch_lines))
    return keep, dt, txt


def main():
    global MODEL, BATCH
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-09-13")
    ap.add_argument("--chat", default=None)
    ap.add_argument("--sample", type=int, default=0, help="只处理前 N 条（0=全部）")
    ap.add_argument("--random", action="store_true", help="小样本时**随机抽**（默认取前 N 条）—— 测漏率必须随机，不能只看开头")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--dry", action="store_true", help="只打印第一批的提示词，不调用模型")
    ap.add_argument("--out", default=None,
                    help="试验用：结果写到这个文件（被丢的写 <out>.dropped），**不覆盖当天产物**")
    a = ap.parse_args()
    MODEL, BATCH = a.model, a.batch

    units_p = os.path.join(HERE, "output", "days", "%s_units.md" % a.date)
    if not os.path.exists(units_p):
        # A17：**前提缺失 = failed**（不是空状态）。旧版这里直接 open() 抛栈，
        # 退出码虽然非零，但报错看不出是"前提没跑"还是"脚本坏了"。
        print("前提缺失：%s 不存在（先跑 units_day.py）" % units_p)
        return 2
    units = load_units(a.date, a.chat)
    if a.sample:
        if a.random:
            import random
            random.Random(20260913).shuffle(units)      # 固定种子 → 可复现
        units = units[:a.sample]
    if not units:
        # A17：**0 条是合法空状态 empty，不是失败**（当天该群确实没消息 / 全是噪音）。
        # 旧版 return 1 → 09-19、09-20 被记成 FAILED（假失败）。仍写出（空的）产物，
        # 免得 daily_prep 再因 "MISSING" 判一次失败。
        out0 = a.out or os.path.join(HERE, "output", "days", "%s_units_filtered.md" % a.date)
        io.open(out0, "w", encoding="utf-8", newline="\n").write("")
        print("当天无单元可筛（合法空状态 empty，非失败）；已写出空产物 %s" % out0)
        return 0
    if a.dry:
        print(SYS)
        print("--- 第一批 ---")
        for i, t in enumerate(units[:a.batch]):
            print("[%d] %s" % (i + 1, t))
        return 0

    kept, dropped, fails, total_s, chars_all, chars_keep = [], [], 0, 0.0, 0, 0
    rescued = 0
    for s in range(0, len(units), BATCH):
        chunk = units[s:s + BATCH]
        try:
            k, dt, raw = ask(chunk)
        except Exception as e:
            k, dt, raw = None, 0.0, "ERR:%s" % e
        total_s += dt
        try:   # 每批都把模型原文落盘 —— 诊断"为什么全丢/全留"必须有它
            io.open(os.path.join(HERE, "output", "window", "_llm_last_raw.txt"), "w",
                    encoding="utf-8", newline="\n").write("[batch %d-%d]\n%s" % (s + 1, s + len(chunk), str(raw)))
        except Exception:
            pass
        if k is None:
            fails += 1
            k = set(range(1, len(chunk) + 1))          # fail-open：整批全留
        if k is not None and not k and len(chunk) >= 10:
            # 空数组保护（2026-09-15）：模型回 `[]` 等于**整批清空**。一批里一条都不留很反常，
            # 先反问一次（点明"有事实/安排/数字/通知就得留"）；仍为空才接受为"整批确实是水"。
            try:
                k2, dt2, _raw2 = ask(chunk, nudge=True)
                total_s += dt2
            except Exception:
                k2 = None
            if k2:
                k, raw = k2, "nudge-retry -> %s" % (raw or "")
                print("    (空批次→反问后留 %d 条)" % len(k2))
            else:
                k = set(range(1, len(chunk) + 1))
                fails += 1
                print("    (空批次→反问仍为空，fail-open 整批全留)")
        for i, t in enumerate(chunk, 1):
            chars_all += len(t)
            if i in k:
                kept.append(t)
                chars_keep += len(t)
            elif RESCUE.search(body(t)):
                kept.append(t)                       # 白名单兜底：疑似有特定信号 → 留
                chars_keep += len(t)
                rescued += 1
            else:
                dropped.append(t)
        print("  batch %3d-%3d  留 %2d/%2d  %.1fs" % (s + 1, s + len(chunk), len(k), len(chunk), dt))
    out = a.out or os.path.join(HERE, "output", "days", "%s_units_filtered.md" % a.date)
    io.open(out, "w", encoding="utf-8", newline="\n").write(
        "\n".join("- " + t for t in kept) + "\n")
    dout = (a.out + ".dropped") if a.out else os.path.join(HERE, "output", "days", "%s_units_dropped.md" % a.date)
    io.open(dout, "w", encoding="utf-8", newline="\n").write(
        "\n".join("- " + t for t in dropped) + "\n")
    print("KEPT %d / %d  (drop %.1f%%)  chars %d -> %d (-%.1f%%)  rescued %d  fail-open %d batch  total %.1fs"
          % (len(kept), len(units), 100.0 * len(dropped) / len(units), chars_all, chars_keep,
             100.0 * (1 - chars_keep / max(1, chars_all)), rescued, fails, total_s))
    print("kept -> %s\ndropped -> %s" % (out, dout))

    # 群级覆盖报告（2026-09-15）：**整群清零**必须人看一眼 —— 起因是"漏报崔老师布置的作业"那轮排查，
    # 发现"过滤只覆盖大群、其余群靠 split_day 补齐"，任何整群消失都可能是这类层级错。
    def gname(t):
        m = re.match(r"^(?:\d\d:\d\d\s+)?((?:\[[^\]]*\]\s*)*)", t)
        tags = re.findall(r"\[([^\]]+)\]", m.group(1)) if m else []
        return tags[-1] if tags else "(none)"

    tot_g, keep_g = {}, {}
    for t in units:
        tot_g[gname(t)] = tot_g.get(gname(t), 0) + 1
    for t in kept:
        keep_g[gname(t)] = keep_g.get(gname(t), 0) + 1
    wiped = sorted((g, n) for g, n in tot_g.items() if n >= 5 and keep_g.get(g, 0) == 0)
    print("群覆盖：见过 %d 群 ｜ 整群清零 %d %s"
          % (len(tot_g), len(wiped), ("-> " + ", ".join("%s(%d)" % (g, n) for g, n in wiped)) if wiped else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
