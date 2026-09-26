"""启动自检（每轮唤醒先跑这个，省掉逐项手敲）。

用法:
    python tools\\boot_check.py

做四件事（只读，不写任何运行态）：
  1. 当前时间（CST，用 Python 显式时区，避免 pwsh -UFormat %s 的 +8h 坑）；
  2. 读插件 live /state（**唯一可信来源**；%TEMP%\\chat-feed\\state.json 已不是）：
     待发引用 / 条目摘要 / 会话 id / 运行标志；
  3. 报告 output\\days 最新日期与断档天数（断档 >= 2 天要报告，但**不自行补做**）；
  4. 报告 output\\daily 与 docs\\summary_* 最新产物。

实现要点（两个坑）：
  - **不走子进程**：Windows 下子进程管道默认按 cp936 解码，cf_api.py 输出的 UTF-8 中文会
    直接抛 UnicodeDecodeError（实测 `python ... | python` 这类管道必踩）。改为 import cf_api 直接调。
  - 输出统一用 UTF-8 写 stdout（pwsh 控制台可能显示成乱码，但 `chcp 65001` 或重定向到文件都正常）。

不打印任何密钥（cf_api.py 自己保证）。
"""
import datetime
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CF_API_DIR = os.path.join(ROOT, "docs", "agent")
CST = datetime.timezone(datetime.timedelta(hours=8))

try:  # 保证中文无论如何都能打出来
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, CF_API_DIR)
try:
    import cf_api  # noqa: E402
except Exception as exc:  # noqa: BLE001
    cf_api = None
    CF_API_ERR = exc


def today():
    return datetime.datetime.now(CST).date()


def section(title):
    print("\n== %s ==" % title)


def state():
    if cf_api is None:
        return None, "import cf_api 失败: %s" % CF_API_ERR
    status, body = cf_api.call("GET", "/chat-feed/api/state")
    if status != 200:
        return None, "HTTP %s: %s" % (status, (body or "")[:300])
    at = body.find("{")
    try:
        return json.loads(body[at:]), None
    except Exception as exc:  # noqa: BLE001
        return None, "解析 /state 失败: %s" % exc


def main():
    t = today()
    section("时间")
    print("now = %s (CST)" % datetime.datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"))

    section("插件 live /state")
    st, err = state()
    if st is None:
        print("读 /state 失败：%s" % err)
    else:
        print("quoteNo=%r quoteText=%r  ← 非空＝有他点的待发引用" % (
            st.get("quoteNo") or "", (st.get("quoteText") or "")[:60]))
        print("qdiag=%s" % json.dumps(st.get("qdiag"), ensure_ascii=False))
        print("sessionId=%s\nmainSessionId=%s" % (st.get("sessionId"), st.get("mainSessionId")))
        print("auto=%s autoTime=%s busy=%s lastCollectAt=%s saveOk=%s" % (
            st.get("auto"), st.get("autoTime"), st.get("busy"),
            st.get("lastCollectAt"), st.get("saveOk")))
        items = st.get("items") or []
        kinds = {}
        for it in items:
            kinds[it.get("kind")] = kinds.get(it.get("kind"), 0) + 1
        print("条目 %d 条：%s；日期 %s；done=%d" % (
            len(items), kinds, sorted({it.get("date") for it in items}),
            sum(1 for it in items if it.get("done"))))
        for it in items[:12]:
            print("  - [%s/%s] %s | %s" % (
                it.get("kind"), it.get("urgency"), (it.get("text") or "")[:46], it.get("date")))

    section("断档")
    days_dir = os.path.join(ROOT, "output", "days")
    dates = sorted({
        re.match(r"(\d{4}-\d{2}-\d{2})", n).group(1)
        for n in os.listdir(days_dir)
        if re.match(r"\d{4}-\d{2}-\d{2}", n)
    }) if os.path.isdir(days_dir) else []
    if not dates:
        print("output\\days 为空")
    else:
        last = datetime.date.fromisoformat(dates[-1])
        gap = (t - last).days
        print("最新 = %s；今天 = %s → 断档 %d 天%s" % (
            dates[-1], t.isoformat(), gap,
            "（>=2 天，按规格要报告，但不自行补做）" if gap >= 2 else ""))
        print("已有日期：%s" % ", ".join(dates[-8:]))

    section("微信 / 图片线")
    try:
        scripts = os.path.join(ROOT, "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import wx_images as W  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        print("import wx_images 失败：%s" % exc)
        W = None
    if W is not None:
        kv = W.find_kvcomm()
        login = W.wx_login_state(kv)
        code, meta = W.load_cached_key()
        lg = {True: "在线（kvcomm 已协商出密钥）", False: "**离线/未协商出密钥**（kvcomm 只有 code=0 占位）",
              None: "判不出来"}.get(login["loggedIn"], "?")
        print("状态 = %s" % lg)
        print("kvcomm 候选 = %s ｜ 缓存 code = %s ｜ 历史 code = %s"
              % (W.enumerate_codes(kv) if kv else [], code, list(W.HISTORICAL_CODES)))
        if not login["codeNegotiated"]:
            print("  → 客户端还没协商出密钥：**新消息/新图不会进来**（等登录）；图片线仍能用已验证的"
                  "本机 code 兜底跑，第 4/3j 步不会失败")
        print("  ⚠ 判据是 **kvcomm 的 code 段是否为 0**，不要只看 `last_uin`（已登录时它也可能是空）")
        print("  （细查 `python tools\\wx_status.py`；完整 JSON 落 `output\\logs\\_wx_status.json`）")

    section("产出一览")
    daily = os.path.join(ROOT, "output", "daily")
    if os.path.isdir(daily):
        print("output\\daily: %s" % (", ".join(sorted(os.listdir(daily))) or "(空)"))
    docs = os.path.join(ROOT, "docs")
    sums = sorted(n for n in os.listdir(docs) if n.startswith("summary_"))
    print("docs\\summary_*: %s" % (", ".join(sums[-5:]) or "(无)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
