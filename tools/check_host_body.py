# -*- coding: utf-8 -*-
"""check_host_body.py — 校验 `lib\\host-body.txt`（Host 权威源码）现在是**合法函数体**。

为什么必须做（2026-09-13 踩过两次）：加载器是 `new Function('CFG', bodyText)(cfg)`，它只吃**函数体**；
一旦整份带 `async function` 头的文件被写进 body，`/chat-feed/*` 会**全部 404**。
所以每次改完 body，按这个顺序自检：
  ① 从磁盘复读（不信内存）② 不以 `async function` 开头 ③ 以 `};` 结尾
  ④ 包成 `function __cfBody(){ … }` 后 `node --check` 必须过
  ⑤ 关键片段仍在（防手滑删段）

用法: python check_host_body.py
"""
import io
import os
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
TOOLS = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(TOOLS)                          # 包根（tools/ 的上一层）
BODY = os.path.join(PKG, "lib", "host-body.txt")
# 生成的检查副本**必须写到仓库外**（A26，2026-09-25）：原先写在 tools/ 下，而那个文件是**已入库**的
# ⇒ 每跑一次自检就把仓库弄脏一次（和管线探针写 fixtures/ 是同一个毛病：自检不该改被检查的仓库）。
CHK = os.path.join(tempfile.mkdtemp(prefix="cf-bodycheck-"), "_host_body_check.js")

body = io.open(BODY, encoding="utf-8").read()
fails = []


def check(name, good, extra=""):
    print(("OK   " if good else "FAIL ") + name + (("  " + extra) if extra else ""))
    if not good:
        fails.append(name)


check("不以 async function 开头", not body.lstrip().startswith("async function"),
      "head=%r" % body[:40])
check("以 }; 结尾", body.rstrip().endswith("};"), "tail=%r" % body.rstrip()[-30:])
check("没有 const apply 之外的顶层包装", body.count("async function") == 0)

# 关键片段（本轮改动点 + 不能丢的路由）
for frag in ("const DIR =", "const WAKE_TEXT =", "apply(ctx)",
             "routeOk.state", "routeOk.items", "routeOk.rotate", "routeOk.collect",
             "triggerRound", "checkBusy", "roundPrompt", "cstDay",
 
             # 2026-09-17：提炼改成"本机先初提、主 agent 成稿"（旧口径"提炼派子代理"已废）
             #   —— 这三条是主 agent 新流程的入口/自检/回原文核，丢一条它就会退回 ¥27 的旧打法
 
             # 2026-09-17：跑前探路由（THU 通就用 THU、不通要问过他才能回退付费的 paratera）
              "先问",
             # 2026-09-17：**会话内换模型**（DSH selectModel）—— 不再让用户去刷新会话
             "routeOk.route = route", "selectModel", "POST /chat-feed/api/route", 
             # 2026-09-17 晚：用户定案改成**两个常驻会话按需切换**（THU 一个 / paratera 一个）+ THU 刷新阈值 0.9
             "routeOk.routePick = route", "routeOk.routeProbe = route", "pickRoute", "pluginProbe",
             "ensureBothSlots", "slotsInitAt", "routeOk.routeAdopt = route", "routeOfActive", "wsSessionIds", "activeRoute",
             "SLOTS_VER", "adoptRouteByTitle", "slotsInitVer", "routeProbe: S.routeProbe", "sessThu: S.sessThu ||",
             # 2026-09-17 晚：网关不通改成**面板策略**（默认不跑）+ 手动补跑，**不再弹 question 卡片**
             "routeOk.gwPolicy = route", "routeOk.gwRun = route", "gwPolicy", "fireRound", "forceRoute", "gwRunMode",
             # 2026-09-17 白天（用户要求）：右栏**网关状态条删掉**，「获取」改成下拉菜单
             #   ＝选提供商 → 现场探测它 → 通了才触发 / 不通就把按钮闪红「获取失败」且**不动采集指针**
             #   宿主侧三处：pluginProbe(want) 只探指定线路 ｜ /collect {route} ｜ triggerRound({probeRoute})
             "PROBE_URL", "const only = (typeof ROUTES", "const ROUTES = (Array.isArray(CF.routes)", "const routeSlotKey = (route)", "const ctxRatioOf =", "const routeDef =", "probeRoute", "routeDown", "'menu:' + only",
             # 2026-09-17 下午：**别把槽的标题抹平**（adoptRouteByTitle 靠标题后缀认回会话；
             #   被 ensureSession 无条件改名成通用标题后，侧栏一堆同名、槽丢了还会再造一个）
             "别把\"槽\"的标题抹平", "const slotRoute =", "wantTitle",
             # 2026-09-17 晚（"两个主 agent 同时跑"事故的两条根因 + busy 卡死）：
             #   ① checkUsable 曾用分页的 sc.list() 判活 ⇒ 槽被判死 ⇒ 新建；现在先查工作区成员表
             #   ② 判"是不是主 agent"只认通用标题 ⇒ 槽标题带后缀后认不出 ⇒ 新建；现在统一 isMainTitle()
             #   ③ busy 收尾认 busyFor（这一轮真正发进去的会话）+ 看到过 open、现在不 open 就收尾
             "alive:ws-member", "const isMainTitle =", "isMainTitle(meta.title)", "isMainTitle(x.title)",
             "const turnState =", "S.busyFor = String", "busySawOpen", "busyFor: S.busyFor ||",
             # 2026-09-17 晚（用户要求）：**异常退出自动续跑** —— 判据是 turn/end 的 reason.kind === 'error'
             #   （实测 "Stream ended without finish_reason"）；只对 error 续、不对 aborted 续；
             #   只对"我们自己触发的那一轮"续（busyFor 非空）；上限 3 次；`/say` 支持点名 sessionId
             "autoRetry", "retryCount", "lastReason", "已自动续跑", "sessionId: sid", "const want = String((body && body.sessionId)",
             "sessThu", "sessParatera", "routePick", "ctxRatioThu", "routeNeedsConfirm",
             # 2026-09-18（工程线）：建会话统一入口带聊天摘要专用 preset（压缩调优版）。
             #   压缩策略建会话时定死 ⇒ 不带 preset 就永远吃 0.16；降级分支不能丢
             #   （preset 服务没了也要能照常建会话，采集线不能因可选件挂掉）
             "const AGENT_PRESET =", "const presetUsable = async", "const createSession = async",
             "preset-fallback:", "preset:none", "agentPreset: AGENT_PRESET",
             "await createSession(sc, wsId ?", "await createSession(sc, wsIdForCreate ?",
             # 2026-09-18：默认线路收敛成一个常量（原先 '线路1' 散在三处：状态初始化 / pluginProbe 默认目标 / /collect 兜底）
             "const DEFAULT_ROUTE =", "routePick: DEFAULT_ROUTE", "only || DEFAULT_ROUTE", "S.routePick || DEFAULT_ROUTE",
             # 2026-09-18 晚（用户报"引用之后回应太长、搞了半天"）：注入段改成**比例原则** ——
             #   默认只改这一条（最小改动 ＋ 回报 ≤2 行，不写文档/不写记忆/不派子代理），只有"通则"才沉淀。
             #   同一条语义的另两处（MAIN_AGENT_SPEC §六 / WORKING §三）已同步改写。
             "不许默认做重的那个", "不写文档、不写记忆、不派子代理",
             # 2026-09-18 晚：待发引用在"原目标被归档、插件新建了主会话"时要**重新指向**
             #   （否则硬闸门 scope.id === quote.for 永远对不上，引用一个字都进不去）
             "const retargetQuote =", "quote-retarget:",
             "retargetQuote([loadedId], id, steps)", "retargetQuote([oldId], createdId, steps)",
             # 2026-09-19：注入段要**同时**给"显示编号"和"稳定 id" —— 编号是按渲染顺序派生的（不是稳定键），
             #   原来写 `q.no || q.id` ⇒ 有编号就把 id 藏了，改条目可能按编号错位。
             "（稳定 id＝`", "改条目一律按上面那个「稳定 id」", "它是按渲染顺序派生的",
             # 2026-09-19：**数字先定"是什么"再当"是多少"** —— 实测把「12，31」（班级/上课时间编号）
             #   当成题号，在面板上造出两个不存在的题号（第 10 页作业其实只有 3、4、8），用户当场发现。
 
             # 2026-09-19：**口径溯源不进正文** —— 用户指出「（09-16 13:04 通知群口径…）这种东西除了占地方还有什么用」；
             #   实测 45 条里 17 条带这类尾巴。（原文 6 行 440 字，按"写精简点"压成 2 行 180 字）
 
             # 2026-09-15 本轮改动点（丢了任何一条，主 agent 的自证/透传能力就静默退化）
             "extraFields", "droppedFields", "const panelView = async",
             "panel: await panelView()", "panel/set",
             # 2026-09-15 晚：步数口径改成"以 prep_report.md 行数为准"（原先写死 19 步 → 实际已 21 步，
             # 数字会随管线增删而腐烂）+ 开工前先读「微信登录态 / 数据窗口」两行自证
 
             # 2026-09-15 晚：动作项口径（漏报某老师作业那次纠正）——丢了它提示词就退化回"已知就删"
 
             # 2026-09-15 深夜：/collect 拨指针的前移护栏（采集指针被错拨成整点那次事故）
             "前移护栏", "skip-window", "wouldSkipMs",
             # 2026-09-15 更晚：上下文阈值**自动刷新会话**（主 agent 上下文爆掉被强制停止那次）
             #   · rotateSession 是从 /rotate 路由抽出来的**唯一实现**（自动刷新复用它，别抄第二份）
             #   · ctxProbe 读 request/context 的真实 contextWindow + assistant/message.usage
             #   · open turn 时不刷新（不打断正在干的活）
             "const rotateSession = async", "const ctxProbe = async", "const checkCtx = async",
             "routeOk.ctx = route", "contextWindow", "ctxAuto", "ctxRotations",
             "open: lastTurn >= 0 && !ended[lastTurn]",
             # 2026-09-15 更晚：**模型路由**（主 agent 走某校免费模型 → 不能读图；子代理必须显式走 paratera）
             #   丢了这段，子代理就会继承主 agent 的路由、于是整个体系再也读不了图
  "sessParatera", 
             # 2026-09-15 深夜：**省 token 的两个接口**（成本审计：面板整表 47 KB、每轮搬运 ≈11 万 token）
             #   · `/state?slim=1` 瘦身投影（只给 id/kind/urgency/done/isNew/date + 首行 60 字）
             #   · `/items-patch` 按 id 打补丁（未提供的字段原样保留 → 漏传 done 不会抹掉用户勾选）
             "itemsSlim", "slimItem", "routeOk.itemsPatch = route", "items-patch",
             # 瘦身模式**连 wakeText 也不回**（13 KB，而主 agent 的会话前缀里本来就有一份）；
             # 同时把 wakeTextLen 回显出去，别让"瘦身"变成"看不见我丢了多少"
             "wakeTextLen", "wakeText: slim ? '' : WAKE_TEXT",
             # 单位必须取 totalTokens（inputTokens 不含缓存命中，实测差 800 倍）——
             # 丢了这条断言，将来有人"顺手简化"成 input+output 就会静默失效
             "cacheReadTokens", "totalTokens",
             # 空闲路径节流（inspect 是整会话读回，别每 30 秒来一次）
             "ctxIdleIntervalMs", "ctxLastProbeAt",
             # 提示词里"上次采集"补上日期（指针可能是前一天的 23:59，只给 HH:MM 会有歧义）
 
             # 2026-09-15 深夜：**跨日补漏**——取数按日期过滤，只跑今天永远补不到那天的尾巴
 
             # 2026-09-20 全量审计（dsh-chat-digest/docs/audit-2026-09-20/REPORT.md）11 个 P1 的修复点。
             #   每条都对应一个可复跑的探针（`test/host-behavior-checks.mjs` 的 H01–H08）；
             #   丢了任何一条，对应缺陷会**静默回退**（探针立刻转红，但没人跑就发现不了）。
             # A04/H06：采集游标等交付成功才前移（旧版入队即前移 ⇒ 失败轮留覆盖空洞）
             "pendingCollect", "采集游标等交付成功才前移", "cursorCommitted",
             # A05/H01：异常续跑的条件原先永远为假（先清 busyFor 再判 busyFor）
             "先把\"这一轮的身份\"取出来", "roundSid",
             # A06/H08：返回的路由必须就是刚探的那个（旧版写死成功就回 '线路1'）
             "返回的路由必须就是刚才探的那个",
             # A07/H02+H03：空列表也是有效状态；持久化结果真实回传（旧版写死 persist:'saved'）
             "空数组也是有效状态", "持久化结果必须真实回传",
             # A10/H07：进入触发入口即占互斥锁（旧版只查 S.busy，异步前置阶段有竞争窗口）
             "const triggerRoundInner", "入口互斥锁已占用", "S.triggering",
             # A11/H05：超上限明确拒绝，不许静默 slice 丢条目
             "const ITEMS_MAX =", "不许静默 slice 丢条目", "已拒绝整表替换",
             # A01③：本机文件/图片读取路由（路径限定在允许根内；客户端把 file:/img: 渲染成链接/图）
             "const FILE_ROOTS =", "const serveLocal =", "const fileCandidates =",
             "路径不被允许", "fsSvc.readBytes",
             # A19（2026-09-21 用户报「启用了自动今天却没有自动」）：自动 tick 的去重判据里
             #   **不能有 collectDay**（它是"上次采到哪天"的游标；手工/菜单早上跑过一轮就会把它写成今天
             #   ⇒ 当晚的自动轮被静默取消）。"今天自动跑过没"只认 autoFiredDay；并把每次 tick 的结论
             #   写进 `S.autoWhy` 由 `/state` 回显（此前没有任何一处能看出"为什么没自动"）。
             "autoWhy", "只有一个判据：`autoFiredDay`", "S.autoFiredDay === day",
             "note: String(S.note || '')", "autoFiredAt", "autoWhy: S.autoWhy || ''",
             # A20（2026-09-21 用户纠正「我点击后会在浏览器又下载一遍」「最好所有文件都用本机默认应用打开吧」）：
             #   `file:` 链接改为 POST `/api/open` → 宿主用 `ctx.subprocess` 起 `cmd /c start "" "<绝对路径>"`，
             #   交给该扩展名的默认应用；闸门与 `/api/file` 同一套（信任栅栏 + 允许根 + 必须真实存在）。
             #   丢了它，链接会退回"浏览器再下载一份"。
             "const spawnOpen = async", "routeOk.open = route('POST', 'open'", "cmd-start",
             "lastOpenOk", "所有文件都用本机默认应用打开",
             # A21/A22（2026-09-22 用户问"为什么昨天还是没有自动获取"）：
             #   实测 2026-09-21 23:30 那轮：23:35:59 调 `ask_user_question` → 一直等 → 90 秒后
             #   `turn/end reason=interrupted` ⇒ 整晚白跑（产物停在 23:37:32、面板一条没回写）。
             #   ① A21＝**未交付的轮要能自动补跑**（`resumeCount` 上限 3，交付成功才归零）；
             #   ② A22＝**把"它在等你回答"暴露出来**（`/state.pendingAsk` + 面板顶部卡片 + 一键跳会话），
             #      并在提示词里禁掉"自动轮用提问阻塞"。
             "补跑未交付的", "S.resumeCount", "pendingAsk",
             "主 agent 在等你回答", 
             "ask: askOut",
             # A23（2026-09-25 用户问"为什么多了一堆主agent"）：
             #   实测根因＝**上下文自动轮换**每次新建一个「聊天摘要 · 主 Agent」，而旧版轮换只 rebase 了
             #   sessionId/mainSessionId、**槽没管**（sessParatera 一直指着刚被归档的会话 ⇒ 下一轮判槽死 ⇒
             #   再建一个）；而且轮换的 steps **没有落盘**，事后查不出"归档成没成"。三处：
             #   ① 轮换留痕（ctxLastRotateWhy/Ok/Archived/Err/Steps，跨重启）；② 槽一并 rebase；
             #   ③ 扫出"多余的同标题主 agent"给面板 + `POST /api/archive` 一键归档。
             "ctxLastRotateSteps", "slot-rebase:", "const scanExtraMains = async", "extraMains",
             "routeOk.archive = route('POST', 'archive'", "已归档多余的会话",
             # ── A28（2026-09-25 通用化）：内置的必须是【通用】提示词，私人内容只住 local/ ──
             "WAKE_GENERIC", "CF.wakeText", "ROUND_GENERIC", "CF.roundText",
             "## 数据从哪来（默认约定）", "先把 inbox 读完再动手", "别为了加一节去改插件代码", "不要编造数据",
        # 2026-09-25「装完就能用」：inbox 约定 + 没 probeUrl 时跳过探测
        # A29（2026-09-26 事故）：堵死"多出一个主 agent"的三条不变量
        "if (!wc || !sc || !ids) return null", "alive !== false",
        "&& !stored", "create:skip:controllers-missing", "slotsInitWait",
        "const INBOX_DIR", "CF.inboxDir", "inbox: INBOX_DIR", "跳过网关探测",
        "{inbox}", "INBOX_DIR",
             "CF.agentPreset", "CF.agentCwd",

             # A15（2026-09-25 发布化）：Host 函数体进包 + 本机路径全部可由 profile 的 config 覆盖。
             #   丢了这段，"发布包"就又会依赖包外的绝对路径（换机器即废）。
             "const CF = (typeof CFG", "const ENV = (typeof process", "CF.fileRoots", "CF.agentCwd",
             "CF.dshHome", "CF.stateDir", "CF.wxRoot",
             # A25（2026-09-25）：面板活数据从 %TEMP% 迁到持久数据根（A18 的漏网之鱼）
             "const PANEL_OLD", "已从旧 %TEMP% 迁到",
             # A27（2026-09-25）：`routeWhy` 必须报**实际探的那条线**。旧版把这句话写死成 "THU"，
             #   于是探 paratera 成功时 /state 会同时给出 routePick=paratera 与 routeWhy="probe:THU 可达"
             #   —— 自证字段当场自相矛盾（实测 2026-09-25）。配套探针 H23。
             "'probe:' + probeRes.route"):
    check("片段仍在: %s" % frag, frag in body)

with io.open(CHK, "w", encoding="utf-8", newline="\n") as f:
    f.write("function __cfBody() {\n" + body + "\n}\n")
r = subprocess.run(["node", "--check", CHK], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")   # 别用 locale 编码，node 的错误里是 UTF-8 中文
check("node --check", r.returncode == 0, (r.stderr or "").strip()[:400])

print("\nbody 字符数 %d ｜ 行数 %d" % (len(body), body.count("\n") + 1))
print("FAILS:", len(fails), fails)
sys.exit(1 if fails else 0)
