# -*- coding: utf-8 -*-
"""wx_status.py — 微信/图片线的一行状态（主 agent 每轮判活用，只读）。

用法:
    python tools\\wx_status.py            # 人类可读摘要（ASCII 安全）
    python tools\\wx_status.py --json      # 只输出 JSON

回答的问题（"图片线为什么停/能不能跑"）：
  1. 微信进程在不在（Weixin / WeChatAppEx）；
  2. 微信**在线/可用状态**（用户 2026-09-15 提醒："微信还没有登陆，你要判断这种情况"）——
     **主判据＝kvcomm 里 `key*` 文件名的 code 段是否为 0**（0＝客户端还没协商出密钥）。
     **不要只看 `kvcomm\\config.ini` 的 `last_uin`**：第一版就是只看它，而 20:02 实测
     **已登录时 `last_uin` 依然是空的** → 那个判据被反例证伪（`last_uin` 现在只作参考值）；
  3. 图片密钥从哪一级解出来的（cached / kvcomm / historical），缓存文件内容；
  4. 附件库最新活动时间（登录着的话消息在走，这个时间应该是"刚刚"）；
  5. 今天的 `output\\days\\<today>.jsonl` 在不在。

**背景（2026-09-15 的坑）**：微信未登录时 kvcomm 只剩 `key_0_<idkey_clientversion>_…` 这种占位
（code 段是 0），纯靠扫 kvcomm 会得出"解不出图片密钥"的**假结论**、把第 4 步显示成脚本 FAILED。
真相是本机 code 不随登录态变化，用历史验证过的 code 照样能解开当天的图。

全部响应落 `output\\logs\\_wx_status.json`（UTF-8，含中文），终端只打 ASCII 安全摘要。
"""
import datetime
import io
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
CST = datetime.timezone(datetime.timedelta(hours=8))
OUT_J = os.path.join(ROOT, "output", "logs", "_wx_status.json")


def procs():
    """微信相关进程（tasklist 走管道失败就返回 None，不因此报错）。"""
    try:
        p = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        rows = []
        for line in (p.stdout or "").splitlines():
            parts = [x.strip('"') for x in line.split('","')]
            if parts and parts[0].lower().startswith(("weixin", "wechat")):
                rows.append({"name": parts[0], "pid": parts[1] if len(parts) > 1 else ""})
        return rows
    except Exception:  # noqa: BLE001
        return None


def newest_attach():
    try:
        import wx_images as W  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    attach = os.path.join(W.WX_ROOT, "msg", "attach")
    best = (0.0, "")
    if not os.path.isdir(attach):
        return {"error": "attach 目录不存在：%s" % attach}
    for d, _dirs, files in os.walk(attach):
        for fn in files:
            p = os.path.join(d, fn)
            try:
                mt = os.stat(p).st_mtime
            except OSError:
                continue
            if mt > best[0]:
                best = (mt, p)
    return {"ts": best[0], "at": fmt(best[0]), "path": best[1]}


def fmt(ts):
    try:
        return datetime.datetime.fromtimestamp(ts, CST).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return ""


def main():
    want_json = "--json" in sys.argv
    info = {"at": datetime.datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")}

    info["processes"] = procs()
    try:
        import wx_images as W  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        info["error"] = "import wx_images 失败：%s" % e
        print(json.dumps(info, ensure_ascii=False, indent=1))
        return 1

    kv = W.find_kvcomm()
    login = W.wx_login_state(kv)
    info["kvcomm"] = kv
    info["loggedIn"] = login["loggedIn"]
    info["codeNegotiated"] = login["codeNegotiated"]
    info["lastUinEmpty"] = not login["lastUin"]
    info["idkeyClientVersion"] = login["idkeyClientVersion"]
    info["kvcommCandidates"] = W.enumerate_codes(kv) if kv else []
    info["historicalCodes"] = list(W.HISTORICAL_CODES)
    code, meta = W.load_cached_key()
    info["cachedCode"] = code
    info["cachedMeta"] = meta

    # 不真去解密（那要扫全库）；只报"密钥可用性"的三级候选清单
    info["keySources"] = {
        "cached": bool(code),
        "kvcomm": bool(info["kvcommCandidates"]),
        "historical": bool(W.HISTORICAL_CODES),
    }

    info["newestAttach"] = newest_attach()
    today = datetime.datetime.now(CST).strftime("%Y-%m-%d")
    jl = os.path.join(ROOT, "output", "days", "%s.jsonl" % today)
    info["today"] = today
    info["todayJsonl"] = {"exists": os.path.exists(jl), "path": jl}

    lines = None
    try:
        with open(OUT_J, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=1)
    except OSError:
        pass

    if want_json:
        print(json.dumps(info, ensure_ascii=False, indent=1))
        return 0

    # ASCII-safe one-liner summary (中文一律去文件里读)
    ps = info["processes"]
    ps_txt = "tasklist-failed" if ps is None else ("%d proc" % len(ps) if ps else "NOT RUNNING")
    lg = info["loggedIn"]
    lg_txt = "ONLINE" if lg is True else ("OFFLINE" if lg is False else "UNKNOWN")
    na = info["newestAttach"]
    print("wechat_proc=%s | state=%s | code_negotiated=%s | last_uin_empty=%s | key_cached=%s"
          % (ps_txt, lg_txt, info["codeNegotiated"], info["lastUinEmpty"], bool(code)))
    print("kvcomm_candidates=%s | historical=%s" % (info["kvcommCandidates"], list(W.HISTORICAL_CODES)))
    print("newest_attach=%s | today_jsonl=%s" % (na.get("at") or na.get("error"), info["todayJsonl"]["exists"]))
    if lg is False:
        print("=> WeChat has NOT negotiated a key (kvcomm holds only the code=0 placeholder).")
        print("   The image line can still run via the verified local code, but no NEW images/messages")
        print("   arrive until login. Full text line is unaffected.")
    elif not info["codeNegotiated"]:
        print("=> last_uin is non-empty but kvcomm has not negotiated a key yet (mid-login?).")
    print("   NOTE: an empty last_uin does NOT mean 'not logged in' - judge by code_negotiated")
    print("   (2026-09-15 20:02 counterexample: logged in with last_uin empty).")
    print("full json (UTF-8, has Chinese): %s" % OUT_J)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
