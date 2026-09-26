# -*- coding: utf-8 -*-
"""vision_triage.py — 用**本地视觉小模型**给当天图片做分诊（daily_prep 第 3j 步）。

为什么（用户 2026-09-14："回顾整个工作流程，看看还有没有可以用本地小模型降本增效的地方"）：
  图片 token 是整条流程里最贵的；而"信息图/海报/二维码"又非读不可。本地 qwen3.5:9b 带 vision
  （实测 2.0 秒/张、全天 75 张 ≈ 2.5 分钟、零 API 花费），可以先把图**分诊**：
    · 判出"有行动项 / 有关键字段"的 → **强模型回看原图**（这是必须的，别省）
    · 判出"表情包/梗图/纯生活照/无信息截图"的 → 图**不进强模型**（省的就是这一大块）
  实测质量（2026-09-14，8 张样本人审）：两个 action 判断都命中真事（羽毛球队群二维码"7 天内有效"、
  算力券页面"余额与截止日期"）；我亲自核对一张判 noise 的文字图（谐音梗贯口）→ 判得对。

判据（"宁可疑不放过"）：
  need_review = action==true 或 fields 非空 或 **解析失败/超时**（fail-open：绝不当 noise 丢掉）
  只有 noise==true 且 action==false 且 fields 为空 → 才算"无信息"，图不进强模型

用法:  python tools\\vision_triage.py [YYYY-MM-DD] [--limit N] [--no-detail] [--detail-limit N]
产出:  output/days/<date>_vision.md   （① 需强模型回看 ② 判为无信息 ③ 自证统计）
       output/days/<date>_vision_detail.json （机器可读：粗判 + 细读的字段，供阶段 5 直接消费）

2026-09-17 升级（阶段 4 第二遍 · 细读遍）：
  粗判只回答"要不要回看"，而真正要进条目的是金额/截止/联系人/报名方式。所以对「需回看」的那几十张
  再用 `DETAIL_SYS` 跑一遍（用原图 2048 长边，看得清小字），把细节写进 md 与 json。
  实测单张 0.9 秒、0 元 ⇒ 之后**子代理不必再看图**（看图这步的云端成本归零）。用 `--no-detail` 可退回旧行为。

2026-09-18 升级（把"回语境"从提示词规则搬进脚本 ＋ 字段改名）：
  ① **每张图现在自带"它所在那条消息的前后文本"**（`ctx.before` / `ctx.after`：同群 ±15 分钟内、前 3 条后 3 条），
     写进 md 的「语境」行与 json 的 `ctx` 字段 ⇒ 阶段 5 **不必再自己去翻语料**。
     起因（2026-09-17 事故）：辅导员发了一张**他自己的**课程邮件截图、配文是「坏了 / 你给我留了多少算力呢」（在开玩笑），
     而阶段 5 只读结构化字段、**看不到配文** ⇒ 写成「明天你 9:50 去上产业生态学第一课」的待办。
     判据：**图上"写了什么"可信，图上"是什么意思"不可信** —— 归属只能靠上下文。
  ② 细读遍的 `sure` 改名 **`ocr_sure`**：它只代表"**字读得清**"，**不代表"意思对"**（旧名字容易被当成可信度用）。
"""
import base64
import io
import json
import os
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# 复用当天的语料 loader（与 units_day / split_day **同一套清洗口径**）—— "回语境"要用它。
#   为什么不在本脚本里自己读 <date>.jsonl：清洗口径一旦分叉，"语境"与"语料"就会不一致。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import split_day as sd  # noqa: E402
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3.5:9b"
SYS = (
    "你在帮一位清华大一新生看群聊里的图片。只看图说话，不要猜。\n"
    "只输出一个 JSON 对象，字段固定：\n"
    '{"what":"这张图是什么（≤20字）","action":true/false,"fields":["时间/地点/截止/联系人/金额/链接，没有就空数组"],'
    '"noise":true/false,"why":"判断依据（≤30字）"}\n'
    "action＝图里有没有需要他去做的具体事（报名/截止/填表/找谁/去哪/交材料/领东西）。\n"
    "noise＝表情包/梗图/纯风景/纯生活照/无信息截图。\n"
    "不要解释、不要输出 JSON 以外的任何字。"
)
# 细读遍（2026-09-17 新增，阶段 4 第二遍）：只对"需回看"的那几十张跑，把**细节**抠出来。
# 起因：粗判只回答"要不要回看"，而真正要进条目的是金额/截止/联系人/报名方式；
# 这一步做完，子代理就不必再看图（看图这步的云端成本归零）。
DETAIL_SYS = (
    "你在帮一位清华大一新生读群聊里的一张图，**只图里有的才算**，看不清就写「看不清」。\n"
    "只输出一个 JSON 对象，字段固定：\n"
    '{"title":"图的标题/主题（≤20字）","org":"发文单位或主办方（没有就空串）","deadline":"截止/活动时间（原文照抄，没有就空串）",'
    '"where":"地点或线上入口（没有就空串）","who":"联系人/联系方式/群（没有就空串）","money":"金额/费用/额度（没有就空串）",'
    '"how":"怎么参与：报名方式/需要的材料/要做什么（≤60字）","url":"图里的链接或二维码指向（看不清就空串）",'
    '"text":"图上最关键的一两句原文（≤80字，照抄）","ocr_sure":true/false}\n'
    "ocr_sure＝你是否真的**看清了字**（模糊/被截断/信息不全就 false）。\n"
    "**它只说明「字读得清」，不说明「意思对」** —— 归属一律以 ctx 里的前后文本为准。\n"
    "不要解释、不要输出 JSON 以外的任何字。"
)


def normalize(path, max_side=1568, quality=85):
    """把图统一成"安全 JPEG"再喂模型（2026-09-14 实测：11/75 报 HTTP 400，且**不是纯尺寸问题**
    —— 190KB 也失败、500KB 却成功 → 是格式变体（渐进式/CMYK/16bit 之类）。
    PIL 归一化（转 RGB + 限长边 + 重编码）能一次治掉，顺带降体量提速。失败则回退原图。"""
    try:
        from PIL import Image
        im = Image.open(path)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > max_side:
            k = max_side / float(max(w, h))
            im = im.resize((max(1, int(w * k)), max(1, int(h * k))))
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="cfvt_")
        os.close(fd)
        im.save(tmp, "JPEG", quality=quality)
        return tmp, True
    except Exception:
        return path, False


def resolve(date):
    p = os.path.join(HERE, "output", "days", "%s_images.json" % date)
    if not os.path.exists(p):
        return None
    j = json.loads(io.open(p, encoding="utf-8", errors="replace").read())
    out, seen = [], set()
    for it in (j if isinstance(j, list) else []):
        if not isinstance(it, dict):
            continue
        for rel in (it.get("path") or []):
            f = os.path.join(HERE, "output", "window", "images", rel.replace("/", os.sep))
            if os.path.exists(f) and f not in seen:
                seen.add(f)
                out.append({"file": f, "chat": it.get("chat_name") or "", "ts": it.get("ts") or 0,
                            "sender": it.get("sender") or ""})
    out.sort(key=lambda x: x["ts"])
    return out


# ---- 「回语境」（2026-09-18 从提示词规则搬进脚本）--------------------------------------------
# 判据：**图上"写了什么"可信，图上"是什么意思"不可信** —— 归属只能靠同一条消息的前后文本。
# 为什么搬进脚本：写进提示词的规则要靠读的人自觉执行；写进产物则阶段 5 **不得不**看到它。
CTX_WINDOW_SEC = 900      # 同群 ±15 分钟
CTX_BEFORE = 3            # 图前最多 3 条
CTX_AFTER = 3             # 图后最多 3 条
CTX_TEXT_MAX = 200        # 每条语境截断（语境是判归属用的，不需要全文）


def cst(ts):
    """秒级时间戳 → CST 的 MM-DD HH:MM（与 _msg_ctx.mjs / 语料视图同口径）。"""
    try:
        return time.strftime("%m-%d %H:%M", time.gmtime(int(ts) + 8 * 3600))
    except Exception:  # noqa: BLE001
        return "?"


def group_rows(rows):
    by = {}
    for r in rows:
        by.setdefault(r["chat"], []).append(r)
    return by


def pick_chat(by, chat):
    """群名对不上时用包含关系兜底（图片索引里的 chat_name 与语料里的 chat 未必逐字相同）。"""
    if chat in by:
        return chat
    for k in by:
        if chat and (chat in k or k in chat):
            return k
    return None


def context_for(by, chat, ts):
    """这张图所在那条消息的前后文本；取不到就**显式标缺失**，让下游知道"这里是猜的"。"""
    key = pick_chat(by, chat)
    if not key:
        return {"before": [], "after": [], "missing": "chat-not-in-corpus"}

    def fmt(r):
        return {"ts": r["ts"], "who": r["who"], "text": r["text"][:CTX_TEXT_MAX]}

    near = [r for r in by[key] if abs(r["ts"] - ts) <= CTX_WINDOW_SEC]
    return {"before": [fmt(r) for r in near if r["ts"] <= ts][-CTX_BEFORE:],
            "after": [fmt(r) for r in near if r["ts"] > ts][:CTX_AFTER]}


def ask(path, timeout=300, sysmsg=SYS, max_side=1568, num_predict=300):
    send, _tmp = normalize(path, max_side=max_side)
    try:
        b64 = base64.b64encode(io.open(send, "rb").read()).decode()
    finally:
        if _tmp:
            try:
                os.remove(send)
            except Exception:
                pass
    payload = {"model": MODEL, "stream": False, "think": False,
               "options": {"temperature": 0, "num_predict": num_predict},
               "messages": [{"role": "system", "content": sysmsg},
                            {"role": "user", "content": "看这张图。", "images": [b64]}]}
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    dt = time.time() - t0
    txt = ((j.get("message") or {}).get("content") or "").strip()
    m = re.search(r"\{[\s\S]*\}", txt)
    if not m:
        return None, dt, txt[:160]
    try:
        return json.loads(m.group(0)), dt, txt[:160]
    except Exception:
        return None, dt, txt[:160]


def main():
    date = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else \
        time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600))
    try:
        __import__("datetime").datetime.strptime(date, "%Y-%m-%d")
    except Exception:
        raise SystemExit("vision_triage.py: 日期参数必须是 YYYY-MM-DD，收到 %r" % (date,))
    lim = 0
    if "--limit" in sys.argv:
        lim = int(sys.argv[sys.argv.index("--limit") + 1])
    no_detail = "--no-detail" in sys.argv          # 细读遍默认**开**（阶段 4 第二遍）
    dlim = 0
    if "--detail-limit" in sys.argv:
        dlim = int(sys.argv[sys.argv.index("--detail-limit") + 1])
    items = resolve(date)
    if items is None:
        print("缺 output/days/%s_images.json（先跑 4-图片索引）" % date)
        return 1
    if lim:
        items = items[:lim]
    # ---- 回语境（在跑视觉模型之前就配好；语料缺失时**显式警告**，别让它静默退化成"没有语境"）----
    #   `min_len=2`：语境要**短消息**。实测教训 —— "坏了"（2 字）会被默认的 `len(t) < 4` 静默滤掉，
    #   而它正是"这张图是开玩笑发的"的一半信号（另半句 14 字那句默认能过）。
    corpus = sd.load(date, min_len=2)
    by_chat = group_rows(corpus) if corpus else {}
    if corpus is None:
        print("注意：缺 output/days/%s.jsonl ⇒ 本轮的图**没有语境**（ctx 为空）⇒ 归属不许靠猜" % date)
    for it in items:
        it["ctx"] = context_for(by_chat, it["chat"], it["ts"])
    n_ctx = sum(1 for it in items if (it["ctx"].get("before") or it["ctx"].get("after")))
    review, noise, fail, tot = [], [], [], 0.0
    for i, it in enumerate(items, 1):
        obj, dt, raw = None, 0.0, ""
        for attempt in (1, 2):                       # 400/超时重试一次（个别 JPEG 变体会 400）
            try:
                obj, dt, raw = ask(it["file"])
                tot += dt
                if obj:
                    break
            except Exception as e:
                raw = "ERR:%s" % e
                if attempt == 1:
                    time.sleep(0.5)
        it["dt"] = round(dt, 1)
        it["obj"] = obj
        it["raw"] = raw
        if not obj:
            fail.append(it)                          # fail-open：标"需人工看"，绝不当 noise
        elif obj.get("action") or (obj.get("fields") or []):
            review.append(it)
        elif obj.get("noise"):
            noise.append(it)
        else:
            review.append(it)                        # 既非 noise 又无 action → 保守当"需回看"
        if i % 10 == 0:
            print("  %d/%d ..." % (i, len(items)))

    # ---- 细读遍（阶段 4 第二遍）：只对"需回看"的几十张抠细节（金额/截止/联系人/报名方式）----
    # 做完这步，**子代理不必再看图**（看图这步的云端成本归零）。
    d_targets = [] if no_detail else list(review + fail)
    if dlim:
        d_targets = d_targets[:dlim]
    t_d = 0.0
    for k, it in enumerate(d_targets, 1):
        obj, dt, raw = None, 0.0, ""
        for attempt in (1, 2):
            try:
                obj, dt, raw = ask(it["file"], sysmsg=DETAIL_SYS, max_side=2048, num_predict=400)
                t_d += dt
                if obj:
                    break
            except Exception as e:                   # noqa: BLE001
                raw = "ERR:%s" % e
                if attempt == 1:
                    time.sleep(0.5)
        it["detail"] = obj
        it["detail_dt"] = round(dt, 1)
        it["detail_raw"] = raw
        if k % 10 == 0:
            print("  detail %d/%d ..." % (k, len(d_targets)))
    n_detail = sum(1 for it in d_targets if it.get("detail"))

    L = ["# %s 图片分诊（本地视觉 qwen3.5:9b）" % date, "",
         "> 共 %d 张 ｜ **需强模型回看 %d** ｜ 判为无信息 %d ｜ 解析失败(fail-open) %d ｜ 总 %.0fs（均 %.1fs/张）"
         % (len(items), len(review), len(noise), len(fail), tot, tot / max(1, len(items))), "",
         "> **细读遍**（阶段 4 第二遍）：对「需回看」的 %d 张再抠一次细节，成功 %d 张、%.0fs（均 %.1fs/张）"
         % (len(d_targets), n_detail, t_d, t_d / max(1, len(d_targets))),
         "> 用法：**细节以「细读」那行为准**（金额/截止/联系人/报名方式都在里面）；判不准的仍按「必须回看原图」处理。"
         if not no_detail else "> 用法：强模型**只看「一、需回看」里那 %d 张的图**（本次 --no-detail，未跑细读遍）。"
         % len(review), "",
         "## 一、需强模型回看（action / 有字段 / 解析失败）", ""]
    for it in review + fail:
        o = it["obj"] or {}
        tag = "FAIL" if not it["obj"] else ("action" if o.get("action") else ("fields" if o.get("fields") else "info"))
        L.append("- `%s` ｜ %s ｜ %.1fs ｜ **%s**" % (os.path.relpath(it["file"], HERE), it["chat"], it["dt"], tag))
        L.append("  - 本地判断：%s%s" % (json.dumps(o, ensure_ascii=False) if o else ("解析失败：" + it["raw"]),
                                      "  ← **必须回看原图**" if (not o or o.get("action") or (not o.get("action") and (o.get("fields") or [])) or (not o.get("noise") and not o.get("action"))) else ""))
        d = it.get("detail")
        if d:
            L.append("  - **细读**：%s" % json.dumps(d, ensure_ascii=False))
        elif not no_detail:
            L.append("  - **细读失败**（图还是要人看）：%s" % str(it.get("detail_raw"))[:120])
        # 语境＝归属判据（2026-09-18 新增）：图上"写了什么"可信，"是什么意思"不可信。
        c = it.get("ctx") or {}
        if c.get("before") or c.get("after"):
            L.append("  - **语境**（**归属只认这里**，别只看图）：")
            for r in (c.get("before") or []):
                L.append("    - 前 %s %s：%s" % (cst(r["ts"]), r["who"], r["text"]))
            for r in (c.get("after") or []):
                L.append("    - 后 %s %s：%s" % (cst(r["ts"]), r["who"], r["text"]))
        else:
            L.append("  - **语境缺失**（%s）⇒ 归属不许靠猜，宁可标「待人工确认」" % (c.get("missing") or "相邻无文本"))
    L += ["", "## 二、判为无信息（%d 张，不必进强模型）" % len(noise), ""]
    for it in noise:
        o = it["obj"] or {}
        L.append("- `%s` ｜ %s ｜ %s" % (os.path.relpath(it["file"], HERE), o.get("what", ""), o.get("why", "")))
    L += ["", "## 三、自证", "",
          "| 项 | 值 |", "|---|---|",
          "| 落盘图（索引里存在磁盘上的） | %d |" % len(items),
          "| 需回看 | %d |" % len(review),
          "| 判无信息 | %d |" % len(noise),
          "| 解析失败（fail-open 已并入「需回看」） | %d |" % len(fail),
          "| 总耗时（粗判） | %.0f 秒（均 %.1f 秒/张） |" % (tot, tot / max(1, len(items))),
          "| **细读遍** | %d/%d 张成功，%.0f 秒（均 %.1f 秒/张） |"
          % (n_detail, len(d_targets), t_d, t_d / max(1, len(d_targets))),
          "| 模型 | %s（本机 Ollama，零 API 花费） |" % MODEL,
          "| **带语境**（回语境是归属判据） | %d/%d 张；缺 %d 张 |" % (n_ctx, len(items), len(items) - n_ctx)]
    out = os.path.join(HERE, "output", "days", "%s_vision.md" % date)
    io.open(out, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
    # 机器可读版：阶段 5 直接吃这个，不必解析 md、也不必再看图
    jpath = os.path.join(HERE, "output", "days", "%s_vision_detail.json" % date)
    pack = {"date": date, "model": MODEL,
            "stats": {"images": len(items), "review": len(review), "noise": len(noise), "fail": len(fail),
                      "detail_ok": n_detail, "detail_tried": len(d_targets),
                      "ctx_ok": n_ctx, "ctx_missing": len(items) - n_ctx,
                      "triage_sec": round(tot, 1), "detail_sec": round(t_d, 1)},
            "review": [{"file": os.path.relpath(it["file"], HERE).replace("\\", "/"), "chat": it["chat"],
                        "ts": it["ts"], "sender": it["sender"], "triage": it["obj"], "detail": it.get("detail"),
                        # 归属判据：阶段 5 **必须**先看这里，再看图里写了什么（2026-09-18）
                        "ctx": it.get("ctx")}
                       for it in review + fail],
            "noise": [{"file": os.path.relpath(it["file"], HERE).replace("\\", "/"), "chat": it["chat"],
                       "what": (it["obj"] or {}).get("what", "")} for it in noise]}
    io.open(jpath, "w", encoding="utf-8", newline="\n").write(json.dumps(pack, ensure_ascii=False, indent=1))
    print("REVIEW %d | noise %d | fail %d | detail %d/%d | total %.0fs | -> %s"
          % (len(review), len(noise), len(fail), n_detail, len(d_targets), tot + t_d, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
