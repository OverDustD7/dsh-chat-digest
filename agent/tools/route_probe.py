# -*- coding: utf-8 -*-
r"""跑前先探"清华免费网关（THU）还通不通" —— 通就用 THU，不通才回 paratera（用户 2026-09-17 定的规矩）。

为什么要它：用户 2026-09-17 明确「每次跑之前先检测 THU 连通性，如果可以用 THU 就用 THU，不可以才用 paratera」。
背景事实（实测）：THU（provider `deepseek`，`<部署方的免费网关>`）**免费但很不稳定** ——
09-17 才通、前一天不通；paratera 稳定但走 DeepSeek 官方高峰价（干净一轮 ≈ ¥2–3）。
**还有一个硬差异必须知道**：THU 的 `contextWindow` 只有 **200,000**，paratera 是 **1,000,000**（差 5 倍）——
所以"能用 THU"只解决钱的问题，**长上下文会缩水**（`ctxRatio=0.5` 时 200k 会在 100k 就触发自动刷新）。

退出码（沿用"上游缺失单独报"的纪律）：**0 = THU 可用** ｜ **3 = THU 不可用（该走 paratera）** ｜ 1 = 探测本身出错。

用法：
    ..\venv\Scripts\python.exe tools\route_probe.py                 # 探两条线 + 给结论（人读）
    ..\venv\Scripts\python.exe tools\route_probe.py --json          # 机器读（写 output\window\route_probe.json）
    ..\venv\Scripts\python.exe tools\route_probe.py --ensure        # 探 + 把 agent-default-model 对齐到可用那条（带 .bak）
    ..\venv\Scripts\python.exe tools\route_probe.py --set-default paratera
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "output", "window")
DSH = os.path.join(os.path.expanduser("~"), ".dsh")
CRED = os.path.join(DSH, ".credentials.yaml")
SETTINGS = os.path.join(DSH, "settings.yaml")
TZ = dt.timezone(dt.timedelta(hours=8))

# 线路表：**供应商/模型/入口一律从环境变量取**（本工具是给"部署方自己那条线"用的，
#   包内不许写死任何人的网关地址与模型名）。插件自己的 `routes` 配置才是权威来源，
#   见 profile 的 `cordis.patch.yml`；这里的默认值只用来在命令行上临时试。
ROUTES = {
    "thu": {"provider": "deepseek", "model": os.environ.get("THU_MODEL", ""), "keyEnv": os.environ.get("THU_KEY_ENV", "THU_API_KEY"),
            "base": os.environ.get("THU_BASE", ""), "ctx": 200000, "price": "免费",
            "note": "免费线；**能不能读图、窗口多大由部署方自己确认**"},
    "paratera": {"provider": "paratera", "model": os.environ.get("PARATERA_MODEL", ""), "keyEnv": "PARATERA_API_KEY",
                 "base": os.environ.get("PARATERA_BASE", ""), "ctx": 1000000, "price": "付费线",
                 "note": "付费线；窗口与读图能力由部署方自己确认"},
}


def load_cred(name):
    """从 ~/.dsh/.credentials.yaml 取一个键。值可能是折行（行尾反斜杠）→ 拼回去再剥引号。"""
    if not os.path.exists(CRED):
        return None
    lines = io.open(CRED, encoding="utf-8", errors="replace").read().split("\n")
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*%s\s*:\s*(.*)$" % re.escape(name), ln)
        if not m:
            continue
        val = m.group(1).strip()
        j = i
        while val.endswith("\\") and j + 1 < len(lines):      # YAML 折行
            val = val[:-1] + lines[j + 1].strip()
            j += 1
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        return val or None
    return None


def http(method, url, key, body=None, timeout=10):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/json")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(4000).decode("utf-8", "replace")
            return {"ok": True, "status": r.status, "ms": int((time.time() - t0) * 1000), "body": raw[:400]}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "ms": int((time.time() - t0) * 1000),
                "body": (e.read(400).decode("utf-8", "replace") if hasattr(e, "read") else ""), "err": "HTTP %s" % e.code}
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "status": 0, "ms": int((time.time() - t0) * 1000), "err": str(e)[:200]}


def probe(route):
    """先试 /models（便宜、不花 token）；404/405 就退回"1 token 对话"（最硬的可用性证据）。"""
    cfg = ROUTES[route]
    key = load_cred(cfg["keyEnv"])
    out = {"route": route, "provider": cfg["provider"], "model": cfg["model"], "base": cfg["base"],
           "ctx": cfg["ctx"], "keyFound": bool(key), "price": cfg["price"], "note": cfg["note"]}
    if not key:
        out.update(ok=False, how="none", detail="凭据文件里没有 %s" % cfg["keyEnv"])
        return out
    m = http("GET", cfg["base"] + "/models", key)
    if m.get("ok"):
        out.update(ok=True, how="GET /models", ms=m["ms"], detail="HTTP %s" % m["status"])
        return out
    if m.get("status") in (404, 405, 400):                    # 网关可能没实现 /models
        c = http("POST", cfg["base"] + "/chat/completions", key,
                 {"model": cfg["model"], "messages": [{"role": "user", "content": "ping"}],
                  "max_tokens": 1, "stream": False}, timeout=25)
        if c.get("ok"):
            out.update(ok=True, how="POST /chat/completions(1 token)", ms=c["ms"],
                       detail="HTTP %s" % c["status"])
        else:
            out.update(ok=False, how="POST /chat/completions", ms=c.get("ms"),
                       detail="%s ｜ %s" % (c.get("err"), (c.get("body") or "")[:160]))
        return out
    out.update(ok=False, how="GET /models", ms=m.get("ms"),
               detail="%s ｜ %s" % (m.get("err"), (m.get("body") or "")[:160]))
    return out


def set_default(route):
    """把 settings.yaml 的 agent-default-model 对齐到这条路线（**先备份 .bak，不删任何东西**）。
    为什么需要：会话的路由在**建会话时**就定死了（配置改了不影响已存在会话），所以"切路线"＝改默认值 + 刷新会话。"""
    cfg = ROUTES[route]
    if not os.path.exists(SETTINGS):
        return {"ok": False, "err": "没有 %s" % SETTINGS}
    txt = io.open(SETTINGS, encoding="utf-8").read()
    bak = SETTINGS + ".bak"
    io.open(bak, "w", encoding="utf-8", newline="\n").write(txt)
    new = re.sub(r"(?ms)^agent-default-model:\n(?:[ \t]+.*\n)*",
                 "agent-default-model:\n  provider: %s\n  model: %s\n  reasoningEffort: high\n" % (cfg["provider"], cfg["model"]),
                 txt, count=1)
    if new == txt:
        return {"ok": False, "err": "没匹配到 agent-default-model 段"}
    io.open(SETTINGS, "w", encoding="utf-8", newline="\n").write(new)
    m = re.search(r"(?ms)^agent-default-model:\n(?:[ \t]+.*\n)*", new)
    return {"ok": True, "backup": bak, "now": m.group(0).strip() if m else ""}


def ctx_now():
    """读 `/state`：① 会话当前**真实上下文占用**（ctxTokens）② **两个会话槽**与当前选中的路线。
    读不到就返回 {"err": …}（不阻断探测，只是这一维不判）。"""
    try:
        sys.path.insert(0, os.path.join(HERE, "docs", "agent"))
        import cf_api  # noqa: E402
        st, body = cf_api.call("GET", "/chat-feed/api/state")
        if st != 200:
            return {"err": "HTTP %s" % st}
        d = json.loads(body)
        return {"tokens": int(d.get("ctxTokens") or 0), "window": int(d.get("ctxWindow") or 0),
                "limit": int(d.get("ctxLimit") or 0), "pct": d.get("ctxPct"),
                "mainSessionId": str(d.get("mainSessionId") or ""),
                "routePick": str(d.get("routePick") or ""), "ctxRatioThu": d.get("ctxRatioThu"),
                "sessThu": str(d.get("sessThu") or ""), "sessParatera": str(d.get("sessParatera") or ""),
                "routeNeedsConfirm": bool(d.get("routeNeedsConfirm")),
                "routeProbe": d.get("routeProbe") or None}
    except Exception as e:                                    # noqa: BLE001
        return {"err": str(e)[:120]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ensure", action="store_true", help="探完把 agent-default-model 对齐到可用那条"
                                                          "（**回退 paratera 必须在 --yes 下才动**：付费要用户点头）")
    ap.add_argument("--yes", action="store_true", help="用户已同意付费回退 paratera（只在 --ensure 时有意义）")
    ap.add_argument("--set-default", choices=sorted(ROUTES))
    ap.add_argument("--thu-only", action="store_true", help="只探 THU（快，给「跑前判活」用）")
    a = ap.parse_args()
    now = dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

    if a.set_default:
        r = set_default(a.set_default)
        print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else
              ("已写入 agent-default-model → %s\n%s" % (a.set_default, r.get("now") or r.get("err"))))
        return 0 if r.get("ok") else 1

    routes = ["thu"] if a.thu_only else ["thu", "paratera"]
    res = {r: probe(r) for r in routes}
    thu = res["thu"]
    usable = bool(thu.get("ok"))
    # **第二道判据：上下文放不放得下**（2026-09-17 实测教训）——
    #   现在架构是"**两个会话**"（`sessThu` 新建、`sessParatera` 是原来那个长会话）⇒ THU 那个槽的上下文是新的、必然放得下；
    #   这里算的 `fits` 用的是**当前活跃会话**的用量，只作参考：它大说明"你别把**这个**会话切去 THU"，
    #   而正确做法是**切到 THU 那个独立会话**（`POST /chat-feed/api/route-pick {"route":"thu"}`），不是把长会话改指过去。
    cx = ctx_now()
    HEADROOM = 50000
    fits = None
    if "err" not in cx:
        fits = (cx.get("tokens", 0) + HEADROOM) <= ROUTES["thu"]["ctx"]
    pick = (cx.get("routePick") if "err" not in cx else "") or ""
    slots = ("当前 routePick=%s ｜ sessThu=%s ｜ sessParatera=%s"
             % (pick or '(未知)', (cx.get("sessThu") or '(无)')[:20], (cx.get("sessParatera") or '(无)')[:20])) \
            if "err" not in cx else ("读不到 /state：%s" % cx.get("err"))
    if usable:
        verdict = ("THU 可用 ⇒ **走 THU 那个会话**（`route-pick thu`，免费；它窗口 200k 但**是新会话**，放得下；"
                   "刷新阈值 0.9）。当前活跃会话用量 %s tokens%s —— **不要把这个长会话改指去 THU**，要用独立会话。%s"
                   % (cx.get("tokens") if "err" not in cx else '?',
                      "" if fits is not False else "（已超过 200k，改指会溢出）", slots))
    else:
        verdict = ("THU 不可用 ⇒ **先问用户**是否就用 paratera（%s），他同意才 `POST /chat-feed/api/route-pick {\"route\":\"paratera\"}`。%s"
                   % (ROUTES["paratera"]["price"], slots))
    pack = {"checkedAt": now, "thuUsable": usable, "ctx": cx, "thuFits": fits, "routePick": pick, "slots": slots,
            # 注意别在这里再写一个 "preferred"（2026-09-17 踩过：重复键把上面这行覆盖掉，于是"超窗口"也报 thu）
            "preferred": "thu" if usable else "paratera",
            "verdict": verdict,
            "needsUserConfirm": (not usable),          # 回退到付费线路**必须用户点头**（用户 2026-09-17 明确）
            "routes": res}
    if os.path.isdir(OUT):
        io.open(os.path.join(OUT, "route_probe.json"), "w", encoding="utf-8", newline="\n").write(
            json.dumps(pack, ensure_ascii=False, indent=1))

    if a.ensure:
        want = ROUTES[pack["preferred"]]
        if pack["preferred"] == "paratera" and not a.yes:
            # 付费线路**不许自动切**（用户 2026-09-17：THU 不通要先问他）
            pack["ensure"] = "**未自动切换**：THU 不通，回退 paratera 是付费线路，必须先 ask_user_question 问用户；他同意后再跑 --ensure --yes"
        else:
            cur = ""
            try:
                m = re.search(r"(?ms)^agent-default-model:\n(?:[ \t]+.*\n)*", io.open(SETTINGS, encoding="utf-8").read())
                cur = m.group(0) if m else ""
            except Exception:                                 # noqa: BLE001
                pass
            if ("provider: %s" % want["provider"]) in cur:
                pack["ensure"] = "已经是 %s，无需改" % pack["preferred"]
            else:
                pack["ensure"] = set_default(pack["preferred"])

    if a.json:
        print(json.dumps(pack, ensure_ascii=False, indent=1))
    else:
        print("== 跑前路由探测 %s ==" % now)
        for r, v in res.items():
            print("  %-9s %s  ｜ %-28s ｜ %sms ｜ key=%s ｜ %s"
                  % (r, "可用" if v.get("ok") else "不可用", v.get("how"), v.get("ms"),
                     "有" if v.get("keyFound") else "**缺**", (v.get("detail") or "")[:90]))
        print("\n结论：%s" % verdict)
        if pack.get("needsUserConfirm"):
            print("**这一步要停下来问他**：`ask_user_question`「清华网关现在不通，这一轮要不要改走 paratera（付费，约 ¥2–3/轮）？」"
                  "——他同意后才 `POST /chat-feed/api/route` {\"provider\":\"<供应商>\",\"model\":\"<模型>\"}；"
                  "不同意就**这一轮不跑**或只做 0 元的本地部分。")
        print("架构：**两个常驻会话**（`sessThu` 免费·200k / `sessParatera` 付费·1M）—— 按需切换用哪个，"
              "**不用在会话内改指向**（那会撞窗口），也不要 /rotate。切会话：`POST /chat-feed/api/route-pick {\"route\":\"thu\"|\"paratera\"}`。")
        print("（`POST /chat-feed/api/route` 的会话内 selectModel 仍可用、已实测，但用户 2026-09-17 已改成两个会话的方案，日常不用它。）")
        if pack.get("ensure"):
            print("--ensure：%s" % (pack["ensure"] if isinstance(pack["ensure"], str) else json.dumps(pack["ensure"], ensure_ascii=False)))
        print("落盘：output\\window\\route_probe.json")
    return 0 if usable else 3


if __name__ == "__main__":
    raise SystemExit(main())