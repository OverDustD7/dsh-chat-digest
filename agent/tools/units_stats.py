# -*- coding: utf-8 -*-
"""units_stats.py — 量"大群的体量都由什么构成"，为"还能砍掉多少"给依据。

用户 2026-09-13："想办法进一步缩减水群无用消息数量"。
不猜（上一轮我把「5000→800」估错了 4 倍）——先量：
  ① 按长度分桶（<8 / 8-15 / 15-30 / >=30 字）各占多少条、多少字符
  ② 其中"情绪/寒暄型"（拟声、附和、招呼，且没有数字/拉丁字母/关键词）占多少
  ③ "可能有信息"（含数字、链接、或课程/办事关键词）占多少
  ④ 原始 jsonl 的 type 分布（图片/文件类消息各多少）
用法: python tools\\units_stats.py [YYYY-MM-DD] [会话名关键字]
"""
import collections
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EMO = re.compile(r"^(哈+|嘻+|嘿+|呵+|呜+|呜哇|笑死|太强|牛|nb|NB|膜|tql|TQL|\+1|同|确实|真实|草|操|泪|哭|么么|晚安|早安|好家伙|离谱|绝了|可以可以|来了|收到|好的|谢谢|感谢|3q|thx)[\s!！。~～]*$")
INFO = re.compile(r"(\d|https?://|课|老师|考试|作业|宿舍|食堂|校|报名|链接|ddl|DDL|截止|选课|绩点|分|班|书院|讲座|活动|价格|元|预约|系统|平台|账号|密码|申请|表)")
LINE = re.compile(r"^- (\d\d:\d\d) (\[[问答]\] )?\[([^\]]+)\] ([^:]+): (.*?)(?: ×(\d+)人| \+(\d+))?$")


def main():
    args = [a for a in sys.argv[1:] if a]
    date = args[0] if args else "2026-09-13"
    key = args[1] if len(args) > 1 else ""   # 群名是私人值：命令行给，或填 <个人目录>/pipeline.yaml
    p = os.path.join(HERE, "output", "days", "%s_units.md" % date)
    buckets = collections.defaultdict(lambda: [0, 0])   # 桶 -> [条数, 字符]
    emo = [0, 0]
    info = [0, 0]
    total = [0, 0]
    for line in io.open(p, encoding="utf-8", errors="replace"):
        m = LINE.match(line.rstrip("\n"))
        if not m:
            continue
        chat, text = m.group(3), m.group(5)
        if key not in chat:
            continue
        n = len(text)
        total[0] += 1
        total[1] += n
        b = "<8" if n < 8 else ("8-15" if n < 15 else ("15-30" if n < 30 else ">=30"))
        buckets[b][0] += 1
        buckets[b][1] += n
        if EMO.match(text):
            emo[0] += 1
            emo[1] += n
        elif INFO.search(text):
            info[0] += 1
            info[1] += n
    print("会话含「%s」：%d 单元 ｜ %d 字符" % (key, total[0], total[1]))
    for b in ("<8", "8-15", "15-30", ">=30"):
        c, ch = buckets[b]
        print("  %-6s %5d 条 (%4.1f%%)  %7d 字符 (%4.1f%%)" % (b, c, 100.0 * c / max(1, total[0]), ch, 100.0 * ch / max(1, total[1])))
    print("  情绪/寒暄型（可折叠）：%d 条 ｜ %d 字符（%.1f%% 的字符）" % (emo[0], emo[1], 100.0 * emo[1] / max(1, total[1])))
    print("  含数字/链接/关键词（疑似有信息）：%d 条 ｜ %d 字符" % (info[0], info[1]))
    # 原始 jsonl 的 type 分布
    q = os.path.join(HERE, "output", "days", "%s.jsonl" % date)
    tc = collections.Counter()
    for line in io.open(q, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        j = json.loads(line)
        if key in (j.get("chat_name") or ""):
            tc[j.get("type")] += 1
    print("  原始 jsonl 里该会话的 type 分布:", dict(tc.most_common(6)))
    # 按 type 看"谁在贡献字符"（决定该裁哪一类）
    per = collections.defaultdict(lambda: [0, 0, 0])   # type -> [条数, 总字符, 最大]
    for line in io.open(q, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        j = json.loads(line)
        if key not in (j.get("chat_name") or ""):
            continue
        t = (j.get("text") or "")
        d = per[j.get("type")]
        d[0] += 1
        d[1] += len(t)
        d[2] = max(d[2], len(t))
    print("  按 type 的字符贡献（条数 / 总字符 / 均长 / 最长）:")
    for k, (c, ch, mx) in sorted(per.items(), key=lambda kv: -kv[1][1])[:8]:
        print("     %-10s %5d 条  %8d 字符  均 %4d  最长 %5d" % (k, c, ch, ch // max(1, c), mx))
    # 长单元里有多少是"链接/卡片正文"（可压成 标题+首句）
    URL = re.compile(r"https?://|mp\.weixin\.qq\.com|点击链接|查看详情|长按|扫码")
    lc = lch = uc = uch = 0
    for line in io.open(p, encoding="utf-8", errors="replace"):
        m = LINE.match(line.rstrip("\n"))
        if not m or key not in m.group(3):
            continue
        text = m.group(5)
        if len(text) < 30:
            continue
        lc += 1
        lch += len(text)
        if URL.search(text):
            uc += 1
            uch += len(text)
    print("  >=30 字单元：%d 条 / %d 字符；其中含链接/卡片特征：%d 条 / %d 字符（占长单元 %.0f%% 字符）"
          % (lc, lch, uc, uch, 100.0 * uch / max(1, lch)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
