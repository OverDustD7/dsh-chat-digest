# -*- coding: utf-8 -*-
r"""阶段 2 · 读 + 初提 —— **本地模型逐块读语料，产出带来源锚点的候选条目**（0 元）。

为什么要有它（2026-09-17）：省 token 路线定为「不外包」后，"读原始记录"从云端子代理
挪到本机 Ollama。实测 qwen3.5:9b 读 09-14 全天 2,467 行只用 111 秒、覆盖基线 93%、0 元。
代价是**它会编造细节**（实测把「秀钟6字班通知群」发的 SRT 立项写成「经管学院 SRT 立项」）
⇒ 本脚本的**核心设计就是给每条候选钉锚点**：让模型只能引用"它在块里真实读到的行号"，
锚点（群名 / HH:MM / 分片文件 / 行号 / 原文片段）由**脚本从被引用的行反查生成**，
不是模型自己写的 —— 这样阶段 5 一条 grep 就能回原文核，核不上的不许进条目。

与 `local_full_probe.py` 的区别：那个是**实验探针**（对账用，输出到 logs、不带锚点）；
这个是**管线件**（输出到 `output\days\<date>_candidates.json` + 人读的 `_candidates.md`）。

用法：
  python tools\local_prepass.py 2026-09-16                      # 用当天全部分片
  python tools\local_prepass.py 2026-09-16 --max-chunks 1        # 小样本试跑（纪律：先小后全）
  python tools\local_prepass.py 2026-09-15 --include output\days\2026-09-15_tail_2144.md --tag tail
  python tools\local_prepass.py 2026-09-16 --resume              # 断点续跑（已完成的块不重问）
"""
import argparse
import glob
import io
import json
import os
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAYS = os.path.join(HERE, "output", "days")
LOGS = os.path.join(HERE, "output", "logs")
URL = "http://127.0.0.1:11434/api/chat"

ROW = re.compile(r"^- (\d\d:\d\d)\s+(.*)$")          # 只认 `- HH:MM …`，挡掉「各会话条数」这类列表
KINDS = ("todo", "chance", "official", "peer", "resource", "life")

PROMPT = (
    "你是「聊天情报」的提炼助手。下面是一段微信群/QQ 消息，每行格式：`行号| - HH:MM [群] 人: 内容`。\n"
    "读者只有一个人：清华大一学生冯思韬（自动化+AI 方向）。请挑出**对他有用**的条目。\n"
    "判据（三问，皆否就不收）：① 需要他做什么？② 会不会影响他？③ 他以后用得上吗？\n"
    "硬规矩：\n"
    "· 动作项（作业/截止/提交/上交/报名/问卷/小测/考试/登记/领取）**一律收**，不许因「他可能已知」而丢；\n"
    "· 群里的经验/踩坑/对课与平台的评价也收（kind=peer）；官方通知 kind=official；资源/工具 kind=resource；"
    "生活办事 kind=life；可自由报名/申请的岗位·比赛·活动 kind=chance；其余要他做一次动作的 kind=todo；\n"
    "· 别人的私事、玩梗/复读/纯闲聊不收；**不许编造**：不要把 A 群的消息写成 B 群，不要加原文没有的院系/金额/截止。\n"
    "输出**只输出 JSON 数组**，每项 {\"head\":\"≤40字的一句话\",\"kind\":\"todo|chance|official|peer|resource|life\","
    "\"why\":\"≤30字\",\"lines\":[行号,…]}；`lines` 必须是你在本段里**真实看到**的行号（1–3 个即可）；没有可收的就输出 []。\n\n消息：\n"
)


def ask(model, content, timeout=900, num_predict=1500):
    # num_predict 是**必须的上限**：2026-09-17 实测 qwen3.5:9b 在某些块上会跑飞 ——
    # 一块输出 25,566 token（正常约 500）、耗时 249 秒、**返回 0 条**，静默丢掉那一块的覆盖。
    # 上限把它截断成"可发现的失败"，再由 run_chunk 标 _runaway，由 prepass_audit 报出来。
    payload = {"model": model, "stream": False, "think": False,
               "messages": [{"role": "user", "content": content}],
               "options": {"temperature": 0.2, "num_ctx": 32768, "num_predict": num_predict}}
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8"))
    return j, time.time() - t0


def load_rows(a):
    """按覆盖自检同一口径取语料：默认当天全部分片；`--include` 追加别的视图（如 tail）。"""
    files = sorted(p for p in glob.glob(os.path.join(DAYS, "%s_slice*" % a.date))
                   if not p.endswith("_slices.md"))
    if a.only_include:
        files = []
    for p in a.include or []:
        p = p if os.path.isabs(p) else os.path.join(HERE, p)
        if os.path.exists(p):
            files.append(p)
        else:
            print("!! --include 不存在，已跳过：%s" % p)
    rows, skipped = [], 0
    for f in files:
        for i, ln in enumerate(io.open(f, encoding="utf-8", errors="replace"), 1):
            s = ln.rstrip("\n")
            m = ROW.match(s)
            if m:
                rows.append({"file": os.path.relpath(f, HERE).replace("\\", "/"),
                             "line": i, "t": m.group(1), "g": group_of(m.group(2)), "raw": s[2:]})
            elif s.startswith("- "):
                skipped += 1
    return files, rows, skipped


def group_of(body):
    """群名 = 行首标记串里的**最后一个**方括号内容（`[问]/[答]/[卡片]` 在前，群名在后）。"""
    m = re.match(r"^((?:\[[^\]]*\]\s*)*)", body)
    tags = re.findall(r"\[([^\]]+)\]", m.group(1)) if m else []
    return tags[-1] if tags else "(none)"


def parse_json(txt):
    m = re.search(r"\[.*\]", txt or "", re.S)
    if not m:
        return []
    try:
        got = json.loads(m.group(0))
    except ValueError:
        return []
    return [it for it in got if isinstance(it, dict) and str(it.get("head") or "").strip()]


def run_chunk(model, chunk, base_no):
    """chunk: [{file,line,t,g,raw}]；base_no: 本块首行的全局序号（＝给模型看的行号）。"""
    lines, idx = [], {}
    for k, r in enumerate(chunk):
        no = base_no + k
        idx[no] = r
        lines.append("%d| - %s" % (no, r["raw"]))
    j, sec = ask(model, PROMPT + "\n".join(lines))
    txt = (j.get("message") or {}).get("content") or ""
    out = []
    for it in parse_json(txt):
        want = it.get("lines") if isinstance(it.get("lines"), list) else []
        anchors, bad = [], []
        for w in want[:6]:
            try:
                no = int(w)
            except (TypeError, ValueError):
                continue
            r = idx.get(no)
            if r is None:
                bad.append(w)                      # 编造的行号（不在本块里）——**留证，供阶段 5 判断**
            else:
                anchors.append({"file": r["file"], "line": r["line"], "no": no,
                                "t": r["t"], "g": r["g"], "src": r["file"].split("/")[-1],
                                "snippet": r["raw"][:110]})
        kind = str(it.get("kind") or "").strip()
        out.append({"head": str(it.get("head")).strip()[:80],
                    "kind": kind if kind in KINDS else "peer",
                    "why": str(it.get("why") or "").strip()[:60],
                    "_anchors": anchors, "_badLines": bad,
                    "_unanchored": not anchors})
    return out, sec, int(j.get("eval_count") or 0)


def write_review(path, date, cands, meta):
    """给人（＝主 agent＝我）读的紧凑视图：一行一条 + 锚点摘要。阶段 5 读这个，不读原始语料。"""
    L = ["# %s 本地初提候选（阶段 2 产物）" % date, "",
         "> %s" % meta, "> 锚点＝脚本从模型引用的行反查得来；`?` 开头的是**模型引用了不存在的行号**（可疑）。",
         ""]
    order = {k: i for i, k in enumerate(("todo", "chance", "official", "resource", "life", "peer"))}
    for k in sorted({c["kind"] for c in cands}, key=lambda x: order.get(x, 9)):
        grp = [c for c in cands if c["kind"] == k]
        L.append("## %s（%d 条）" % (k, len(grp)))
        for c in grp:
            a0 = c["_anchors"][0] if c["_anchors"] else None
            tag = "%s %s %s:%d" % (a0["g"], a0["t"], a0["src"], a0["line"]) if a0 else "**无锚点**"
            if c["_badLines"]:
                tag += " ｜? %s" % c["_badLines"]
            L.append("- **%s** ｜ %s ｜锚：%s" % (c["head"], c["why"] or "-", tag))
        L.append("")
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--chunk", type=int, default=150)
    # 默认模型（2026-09-17 用户定）：**A3B** —— 实测 09-16 全天 255 秒 / 73 条 / **0 跑飞**，
    # 而 9B 是 337 秒 / 84 条 / **1 块跑飞（静默丢掉一整块）**。一天绝对时间只差 1–2 分钟、两者都 0 元。
    # 9B 保留作快速预演：`--model qwen3.5:9b`。对照见 `docs\A3B-VS-9B.md`。
    ap.add_argument("--model", default="qwen3.6:35b-a3b")
    ap.add_argument("--max-chunks", type=int, default=0, help="0 = 不限（先拿 1 试跑）")
    ap.add_argument("--include", action="append", help="追加语料文件（可重复），如 09-15 的 tail 视图")
    ap.add_argument("--only-include", action="store_true",
                    help="**只用 --include 给的文件**，不取当天分片（补「尾巴」这类增量窗口时用，避免重读已处理过的分片）")
    ap.add_argument("--tag", default="", help="产物后缀，给同一天跑多批用（如 --tag tail）")
    ap.add_argument("--resume", action="store_true", help="跳过已完成的分块（按块缓存）")
    ap.add_argument("--redo", help="逗号分隔的块号：**忽略缓存重跑这几块**（跑飞的块用它补）")
    ap.add_argument("--only-chunks", help="逗号分隔的块号：只跑这几块（与 --redo 合用时＝只重跑这几块）")
    a = ap.parse_args()
    sfx = ("_" + a.tag) if a.tag else ""

    files, rows, skipped = load_rows(a)
    if not rows:
        print("没有语料（分片/--include 都没给出）：%s" % a.date)
        return 2
    chunks = [rows[i:i + a.chunk] for i in range(0, len(rows), a.chunk)]
    if a.max_chunks:
        chunks = chunks[:a.max_chunks]
    print("日期 %s%s ｜ 语料 %d 行（跳过非消息 `- ` 行 %d）｜ %d 个文件 ｜ 切块 %d 块 × %d 行 ｜ 模型 %s"
          % (a.date, ("/" + a.tag) if a.tag else "", len(rows), skipped, len(files),
             len(chunks), a.chunk, a.model))
    for f in files:
        print("   · %s" % os.path.relpath(f, HERE))

    cdir = os.path.join(LOGS, "_prepass_%s%s" % (a.date, sfx))
    if not os.path.isdir(cdir):
        os.makedirs(cdir)
    cands, t_all, tok, done, failed = [], 0.0, 0, 0, 0
    runaways = []

    def _ints(s):
        return {int(x) for x in (s or "").split(",") if x.strip()}

    redo, only = _ints(a.redo), _ints(a.only_chunks)
    for i, ch in enumerate(chunks, 1):
        cf = os.path.join(cdir, "chunk%02d.json" % i)
        cached = None
        if os.path.exists(cf) and i not in redo:
            cached = json.load(io.open(cf, encoding="utf-8"))
        if only and i not in only:                   # 只补跑指定的块：其余用缓存凑齐，**产物保持完整**（不许变成半份）
            if cached is None:
                print("  块 %02d/%02d  跳过（--only-chunks，且没有缓存 —— 这一块这次没读）" % (i, len(chunks)))
            else:
                cands += cached
                done += 1
            continue
        if cached is not None and (a.resume or only or redo):
            cands += cached
            done += 1
            print("  块 %02d/%02d  已完成（缓存 %d 条）" % (i, len(chunks), len(cached)))
            continue
        base_no = (i - 1) * a.chunk + 1
        got, sec, tk = None, 0.0, 0
        for attempt in (1, 2, 3):                    # 冷加载大模型时 Ollama 会回 HTTP 500（2026-09-17 实测 35B 首块）
            try:
                got, sec, tk = run_chunk(a.model, ch, base_no)
                break
            except Exception as e:                   # noqa: BLE001
                print("  块 %02d/%02d  第 %d 次失败：%s" % (i, len(chunks), attempt, e))
                got = None
                if attempt < 3:
                    time.sleep(5 * attempt)          # 让模型把权重加载完再试
        if got is None:
            failed += 1
            continue
        t_all += sec
        tok += tk
        # 跑飞判定：输出贴到上限，或"很慢 + 一条都没出" —— 这两种都要当**可疑失败**报出来，不许当成"这块没内容"
        if tk >= 1200 or (sec > 60 and not got):
            runaways.append(i)
            print("  块 %02d/%02d  **疑似跑飞**：%.0fs / 输出 %d token / %d 条 ⇒ 该块覆盖不可信，要单独重跑"
                  % (i, len(chunks), sec, tk, len(got)))
        for c in got:
            c["_chunk"] = i
        io.open(cf, "w", encoding="utf-8", newline="\n").write(json.dumps(got, ensure_ascii=False, indent=1))
        cands += got
        done += 1
        print("  块 %02d/%02d  %3d 行  %5.1fs  → %2d 条  （累计 %d 条 / %.0fs）"
              % (i, len(chunks), len(ch), sec, len(got), len(cands), t_all))

    cpath = os.path.join(DAYS, "%s_candidates%s.json" % (a.date, sfx))
    io.open(cpath, "w", encoding="utf-8", newline="\n").write(json.dumps(cands, ensure_ascii=False, indent=1))
    # 2026-09-20 新增：**机器可读的本次口径**（sidecar，不动 candidates json 的形状，免得别的读者被打破）。
    #   为什么需要：`prepass_audit` 原来靠"glob 当天全部分片"算应有块数 —— 增量轮（`--include tail.md --only-include`）
    #   只读了一部分语料，却被按全天算 ⇒ 每次都误报"缺 20 块"（KNOWN_ISSUES #131 / #136）。
    #   这里把**本次真的喂进模型的行数/块数**写下来，审计优先读它。
    mpath = os.path.join(DAYS, "%s_candidates%s.meta.json" % (a.date, sfx))
    io.open(mpath, "w", encoding="utf-8", newline="\n").write(json.dumps({
        "date": a.date, "tag": a.tag, "model": a.model, "chunk": a.chunk,
        "rows": len(rows), "chunks": len(chunks), "done": done, "failed": failed,
        "runaways": runaways, "candidates": len(cands), "seconds": round(t_all, 1),
        "include": list(getattr(a, "include", []) or []),
        "only_include": bool(getattr(a, "only_include", False)),
    }, ensure_ascii=False, indent=1))
    meta = ("语料 %d 行 / %d 块（完成 %d、失败 %d）｜模型 %s ｜耗时 %.0f 秒（%.1f s/块）｜输出 %d token ｜**API 花费 0**"
            "｜候选 %d 条（无锚点 %d 条）｜**疑似跑飞的块 %s**"
            % (len(rows), len(chunks), done, failed, a.model, t_all,
               t_all / max(1, done), tok, len(cands), sum(1 for c in cands if c["_unanchored"]),
               runaways or "无"))
    rpath = os.path.join(DAYS, "%s_candidates%s.md" % (a.date, sfx))
    write_review(rpath, a.date + ("/" + a.tag if a.tag else ""), cands, meta)
    print("\n" + meta)
    print("候选 JSON：%s\n人读视图：%s\n分块缓存：%s"
          % (os.path.relpath(cpath, HERE), os.path.relpath(rpath, HERE), os.path.relpath(cdir, HERE)))
    return 1 if (failed or done < len(chunks) or runaways) else 0     # 有块没跑成 / 有块跑飞 → 非零，**不许静默当成功**


if __name__ == "__main__":
    raise SystemExit(main())