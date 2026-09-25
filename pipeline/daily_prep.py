# -*- coding: utf-8 -*-
"""daily_prep.py — 每日总结的「数据准备」编排（一条命令跑完 + 逐步自检）。

用法:
    python daily_prep.py                # 准备"今天"的数据
    python daily_prep.py 2026-09-12     # 指定日期

流程（每步都自检，失败不中断，最后汇总）:
    **权威清单 = 本文件里 run(...) 的调用顺序**；**行数以运行后 prep_report.md 的表行数为准**
    （2026-09-15 实测 21 行 —— 别在这里写死数字，历史上 11/14/17/18/19 都出现过；
     查数字有没有腐烂：`python tools\\check_step_count.py`）：
      微信 DB 解密 -> QQ 解密+结构化导出 -> 当天消息提取 -> 精简提要 -> 公众号文章 ->
      跨会话时间轴 -> 文章卡片清单 -> 主题跨天回溯 -> 3g 话语单元化(降噪) -> 3h 官网/公众号当日新文章 ->
      3i 本地小模型过筛 -> 3i-b 语料覆盖自检 -> 3k 收藏刷新 -> 3k-b 公众号作者扫描 ->
      4 图片索引(含 wxgf 转码) -> 4b 文件附件索引(双目录) -> 3j 图片分诊(本地视觉) ->
      会话元数据(免打扰) -> 6 链接提取(当天全量) -> 6b 链接验证 -> 7 容量扫描 -> 8 媒体覆盖账本
      （3g/3i 降噪、3h 官网源、3j 本地视觉、3k 收藏、3k-b 作者扫描 都在管线里）
    注意：步数口径别在小节里写死（历史上 11/14/17/18/19 都出现过）—— **以 prep_report.md 的表行数为准**；
    另：3j 必须排在第 4 步（图片索引）之后（见 KNOWN_ISSUES #44）；
        第 4 步解不出图片密钥时用**专属退出码 3** → 记成「待微信登录」而不是 FAILED（查 `tools\\wx_status.py`）。
    **A08（2026-09-20）**：每步除"退出码 0 + 产物存在 + 行数够"外还查**产物新鲜度**（mtime 必须落在本步开始前
    `freshness_grace` 秒内），否则记 `STALE` —— 堵住"一步空跑 + 上一轮旧产物"被当成成功。
    关键步骤（1/3/3d/3g）失败 ⇒ **本脚本非零退出**（`_run.json` 里 `ok:false`），可选步骤失败只记 degraded。

产出：output/daily/<date>/prep_report.md（各步状态/条数/耗时）＋ 同目录 `_run.json`（机器可读：ok/failed/degraded/steps）
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
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
TZ = dt.timezone(dt.timedelta(hours=8))
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 工作区
SCRIPTS = os.path.join(HERE, "scripts")
VENV_PY = os.path.join(os.path.dirname(HERE), "venv", "Scripts", "python.exe")
NT_UTIL = os.path.join(os.path.dirname(HERE), "nt_msg_db_util", "3.export.py")

WX_KEY = C.req("wx_key", "微信库解密密钥")
QQ_KEY = C.req("qq_key", "QQ 库解密密钥")
QQ_SRC = os.path.join(QQ_DATA_DIR, SELF_QQ, "nt_qq", "nt_db", "nt_msg.db")


def hm(ts):
    try:
        return dt.datetime.fromtimestamp(int(ts), TZ).strftime("%m-%d %H:%M")
    except (TypeError, ValueError):
        return "?"


def wx_login_line():
    """一行微信状态 —— **多信号**（2026-09-15 立，同日就被修正过一次）。

    修正原因（务必记住）：第一版只用 `kvcomm\\config.ini` 的 `last_uin` 是否为空来判，
    而 20:02 实测**已登录时 `last_uin` 依然是空的** → 那个判据被反例证伪。
    现在的**主信号＝kvcomm 里 `key*` 文件名是否含非 0 的 code 段**（为 0 就是"客户端还没协商出密钥"）。
    为什么值得占报告一行：没协商出密钥时第 4 步拿不到图片密钥，报出来像"脚本坏了"。
    """
    try:
        if SCRIPTS not in sys.path:
            sys.path.insert(0, SCRIPTS)
        import wx_images as W  # noqa: PLC0415

        st = W.wx_login_state()
    except Exception as e:  # noqa: BLE001
        return "判不出来（%s）" % e
    if st["codeNegotiated"]:
        return "在线（kvcomm 已协商出密钥 code=%s）" % (st["codes"][0] if st["codes"] else "?")
    if st["loggedIn"]:
        return "疑似在线（last_uin 非空，但 kvcomm 还没协商出密钥）"
    if st["codes"]:
        return ("**客户端没协商出密钥**（kvcomm 只有 code=0 的占位文件）→ 第 4/3j 步会停；"
                "登录微信后重跑这两步即可（**注意：`last_uin` 空不等于未登录**）")
    return "判不出来（kvcomm 目录里没有 key* 文件）"


def img_key_note(date):
    """图片索引那一步的注记：读 day_images.py 落的 `<date>_images.status.json`。"""
    p = os.path.join(HERE, "output", "days", "%s_images.status.json" % date)
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
    except (OSError, ValueError):
        return []
    if j.get("ok"):
        return []
    return ["图片线停：%s" % (j.get("reason") or "密钥未解出")]


def check_url_coverage(date):
    """校验 step 6 的链接提取**覆盖了整天**（KNOWN_ISSUES #30）。

    只看"文件存在 + 行数>0"是不够的：旧版读跨天窗口快照时当天只覆盖半天，
    产物照样非空。这里读 `all_urls_meta.json`，硬校验来源就是当天产物、
    且来源里没有落在窗口外的行。返回 (status, notes)。
    """
    p = os.path.join(HERE, "output", "window", "all_urls_meta.json")
    if not os.path.exists(p):
        return "CHECK-FAILED", ["all_urls_meta.json MISSING"]
    try:
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
    except Exception as e:  # noqa: BLE001
        return "CHECK-FAILED", ["meta 读取失败: %s" % e]
    want = os.path.join("output", "days", "%s.jsonl" % date)
    bad = []
    if m.get("date") != date:
        bad.append("meta.date=%s != %s" % (m.get("date"), date))
    if m.get("source") != want:
        bad.append("source=%s != %s（在读跨天窗口快照？）" % (m.get("source"), want))
    if m.get("source_rows") != m.get("day_rows"):
        bad.append("source_rows=%s != day_rows=%s（来源含窗口外的行）"
                   % (m.get("source_rows"), m.get("day_rows")))
    if not m.get("day_rows"):
        bad.append("day_rows=0")
    notes = ["覆盖 %s ~ %s 共 %s 条消息（%s）"
             % (m.get("day_min_hm"), m.get("day_max_hm"), m.get("day_rows"), m.get("by_src")),
             "唯一URL=%s 条目=%s 资源型=%s｜末条URL %s"
             % (m.get("unique_urls"), m.get("occurrences"),
                m.get("resource_ish"), m.get("max_url_hm"))]
    if m.get("prefix_suspicious"):
        notes.append("疑似被截断链接 %s 条（前几条：%s）"
                     % (m.get("prefix_suspicious"), m.get("prefix_samples")))
    if bad:
        notes = ["COVERAGE: " + "; ".join(bad)] + notes
        return "CHECK-FAILED", notes
    return "ok", notes


def day_window(date):
    """当天产物的**实际数据窗口**（首/末条消息时间 + 条数）。

    2026-09-15 立的（用户当场纠正）：一次"恢复"把采集指针从真实的 09-13 23:46 错拨成 09-14 00:00，
    于是 09-13 23:46:40–24:00（约 14 分钟）**哪一轮都没覆盖**；而当时**没有任何一处显示"这天到底取到哪"**。
    现在每份 `prep_report.md` 头部都带这一行 —— 一眼能看出某天是不是只取到半天。
    配套：`/collect` 拨指针的前移护栏（前移 >10 分钟必须显式 confirm，见 host body）。
    """
    p = os.path.join(HERE, "output", "days", "%s.jsonl" % date)
    first = last = None
    n = 0
    if os.path.exists(p):
        with open(p, encoding="utf-8", errors="replace") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                n += 1
                try:
                    j = json.loads(ln)
                except Exception:
                    continue
                t = j.get("time") or j.get("ts") or j.get("timestamp")
                if t:
                    if first is None:
                        first = t
                    last = t

    def hm(v):
        if not v:
            return "?"
        v = float(v)
        if v > 1e12:
            v = v / 1000.0
        return dt.datetime.fromtimestamp(v, TZ).strftime("%m-%d %H:%M:%S")

    return n, hm(first), hm(last)


def run(label, argv, check_paths=(), check_lines=(0, None), timeout=1800, status_map=None,
        critical=False, empty_ok=False, freshness_grace=300):
    """执行一步并自检。check_lines=(min_expected, max_allowed_or_None)

    status_map: {退出码: 状态名} —— 把"可预期的前置条件缺失"从 FAILED 里分出来。
    例：`{3: "待微信登录"}`（day_images.py 解不出图片密钥时用专属退出码 3）。

    A08（2026-09-20 审计 P02）：**只看"退出码 0 + 文件存在 + 行数够"不够**。
    实测"一步空跑（noop）＋ 上一轮的旧产物"照样判 ok —— 下游于是继续消费旧数据。
    现在每个 check_path 还要过**新鲜度**：产物必须在本次步骤开始前 freshness_grace 秒内
    被写过，否则记 `STALE`。所以"旧产物顶包"这条路被堵住了。

    critical: **默认 False（可选）** —— 只有"没有它就没有语料"的那几步（1 解密 / 3 消息提取 /
      3d 时间轴 / 3g 单元化）显式标 True。关键步骤失败 → 整体非零退出；可选步骤失败只记 degraded。
      **默认必须是不致命**（A21，2026-09-22）：2026-09-21 那轮 23/23 步里只有 `3i` 一步 CHECK-FAILED，
      却因为默认 critical=True 把整轮判成 `ok:false` / 退出码 1 —— 主 agent 看到一个"失败"的报告就停下了，
      整晚的取数白跑。**"默认致命"会让任何一步的小毛病升级成整轮失败。**
    empty_ok: 0 条算**合法空状态** `empty`（当天确实没消息 / 该群没单元），不算失败（A17）。
      **内容类步骤一律要开**：`3i` 那次就是"`_units.md` 里一条目标群都没有"的合法空结果，
      被 `check_lines=(1,None)` 记成 CHECK-FAILED。
    """
    t0 = time.time()
    print("\n=== [%s] %s" % (label, " ".join(os.path.basename(a) for a in argv)))
    try:
        p = subprocess.run(argv, cwd=SCRIPTS, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        tail = (p.stdout or "").strip().splitlines()[-4:]
        for line in tail:
            print("    " + line)
        if p.returncode == 0:
            status = "ok"
        elif status_map and p.returncode in status_map:
            status = status_map[p.returncode]
        else:
            status = "FAILED(exit=%d)" % p.returncode
    except subprocess.TimeoutExpired:
        status, tail = "TIMEOUT", []
    except Exception as e:  # noqa: BLE001
        status, tail = "ERROR: %s" % e, []
    notes = []
    for cp in check_paths:
        path = cp if os.path.isabs(cp) else os.path.join(HERE, cp)
        if not os.path.exists(path):
            notes.append("MISSING %s" % cp)
            status = status if status != "ok" else "CHECK-FAILED"
            continue
        try:
            age = t0 - os.path.getmtime(path)
        except OSError:
            age = 0.0
        if age > freshness_grace:
            notes.append("STALE %s（mtime 比本步开始早 %.0f 秒 = 上一轮的旧产物）" % (cp, age))
            status = status if status != "ok" else "CHECK-FAILED"
        n = sum(1 for _ in open(path, encoding="utf-8", errors="replace"))
        lo, hi = check_lines
        if n < lo:
            notes.append("%s lines=%d < %d" % (cp, n, lo))
            if status == "ok":
                status = "empty" if (empty_ok and n == 0) else "CHECK-FAILED"
        if hi is not None and n > hi:
            notes.append("%s lines=%d > %d (duplication?)" % (cp, n, hi))
            if status == "ok":
                status = "CHECK-FAILED"
        notes.append("%s lines=%d" % (cp, n))
    dt_s = time.time() - t0
    print("    -> %s (%.1fs) %s" % (status, dt_s, "; ".join(notes)))
    return {"step": label, "status": status, "seconds": round(dt_s, 1), "notes": notes,
            "critical": bool(critical)}


def main():
    # 在函数内 import：本函数会被审计探针单独 exec（作用域里只有注入的名字），
    # 引用模块级 `time`/`json` 会 NameError。
    import json
    import time

    date = sys.argv[1] if len(sys.argv) > 1 else dt.datetime.now(TZ).strftime("%Y-%m-%d")
    y, m, d = (int(x) for x in date.split("-"))
    start = int(dt.datetime(y, m, d, 0, 0, 0, tzinfo=TZ).timestamp())
    outdir = os.path.join(HERE, "output", "daily", date)
    os.makedirs(outdir, exist_ok=True)
    t_start = time.time()
    print("daily_prep date=%s start_epoch=%d" % (date, start))

    steps = []
    # 关键/可选分级（A08）：**1/3/3d/3g 是关键**（没有它们就没有语料可交付）；
    # QQ 两步标可选 —— QQ 客户端没开时源库停更，不该因此判定"整天失败"，
    # 但它的产物陈旧会被新鲜度自检抓成 STALE → 记 degraded，报告里看得见。
    steps.append(run("1-微信DB解密", [VENV_PY, "wx_decrypt3.py", WX_KEY],
                     ["output/wx/message_0_plain.db", "output/wx/contact_plain.db"],
                     critical=True))
    steps.append(run("2-QQ解密+导出",
                     [VENV_PY, "qq_decrypt_hex.py", QQ_KEY, QQ_SRC,
                      os.path.join(HERE, "output", "qq", "nt_msg_plain.db")],
                     ["output/qq/nt_msg_plain.db"], critical=False))
    steps.append(run("2b-QQ结构化导出",
                     [VENV_PY, NT_UTIL, "--src", os.path.join(HERE, "output", "qq", "nt_msg_plain.db"),
                      "--dst", os.path.join(HERE, "output", "qq", "nt_msg_export.db")],
                     ["output/qq/nt_msg_export.db"], critical=False))
    steps.append(run("3-当天消息提取(不覆盖窗口文件)", [VENV_PY, "extract_day.py", date],
                     ["output/days/%s.jsonl" % date], check_lines=(1, None),
                     critical=True, empty_ok=True))
    steps.append(run("3b-当天精简提要", [VENV_PY, "day_brief.py", date],
                     ["output/days/%s_brief.md" % date]))
    steps.append(run("3c-公众号文章提取", [VENV_PY, "wx_biz.py"],
                     ["output/window/biz_articles.jsonl"], check_lines=(1, None), empty_ok=True))
    # 3d/3e：提炼用的两个"视图"（2026-09-13 加）——
    #   3d 跨会话时间轴：简报是按会话分组的，同一件事的碎片看不见彼此 → 这里合并成一条时间轴
    #   3e 文章卡片清单：把当天文章卡片与**本地已抓正文**对上（历史上抓过的正文在 output/window/articles/）
    #      起因：某条信息那条只读了群消息、没读文章正文，漏了文章里的联系人
    # A17（2026-09-20 审计）：3d/3g 原先是**写死的 50 行门槛**，09-19/09-20 只有 26 条 WX 时
    #   就被判 CHECK-FAILED —— 小样本日被误标失败。现在门槛降到"至少 1 行"，
    #   "每个群都进了语料"由 `3i-b-语料覆盖自检`（按来源覆盖，不按行数）负责；
    #   真正 0 行时记 `empty`（合法空状态），不是失败。
    steps.append(run("3d-跨会话时间轴", [VENV_PY, os.path.join(HERE, "tools", "day_timeline.py"), date],
                     ["output/days/%s_timeline.md" % date], check_lines=(1, None),
                     critical=True, empty_ok=True))
    steps.append(run("3e-文章卡片清单(含本地正文对照)", [VENV_PY, os.path.join(HERE, "tools", "day_articles.py"), date],
                     ["output/days/%s_articles.md" % date], check_lines=(1, None), critical=False))
    steps.append(run("3f-主题跨天回溯", [VENV_PY, os.path.join(HERE, "tools", "day_threads.py"), date, "3"],
                     ["output/days/%s_threads.md" % date], check_lines=(1, None), empty_ok=True))
    # 3h：官网/公众号当日新文章（2026-09-14 新增）
    #   为什么要有这一步：wx_biz.py（3c）只读**本地微信库** → 只覆盖"他关注的号"；
    #   没关注但该看的号、以及信息源官网的「通知公告/活动预告」都在外面，而主 agent 禁用宿主 web 工具
    #   （browser_*/web_fetch/read_page）→ 只能靠本机 node 脚本抓（零插件、与本机抓文章同一套 UA）。
    #   产出自带"近 14 天每日条数"用于自证"当天 0 篇"（沿用既有纪律），并有"未标日期"兜底段。
    # 3g：话语单元化（2026-09-14）—— 机械降噪：连续发言折叠 + 复读合并 + 全局去重 + 清垃圾
    #   顺带修掉一个数据质量 bug：QQ 原始媒体 JSON 与 [图片:hash] 占位文本会当成"正文"混进来
    #   （实测 09-13 大群 146,800 → 49,990 字符，-66%）。主 agent 提炼时读这个而不是原始行。
    steps.append(run("3g-话语单元化(降噪)", [VENV_PY, os.path.join(HERE, "tools", "units_day.py"), date],
                     ["output/days/%s_units.md" % date], check_lines=(1, None),
                     critical=True, empty_ok=True))
    steps.append(run("3h-官网/公众号当日新文章", ["node", os.path.join(SCRIPTS, "day_web_articles.mjs"), date],
                     ["output/window/web_articles_%s.md" % date], check_lines=(1, None), empty_ok=True))
    # 3i：本地小模型过筛（2026-09-14）—— qwen3.5:9b 逐条二分类「留/丢」，**不花 API token**
    #   实测（09-13 大群随机 200 条）：丢 73.0%、字符 -70.2%、rescued 7、fail-open 0、2.9 秒；
    #   漏率约 5%（人工抽检 45 条）→ 已加白名单兜底（RESCUE）；被丢的原文留在 _units_dropped.md 可回查。
    #   失败/超时一律 fail-open 全留 —— 宁可多留，不许因模型抽风丢信息。
    steps.append(run("3i-本地小模型过筛", [VENV_PY, os.path.join(HERE, "tools", "llm_filter.py"),
                                        "--date", date, "--chat", MAIN_GROUP],
                     ["output/days/%s_units_filtered.md" % date], check_lines=(1, None),
                     empty_ok=True, timeout=1200))
    # 3i-b：语料覆盖自检（2026-09-15 新增）—— 3i 只筛大群，其余群靠 split_day 补齐；
    #   这条保证"源里每个群都进了语料"，否则"分片全覆盖"名不副实。
    #   立这条的起因：某次作业在语料里却没被报出（层级判断错），查证时发现
    #   split_day 把 `[问]/[答]` 标记当群名，误排除 59 行；现在既有自检也有修复。
    steps.append(run("3i-b-语料覆盖自检", [VENV_PY, os.path.join(HERE, "tools", "check_corpus_coverage.py"),
                                        date, "--quiet"],
                     [], timeout=120))
    # 3k：收藏刷新（2026-09-14）—— 收藏是「他关心什么」最硬的信号；
    #   用户这轮要测的链就是「查看我的收藏 → 找教学云盘链接」，而收藏刷新原本**不在管线里**。
    steps.append(run("3k-收藏刷新", [VENV_PY, "favorites.py"],
                     ["docs/knowledge/collections.md"], check_lines=(1, None), empty_ok=True))
    # 3k-b：公众号作者扫描（2026-09-15 用户要求「你每天都该看一眼（别人转发的，自己在网上搜）」）
    #   为什么需要：微信只把**他已关注**号的推送写进本地（biz_articles.jsonl）→ 只看它，能发现的号
    #   永远只有他自己关注的那几个。这一步从 `output/days/*_articles.md` 的文章卡片反解
    #   "**别人转发的文章是谁写的**"（消息正文里的链接是截断的，必须用文章卡片那层），
    #   并标出"值得关注但他还没关注"的候选池；主 agent 每天据此把值得的号补进
    #   `docs/knowledge/official_accounts.md` 第一节，并自己 web_search 再搜一遍。
    steps.append(run("3k-b-公众号作者扫描", [VENV_PY, os.path.join(HERE, "tools", "biz_authors.py"), "--fetch", "--limit", "20"],
                     ["output/window/biz_authors.md"], check_lines=(1, None), empty_ok=True, timeout=900))
    s4 = run("4-当天图片索引(含wxgf转码)", [VENV_PY, "day_images.py", date],
             ["output/days/%s_images.json" % date],
             status_map={3: "待微信登录"})
    s4["notes"] = img_key_note(date) + s4["notes"]
    steps.append(s4)
    # 4b-文件附件索引（A01，2026-09-20 审计）：用户 2026-09-12 就要求"顺便把文件看一看"，
    #   但 `find_attachments.py` 的根写死成**不存在**的 `output/wx/msg/attach` ⇒ 永远静默报 0
    #   ⇒ 近几轮全是假阴性（3 例已核实）。现在：真实根（或 WX_ROOT）＋ **两处都扫**
    #   （`msg\file\YYYY-MM\` 与 `msg\attach\<md5>\YYYY-MM\Rec\<msgid>\F\0\`），
    #   缺根时退出码 3 → 记"无微信附件根"（**与"扫了但没有"分开**），产出 `output/days/<date>_files.json`。
    steps.append(run("4b-文件附件索引(双目录)", [VENV_PY, "find_attachments.py", date],
                     ["output/days/%s_files.json" % date], check_lines=(1, None),
                     critical=False, status_map={3: "无微信附件根"}))
    # 3j：图片分诊（2026-09-14，本地视觉 qwen3.5:9b）—— 图片 token 是全流程最贵的
    #   实测（09-13 全量 75 张）：需强模型回看 38 ｜ **判为无信息 37（49% 可完全不进强模型）** ｜ 失败 0 ｜ 69 秒。
    #   先 PIL 归一化（转 RGB + 限长边 1568 + 重编码 JPEG）再喂：修前 11/75 报 HTTP 400（不是尺寸问题，是格式变体），修后 0。
    #   失败/超时一律 fail-open 并入「需回看」——绝不当 noise 丢掉。
    #   **顺序修正（2026-09-14 实测）**：它读的是第 4 步产出的 `<date>_images.json`，原先排在 4 之前 → 每次必 FAILED
    #   （`缺 output/days/<date>_images.json（先跑 4-图片索引）`）→ 已挪到第 4 步之后。
        # 2026-09-15：第 4 步没成（最常见＝微信未登录）时**不跑 3j** —— 它读的是第 4 步产出的
    # `<date>_images.json`；拿上一轮的旧索引去分诊，会产出一份看着正常、实际是旧图的 `_vision.md`。
    # 不是"静默跳过"：报告里留一行带原因。
    if s4["status"] == "ok":
        # 2026-09-20：超时 1200 → **2400 秒**。实测 09-18 有 81 张图时 1200 秒不够（TIMEOUT 后靠手工补跑）；
        #   根因是本地视觉模型在这台机器上跑不满 GPU（16 GB 显存装不下大模型），不是脚本慢。
        #   超时是**可见失败**（报告里带 TIMEOUT），所以这里只放宽余量、不改判据。
        steps.append(run("3j-图片分诊(本地视觉)", [VENV_PY, os.path.join(HERE, "tools", "vision_triage.py"), date],
                         ["output/days/%s_vision.md" % date], check_lines=(1, None), empty_ok=True, timeout=2400))
    else:
        steps.append({"step": "3j-图片分诊(本地视觉)", "status": "跳过(%s)" % s4["status"], "seconds": 0.0,
                      "notes": ["第 4 步未产出本日图片索引；用上一轮旧索引分诊会给出误导性结论，故不跑"]})
    steps.append(run("5-会话元数据(免打扰)", [VENV_PY, "wx_session_meta.py"],
                     ["output/window/session_meta.json"]))
    s6 = run("6-链接提取(当天全量)", [VENV_PY, "dig_urls.py", date],
             ["output/window/all_urls.jsonl", "output/window/all_urls_meta.json"])
    cov_status, cov_notes = check_url_coverage(date)
    if cov_status != "ok" and s6["status"] == "ok":
        s6["status"] = "CHECK-FAILED"
    s6["notes"] = cov_notes + s6["notes"]
    steps.append(s6)
    steps.append(run("6b-链接验证", ["node", os.path.join(SCRIPTS, "verify_links.mjs")],
                     ["output/window/url_check.md"]))
    steps.append(run("7-容量扫描", [VENV_PY, "scan_storage.py"], ["output/window/storage_scan.md"]))
    # 8-媒体覆盖账本（A13，2026-09-20 审计）：把"文章/图片/文件附件/QQ 媒体/音视频"五类各自的
    #   **覆盖状态**摆到一张账上 —— 逐条状态 / 只有总数 / 完全没接线，三类分开写。
    #   为什么要有它：A13 的原文说得很准——"反爬、未落盘本身是边界，**静默漏报边界**才是问题"。
    #   放在最后：它要读 3j 的 `_vision.md` 与 4b 的 `_files.json`。可选步骤（缺某类只记 degraded）。
    steps.append(run("8-媒体覆盖账本", [VENV_PY, os.path.join(HERE, "tools", "media_ledger.py"), date],
                     ["output/days/%s_coverage.md" % date], check_lines=(1, None),
                     critical=False, timeout=300))

    n_msg, tw0, tw1 = day_window(date)
    lines = ["# 每日数据准备报告 · %s" % date, "",
             "- 生成时间：%s" % dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S CST"),
             "- 窗口起点 epoch：%d（= %s 00:00 CST）" % (start, date),
             "- **数据窗口自证：%s ~ %s（%d 条）** ← 这一天实际取到哪，一眼可见（2026-09-15 立）" % (tw0, tw1, n_msg),
             "- **微信登录态：%s** ← 未登录时第 4/3j 步（图片线）必停，那不是脚本错误（2026-09-15 立）" % wx_login_line(), "",
             "| 步骤 | 状态 | 耗时 | 备注 |", "|---|---|---|---|"]
    for s in steps:
        lines.append("| %s | %s | %ss | %s |" % (s["step"], s["status"], s["seconds"],
                                                 "; ".join(s["notes"])[:160]))
    bad = [s for s in steps if not (s["status"] in ("ok", "empty") or s["status"].startswith("跳过("))]
    crit_bad = [s for s in bad if s.get("critical", True)]
    degraded = [s for s in bad if not s.get("critical", True)]
    lines += ["", "失败/异常步骤：%s" % (", ".join(s["step"] for s in bad) if bad else "无"),
              "- **整体：%s**（关键步骤失败 %d 个 ｜ 可选步骤 degraded %d 个）"
              " ← 判据与逐项状态见同目录 `_run.json`"
              % ("FAILED" if crit_bad else ("degraded" if degraded else "ok"),
                 len(crit_bad), len(degraded))]
    lines += ["", "## 交给子代理的输入", "",
              "- `output/days/%s.jsonl`（当天消息；字段 `src`(WX/QQ)/chat/chat_name/ts/sender/type/text/raw/msg_id）" % date,
              "- `output/days/%s_files.json`（**文件附件索引**：文件名/字节数/本地路径/found；"
              "`found:false` = 本机确实没有，不是没查）" % date,
              "- `output/days/%s_brief.md`（按会话分组的可读简报；**主 agent 读它建立全局，分片子代理只读自己那片**）" % date,
              "- `output/days/%s_images.json`（图片索引；已转码的 wxgf 有 jpg 路径）" % date,
              "- **`output/days/%s_timeline.md`（跨会话时间轴）—— ⚠ **它是索引、不是读物**：只读开头的「跨群线索索引 A/B」两节，要细节 `grep -n` 定位后只读几行；**不要整读**（成本审计：该文件 138 KB~813 KB，整读一次就是几十万 token）" % date,
              "- **`output/days/%s_articles.md`（当天文章卡片清单 ↔ 本地已抓正文路径；**有正文的必须读**，别只读群消息）**" % date,
              "- `output/days/%s_coverage.md`（**逐类媒体覆盖账本**：文章/图片/文件附件/QQ 媒体/音视频各自的"
              "覆盖状态；`_coverage.json` 是同一份的机器可读版）" % date,
              "- `output/qq/nt_msg_export.db`（QQ 消息；`content` JSON 里有文件名/链接）",
              "- `url_check.md`（链接验证**只看报告行**），免打扰标记**不可信**——以 `docs/knowledge/channels.md` 的人工清单为准",
              "- `output/window/storage_scan.md`（容量，用于「文件处置建议」栏；**只看结论行**）",
              "- 任务书模板：`docs/每日模板.md`；**冷启动卡：`工作手册.md`（≤150 行，先读这个就够）**",
              "",
              "> **下列文件禁止整读**（2026-09-15 成本审计）：`output/window/session_meta.json`（**396 KB / 1.9 万行**）、",
              "> `output/window/all_urls.jsonl`（144 KB）—— 需要时用脚本或 `grep` 取字段，别把整份喂进上下文。",
              "> 注意：`output/window/wx_raw.jsonl` 是**窗口快照**（跨天、且**没有 `src` 字段**），",
              "> 不要拿它当某一天的数据用 —— `day_brief.py` 依赖 `src`，会 KeyError 或把 WX/QQ 混在一起。"]
    rep = os.path.join(outdir, "prep_report.md")
    with open(rep, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    # A08：落一份**机器可读的本轮记录** —— 关键步骤失败就非零退出，
    # 让"取数与交付是否通过"有据可查（上游不许只凭 HTTP/文件存在当成功）。
    rc = 1 if crit_bad else 0
    rec = {"date": date, "started_at": int(t_start), "at": int(time.time()),
           "n_msg": n_msg, "window": [tw0, tw1], "ok": rc == 0,
           "failed": [s["step"] for s in crit_bad], "degraded": [s["step"] for s in degraded],
           "steps": [{"step": s["step"], "status": s["status"], "seconds": s["seconds"]} for s in steps]}
    try:
        with open(os.path.join(outdir, "_run.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
    except OSError as e:
        print("!! _run.json 写失败:", e)
    print("\n" + "\n".join(lines[-12:]))
    print("\nreport ->", rep)
    print("整体：%s（关键失败 %d ｜ degraded %d）｜ 退出码 %d"
          % ("FAILED" if rc else ("degraded" if degraded else "ok"), len(crit_bad), len(degraded), rc))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())