// dsh-chat-digest — browser UI (plain global script, no framework).
// Injected into every full page load through DSH's structured index table, so
// it also reaches the page served through ds-harness-remote.
//
// Contributes three things, all plain DOM (the sidebar shell exposes no slot an
// external static plugin can register into):
//   1. a footer row inside the sidebar foot — ABOVE the Remote/cordis rows, and
//      BELOW 其它同类插件's own row when that plugin is installed;
//   2. an entry row inside the sidebar, right after "新会话", aligned with the
//      task-board / mnemon / skill-explorer rows (their computed style is copied);
//   3. a center-column panel (left: main agent, right: item list).
(function () {
  'use strict'
  if (typeof window.__chatFeedCleanup === 'function') window.__chatFeedCleanup()
  else if (window.__chatFeedLoaded) return
  window.__chatFeedLoaded = true

  var API = '/chat-feed/api'
  var ENT_ATTR = 'data-dsh-chatfeed-entry'
  var FAMILY = '[data-dsh-taskboard-entry],[data-dsh-mnemon-entry],[data-dsh-skill-explorer-entry],[data-dsh-ssh-entry],[' + ENT_ATTR + ']'
  var VIEW_ATTR = 'data-dsh-chat-digest-view'
  // 刷新图标（24×24 viewBox 的环形箭头，stroke=currentColor 跟着文字色走）
  var ICON_ROTATE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>'
  var PANEL_ATTR = 'data-dsh-chat-digest-panel'
  // 面板不滚动横条里的两件东西（2026-09-13）：right.js 的时间行槽 + ui.js 的「删除已勾选」按钮
  var barEl = null      // 横条本身
  var barSlot = null    // right.js 往里塞"自动采集时间"行的槽
  var clrEl = null      // 「删除已勾选」按钮（标签随已勾选条数变）
  var CHAT_SVG = '<svg viewBox="0 0 16 16" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 3.1h12v8.1H8.4L5 14.2v-3H2z"/><path d="M5 6.1h6M5 8.5h3.8"/></svg>'
  // 底栏图标：与侧栏入口同尺寸（18×18，viewBox 16），靠 24px 容器留白对齐。

  // 会话被重建后 Host 那边发的种子消息用的是 queue 模式 —— 实测不会触发运行、等于没发
  // （`seed:ok` 是假成功，会话日志里根本没有那条）。而"从没跑过"的会话在 DSH 里是 blank，
  // 侧栏会把它隐藏，于是页面永远点不到那一行。这里由页面补一条：既唤醒会话（跑过一个 turn
  // 就不再是 blank、侧栏立刻出现这一行），也顺便把职责交代清楚。
  //
  // 2026-09-14：这段文案**以 Host 的 WAKE_TEXT 为准**。新 Host（v29）在 `/state` 里返回 `wakeText`，
  // refresh() 会把它写进 store.wakeText，这里只保留一份**兜底**（Host 还是旧版、或 /state 拿不到时用）。
  // 旧的 Host SEED 已被移除（它用 queue 模式、实测静默失败），所以"两份文案"这件事到此为止：
  // 一旦新 Host 生效，wakeFor() 用的就是 Host 那一份，下面这段只作降级备份。
  var WAKE_TEXT_FALLBACK = [
    '【聊天摘要 · 主 Agent】',
    '',
    '你的职责：为我维护「聊天摘要」的条目流。',
    '1. 把采集到的聊天信息提炼成待办（🔴今天 / 🟡本周 / ⚪更远）与四类信息（2.1 官方 / 2.2 同学与群里的经验 / 2.3 资源与工具 / 2.4 生活与办事）；',
    '2. 三问过滤：需要我做什么？会不会影响我？我以后用得上吗？——皆否则不报；',
    '3. 判断时效：动作型过期即过期；规则/资源/经验型只要仍有效就保留。',
    '',
    '我会用面板上的「引用它」给你留言：那条会作为**独立上下文**注入到你的提示词里（形如',
    '「【用户引用了面板上的一条】#T1：…」），不写进我的输入框；我紧接着发的那条就是针对它的意见，请沉淀成经验教训。',
    '',
    '这条是插件为恢复会话显示而补发的初始化说明。收到请只回复：已就绪。',
  ].join('\n')
  // 取当前该发哪一份：Host 给的优先，没有就用兜底
  function wakeText() {
    var t = store.wakeText
    return (typeof t === 'string' && t.length > 0) ? t : WAKE_TEXT_FALLBACK
  }

  var store = {
    items: [], auto: false, autoTime: '23:00', busy: false,
    note: '尚未采集 · 点「获取」开始', lastCollectAt: 0, lastCount: 0, err: '', sessionId: '', sessionTitle: '',
    wakeText: '', lastError: '', routeError: '', saveOk: true,
  }
  var footBox = null
  var entryRow = null
  var panelEl = null
  var listEl = null
  var accGetBtn = null   // 侧栏展开行里的「获取」按钮（只用来更新 title）
  var accEl2 = null      // 侧栏展开行里的「上次采集」span
  var leftBackBtn = null
  var rotateBtn = null
  var rotateBusy = false
  var confirmEl = null
  var intervalIds = []
  var observers = []
  // 文档/窗口级监听器也要能摘掉：热重载（重新注入 ui.js）后旧实例的监听还挂在
  // document 上，会继续对点击作出反应 —— 实测表现为"面板刚打开 10ms 就被关掉"
  // （旧实例的 onDocClick 把插件自己切会话的那次点击当成了用户点侧栏）。
  var docListeners = []
  function onEvt(target, type, fn, cap) {
    target.addEventListener(type, fn, cap)
    docListeners.push([target, type, fn, cap])
  }
  // 只有最新那个实例才对全局事件作出反应；被替换掉的旧实例一律装死。
  // （光靠 cleanup 不够：页面加载时那个实例的 cleanup 可能已经被更早的一次替换调用过，
  //   它的监听却还在 —— isCurrent() 让这种僵尸实例无论如何都动不了手。）
  function isCurrent() { return window.__chatFeedCleanup === cleanup }

  function cleanup() {
    intervalIds.forEach(clearInterval)
    intervalIds = []
    observers.forEach(function (o) { try { o.disconnect() } catch (e) {} })
    observers = []
    docListeners.forEach(function (d) { try { d[0].removeEventListener(d[1], d[2], d[3]) } catch (e) {} })
    docListeners = []
    if (footBox && footBox.parentNode) footBox.parentNode.removeChild(footBox)
    if (entryRow && entryRow.parentNode) entryRow.parentNode.removeChild(entryRow)
    if (accEl && accEl.parentNode) accEl.parentNode.removeChild(accEl)
    accEl = null
    if (panelEl && panelEl.parentNode) panelEl.parentNode.removeChild(panelEl)
    // 挂在中央列上的自建节点不在 panelEl 里，必须单独清 —— 否则每重注入一次就多留一份。
    // 实测堆了 3 个「返回」按钮，而 querySelector('.cfw-leftback') 拿到的是最旧那个，
    // 点它走的是旧实例的 closePanel（清不掉新实例的定时器 → 关了面板仍往会话写唤醒消息）。
    var orphans = document.querySelectorAll('.cfw-leftback, #cfw-quotebar')
    for (var oi = 0; oi < orphans.length; oi++) {
      try { if (orphans[oi].parentNode) orphans[oi].parentNode.removeChild(orphans[oi]) } catch (e) {}
    }
    leftBackBtn = null
    var st = document.getElementById('chatfeed-style')
    if (st && st.parentNode) st.parentNode.removeChild(st)
    document.documentElement.removeAttribute(VIEW_ATTR)
    footBox = null; entryRow = null; panelEl = null; listEl = null
    window.__chatFeedLoaded = false
    if (window.__chatFeedCleanup === cleanup) window.__chatFeedCleanup = null
  }
  window.__chatFeedCleanup = cleanup

  function pad(n) { return (n < 10 ? '0' : '') + n }
  // hhmm(ms) 返回的是**已过多久**（时长 "H:MM"），**不是时钟时间** —— 名字是历史遗留。
  // 2026-09-15 实测教训：它被写进「上次采集 21:10」这种位置 → 用户当成时钟读，
  // 倒推出"上次采集是 00:00"（而真值是前一天 23:59:58，只差 2 秒，光看时长根本分不出来）。
  // 所以：**时长一律带"前"字，绝对时间一律用 stamp()**，两者不要混。
  function hhmm(ms) {
    if (!ms) return '--:--'
    var s = Math.floor((Date.now() - ms) / 1000)
    return pad(Math.floor(s / 3600)) + ':' + pad(Math.floor((s % 3600) / 60))
  }
  // 绝对时间戳（本地时区，形如 `09-14 23:59`）—— 回答"到底哪一刻采的"
  function stamp(ms) {
    if (!ms) return '--'
    var d = new Date(ms)
    return pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes())
  }
  function api(method, endpoint, body) {
    var init = { method: method, credentials: 'same-origin', headers: {} }
    if (method === 'POST') {
      init.headers['Content-Type'] = 'application/json'
      init.body = JSON.stringify(body || {})
    }
    return fetch(API + '/' + endpoint, init).then(function (r) {
      return r.json().catch(function () { return null })
    })
  }
  function refresh() {
    return api('GET', 'state').then(function (s) {
      if (!s) { store.err = '服务无响应（/chat-feed/api/state 没有返回 JSON）'; render(); return }
      syncProviders(s.routes)          // 线路菜单跟着宿主配置走
      store.err = (s.ok === false && s.error) ? String(s.error) : ''
      // §4.2-5 失败可见化：Host 侧（v29 起）把 saveState / 路由注册的失败放进 lastError / routeError。
      // 以前这些只 console.error，动态插件看不到 console，于是 UI 只显示"服务无响应"，
      // 分不清"插件停了"和"路由没注册上"。这里把 Host 报的错直接给用户看。
      if (!store.err) {
        if (s.routeError) store.err = 'Host 路由异常：' + String(s.routeError)
        else if (s.lastError) store.err = 'Host 报错：' + String(s.lastError)
      }
      Object.keys(store).forEach(function (k) { if (s[k] !== undefined) store[k] = s[k] })
      render()
      // ⚠ 这里原来每 15 秒还调一次 GET /chat（把主 agent 对话喂给一个已被删掉的旧左半手搓对话框）。
      // 两个问题：① 那个面板的 CSS 早就是 display:none，当前界面（左半＝DSH 官方会话）根本看不到 → 白跑；
      // 当前界面（左半＝DSH 官方会话）根本看不到 → 白跑；
      // ② Host 的 /chat 会先 ensureSession，而 ensureSession 每次都无条件 rename →
      // 每 15 秒往会话日志里塞一条 session/title（实测堆到 110 条）。
      // 改成按需：需要时调 window.__cfwFetchChat()。
    }).catch(function (e) {
      store.err = '连接失败：' + String((e && e.message) || e)
      render()
      console.error('[dsh-chat-digest] state', e)
    })
  }
  // 诊断入口：手动拉一次主 agent 对话（不进定时轮询）
  // 诊断入口：手动拉一次主 agent 对话（不进定时轮询；旧左半已删，这里只打日志）
  window.__cfwFetchChat = function () {
    return api('GET', 'chat').then(function (c) {
      if (c && c.ok && c.messages) { console.log('[dsh-chat-digest] /chat', c.messages); return c.messages.length }
      return -1
    })
  }
  /* A22（2026-09-22）：把"切到主 agent 那条会话"暴露出去，给 right.js 的「它在等你回答」卡片用 ——
     用户在自动轮里看不到提问，所以面板上要给一个**一键跳过去**的入口。 */
  window.__cfwOpenSession = function (id, epoch) {
    try { return !!openNativeSession(id, epoch) } catch (e) { return false }
  }
  function call(method, endpoint, body) {
    return api(method, endpoint, body).then(function (r) {
      var failed = !!(r && r.ok === false)
      // 顺序很重要：refresh() 会把 store.err 重置成 Host 报的错，所以本次动作的失败必须**之后**再写回。
      // 原来是先写后 refresh → 文案被立刻清掉，调用方还会把失败当成功。
      // 这里保持 resolve（不 reject）：调用方有几个没写 .catch，reject 会变成未处理的拒绝。
      // 因此需要区分成败的调用方必须自己看 r.ok（见 runCollectRoute）。
      return refresh().then(function () {
        if (failed) { store.err = String(r.error || '操作失败'); render() }
        return r
      })
    }).catch(function (e) {
      store.err = '请求失败：' + String((e && e.message) || e)
      render()
      throw e
    })
  }

  // ---------------- style ----------------
  var CSS = [
    '.cfw-item.cfw-clickable{cursor:pointer;}',
    // ---- 下拉菜单（替代原底栏行）——外观参考 dsh-home-sync 的 popover ----
    '@keyframes cfwPop{from{opacity:0;transform:scale(.97) translateY(-3px)}to{opacity:1;transform:none}}',
    // ---- 菜单里的按钮：样式完全照抄 同类插件 ----
    '.cfw-tk{font-family:inherit;font-size:14px;line-height:1.6;padding:0 8px;border-radius:6px;border:1px solid rgba(128,128,128,.45);background:transparent;color:inherit;cursor:pointer;white-space:nowrap;flex:none;}',
    '.cfw-tk:hover{border-color:rgba(128,128,128,.85);background:rgba(128,128,128,.18);}',
    '.cfw-tk.cfw-tk-on{background:#4caf50;color:#fff;border-color:#4caf50;}',
    '.cfw-tk[disabled]{opacity:.5;cursor:default;}',
    // ---- 「获取」改成**带三角形的下拉**（2026-09-17 用户要求）----
    //   为什么菜单必须**在文档流里**（不能用 position:absolute 浮层）：`.cfw-acc` 与 `.cfw-acc-inner`
    //   都带 overflow:hidden（折叠动画靠 grid-template-rows 0fr↔1fr），浮层会被**裁掉**、点不到。
    //   所以改成"展开行由 flex 行变成 flex 列：上面一行按钮、下面一块菜单"，靠折叠区的 1fr 自然撑高。
    '.cfw-tk-get{display:inline-flex;align-items:center;gap:4px;}',
    '.cfw-tk-get svg{transition:transform .2s ease;opacity:.75;}',
    '.cfw-tk-get.cfw-tk-get-on svg{transform:rotate(180deg);}',
    // 探测不通 ⇒ 红底白字「获取失败」闪一下（2600ms 后自己恢复；**采集指针不会被更新**，那是宿主侧的事）
    '.cfw-tk.cfw-tk-fail,.cfw-tk.cfw-tk-fail:hover{background:#e5484d;color:#fff;border-color:#e5484d;}',
    '.cfw-tk-row{display:flex;align-items:center;gap:8px;width:100%;}',
    // 悬浮菜单（2026-09-17 用户要求：**不要内嵌列表，要悬浮列表**）——
    //   挂在 document.body 上 + position:fixed + 大 z-index（见 ensureMenu 的注释：挂在折叠区里会被 overflow:hidden 裁掉）
    '.cfw-tk-menu{position:fixed;z-index:2147482500;display:none;box-sizing:border-box;padding:4px;border:1px solid var(--dsw-alias-border-l2,rgba(128,128,128,.35));border-radius:10px;background:var(--dsw-alias-bg-layer-2,var(--cfw-panelBg,#ffffff));color:var(--dsw-alias-label-primary,var(--cfw-text,#1f2328));box-shadow:var(--dsw-shadow-lv3,0 8px 28px rgba(16,24,40,.3));animation:cfwPop .16s cubic-bezier(.2,.9,.3,1.05);}',
    '.cfw-tk-menu.cfw-tk-menu-on{display:block;}',
    '.cfw-tk-mi{display:flex;align-items:center;gap:6px;width:100%;box-sizing:border-box;padding:6px 8px;font-family:inherit;font-size:13px;line-height:1.6;text-align:left;background:transparent;border:0;border-radius:6px;color:inherit;cursor:pointer;}',
    '.cfw-tk-mi:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.18));}',
    '.cfw-tk-mi-s{margin-left:auto;font-size:11px;opacity:.6;}',
    '.cfw-tk-el{margin-left:auto;font-size:14px;line-height:1;font-variant-numeric:tabular-nums;font-family:ui-monospace,Consolas,monospace;flex:none;}',
    // 2026-09-13 实测：`.bhn1Oq_root`（会话列表容器，position:static）从这一行**下半截**开始覆盖
    //   → 输入框中心点上的 elementFromPoint 是它、真实鼠标点不进去（按钮中心也压在边界上，只是侥幸能点）。
    //   修法：把展开行整体抬成定位元素 + z-index，而不是只给输入框加 pointer-events。
    '.cfw-acc-body{position:relative;z-index:3;}',
    // 每天自动采集时间（2026-09-13）：直接可改，改完立刻 POST set-auto{time}
    //   高度对齐旁边的 .cfw-tk 按钮（实测按钮 22.4px → box-sizing:border-box + height:22px，误差 <1px）
    '.cfw-tk-time{margin-left:auto;width:64px;flex:none;box-sizing:border-box;height:22px;font-size:11px;line-height:20px;padding:0 2px;border-radius:6px;border:1px solid var(--dsw-alias-border-l2);background:transparent;color:inherit;font-family:ui-monospace,Consolas,monospace;}',
    // ---- 侧栏入口行右端的 ⋯ 触发钮 ----
    '.cfw-more2{flex:0 0 auto;width:22px;height:22px;margin-left:auto;display:inline-flex;align-items:center;justify-content:center;border-radius:6px;cursor:pointer;opacity:.6;font-size:15px;line-height:1;}',
    '.cfw-more2:hover{background:rgba(128,128,128,.2);opacity:1;}',
    // 侧栏入口：字号/缩进/颜色对齐同族的「任务看板/记忆系统/技能中心」实测值
    // 高度靠"显式 36px + align-self:stretch"双保险：只写 height 时，若宿主把侧栏改成交叉轴可拉伸、
    // 或兄弟行是别的高度，就会跟着错；stretch 让它永远与同排兄弟等高。
    '.cfw-entry{display:flex;align-items:center;align-self:stretch;gap:8px;width:100%;height:36px;min-height:36px;box-sizing:border-box;padding:0 10px;border:0;background:transparent;color:rgb(97,102,107);font-family:inherit;font-size:13px;font-weight:400;line-height:normal;cursor:pointer;text-align:left;border-radius:8px;}',
    
    '.cfw-entryIco{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;flex:0 0 auto;opacity:.85;}',
    '.cfw-entryLbl{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:inherit;font-family:inherit;line-height:normal;}',
    '[' + PANEL_ATTR + ']{display:none;position:absolute;inset:0;flex-direction:row;font-family:inherit;font-size:14px;background:var(--dsw-alias-bg-base,transparent);}',
    
    // 高度固定 42.4px：右侧标题栏含「清理已完成」按钮会被撑高（实测 42.4 vs 左侧 38.4），
    // 不锁死的话左右两条标题下边线会错位。
    '.cfw-h{box-sizing:border-box;height:42.4px;font-size:13px;font-weight:600;padding:0 14px;border-bottom:1px solid rgba(128,128,128,.2);display:flex;align-items:center;justify-content:space-between;gap:8px;flex:none;}',
    // 列表要**撑满右栏**：`.cfw-right` 是 flex 列，之前这条只有 overflow:auto，
    // 于是内容不足时列表只占上半截、下面留一大片空白（用户报"右栏没占满、在中间被截断"）。
    // flex:1 1 auto 让它吃掉剩余高度（内容不足时铺满，超出时照常滚动）；
    // min-height:0 是 flex 子项能正常收缩的必要条件（否则内容多时不会出滚动条）。
    '.cfw-rbody{flex:1 1 auto;min-height:0;overflow:auto;padding:6px 0 20px;}',
    '.cfw-card{border:1px solid rgba(128,128,128,.25);border-radius:8px;padding:10px 12px;}',
    '.cfw-grp{margin-bottom:6px;}',
    '.cfw-gl{font-size:12px;opacity:.6;padding:8px 14px 4px;}',
    '.cfw-item{display:flex;align-items:center;gap:8px;padding:8px 14px;font-size:13px;line-height:1.6;position:relative;cursor:pointer;}',
    
    
    '.cfw-txt{flex:1 1 auto;min-width:0;word-break:break-word;}',
    '.cfw-src{flex:none;font-size:11px;opacity:.45;}',
    '.cfw-more{flex:none;cursor:pointer;opacity:.5;padding:0 2px;font-size:15px;line-height:1;align-self:center;}',
    
    '.cfw-menu{position:absolute;right:10px;top:26px;z-index:30;width:300px;background:var(--dsw-alias-bg-elevated,#1f1f1f);border:1px solid rgba(128,128,128,.35);border-radius:8px;padding:10px;box-shadow:0 8px 28px rgba(0,0,0,.35);}',
    '.cfw-mini{font-size:12px;padding:2px 8px;border-radius:6px;border:1px solid rgba(128,128,128,.45);background:transparent;color:inherit;cursor:pointer;font-family:inherit;}',
    
    '.cfw-h{border-bottom:1px solid var(--dsw-alias-separator-primary);color:var(--dsw-alias-label-primary);font-size:13px;font-weight:600;padding:12px 16px;}',
    '.cfw-card{background:var(--dsw-alias-bg-base);border:1px solid var(--dsw-alias-border-l2);border-radius:10px;padding:10px 12px;transition:box-shadow 120ms ease,border-color 120ms ease,transform 120ms ease;}',
    '.cfw-card:hover{box-shadow:var(--dsw-shadow-lv2);border-color:var(--dsw-alias-border-l3);transform:translateY(-1px);}',
    '.cfw-gl{color:var(--dsw-alias-label-tertiary);padding:10px 16px 4px;}',
    
    '.cfw-item:hover{background:var(--dsw-alias-interactive-bg-hover);}',
    '.cfw-chk{border:1.5px solid var(--dsw-alias-border-l3);}',
    '.cfw-item.cfw-done .cfw-chk{background:var(--dsw-alias-state-success-primary);border-color:var(--dsw-alias-state-success-primary);color:var(--dsw-alias-label-primary-foreground);}',
    '.cfw-item.cfw-done .cfw-txt{color:var(--dsw-alias-label-tertiary);text-decoration:line-through;}',
    '.cfw-src{color:var(--dsw-alias-label-tertiary);}',
    
    '.cfw-mini{border:1px solid var(--dsw-alias-border-l2);color:var(--dsw-alias-label-secondary);border-radius:8px;padding:4px 10px;}',
    // 面板里的**不滚动横条**（2026-09-13）：自动采集时间 + 删除已勾选都放这里 ——
    // 用户原话"都属于不会被滚轮滚掉的内容"。放进 .cfw-rbody 会跟着列表滚走。
    // 2026-09-13 实测数据：竖线 lineX=833.2、横条左缘 barLeft=841.2 → **右边差 8px**（.cfw-right 左侧有 8px 内边距）。
    //   修法：横条的边框向左探 8px（负 margin）去接竖线，内容靠 padding 补回（10+8=18 → 视觉不变）。
    '.cfw-rbar{display:flex;align-items:center;gap:8px;margin-left:-8px;padding:6px 10px 6px 18px;border-bottom:1px solid var(--dsw-alias-border-l2);flex:none;font-size:12px;color:var(--dsw-alias-label-secondary);}',
    '.cfw-mini-off{opacity:.45;cursor:default;}',
    '.cfw-mini-off:hover{background:transparent;color:var(--dsw-alias-label-secondary);}',
    '.cfw-mini:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary);}',
    '.cfw-menu{background:var(--dsw-alias-bg-layer-2);border:1px solid var(--dsw-alias-border-l2);box-shadow:var(--dsw-shadow-lv3);border-radius:10px;}',
    '.cfw-hr{justify-content:space-between;}',
    '@keyframes cfwSpin{to{transform:rotate(360deg)}}',
    // 侧栏菜单：令牌 → 自带深浅色 palette → 白底兜底（三层，任一缺失都不会丢样式）
    // 页面内 ⋯ 菜单：与侧栏菜单同一套卡片外观
    '.cfw-menu{position:absolute;right:10px;top:26px;z-index:30;width:300px;background:var(--dsw-alias-bg-layer-2,var(--cfw-panelBg,#ffffff));color:var(--dsw-alias-label-primary,var(--cfw-text,#1f2328));border:1px solid var(--dsw-alias-border-l2,var(--cfw-border,#c9d2dc));border-radius:10px;padding:10px;box-shadow:var(--dsw-shadow-lv3,0 8px 28px rgba(16,24,40,.3));animation:cfwPop .18s cubic-bezier(.2,.9,.3,1.05);}',
    '.cfw-more{flex:0 0 auto;width:24px;height:24px;padding:0;display:inline-flex;align-items:center;justify-content:center;font-size:15px;line-height:1;border-radius:6px;cursor:pointer;opacity:.6;}',
    '.cfw-more:hover{opacity:1;background:var(--dsw-alias-interactive-bg-hover);}',
    
    '.cfw-acc-body{display:flex;align-items:center;gap:8px;padding:8px 10px 10px 16px;}',
    '.cfw-more2-on{background:var(--dsw-alias-interactive-bg-hover);opacity:1;}',
    // 展开态：入口行 + 折叠区连成一块
    // 展开态：入口行保留**上方** 8px 圆角（与收起态一致），下方两角交给折叠区补 8px，
    // 两者拼成一整块 8px 圆角的大行。注意不能写 border-radius:0 —— 那会把上圆角也削平（用户报"上圆角怎么搞没了"）。
    '.cfw-entry-open{background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.14));border-radius:8px 8px 0 0 !important;}',
    
    // 侧栏里字号跟入口一致（13px），14px 偏大
    '.cfw-acc-body .cfw-tk{font-size:13px;}',
    '.cfw-acc-body .cfw-tk-el{font-size:13px;}',
    
    // 箭头：收起指右，展开转 90° 指下
    '.cfw-more2-on svg{transform:rotate(90deg);}',
    '.cfw-more2{color:var(--dsw-alias-label-tertiary);}',
    // 丝滑：grid-rows 用 ease-out，内容再叠一层 fade + 轻微下滑
    
    
    // 入口行自身的展开过渡
    // ===== 折叠动画终版：展开/收起分开曲线，内容只做"进场"动效 =====
    // 收起（基础态）：ease-in，收得干脆
    '.cfw-acc{display:grid;grid-template-rows:0fr;overflow:hidden;transition:grid-template-rows .26s cubic-bezier(.4,0,.6,1);}',
    // 展开：ease-out，铺得柔和
    '.cfw-acc[data-open="true"]{grid-template-rows:1fr;transition:grid-template-rows .34s cubic-bezier(.22,1,.36,1);}',
    // 内容：常态不透明、无过渡；仅展开时用 animation 淡入（收起时随容器裁掉，不出现空盒）
    '.cfw-acc-body{opacity:1;transform:none;transition:none;}',
    '.cfw-acc[data-open="true"] .cfw-acc-body{animation:cfwAccIn .32s cubic-bezier(.22,1,.36,1) both;padding-bottom:8px;}',
    '@keyframes cfwAccIn{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:none}}',
    // 箭头：对称曲线，双向都自然
    '.cfw-more2 svg{transition:transform .26s ease-in-out;}',
    // 折叠区背景/圆角也要有过渡，否则收起瞬间高亮消失、高度还在缩（用户报"跳变"）
    // 折叠区必须有背景，否则高亮只到入口行 —— 这里和 .cfw-entry-open 用**同一个令牌**，
    // 两块拼成一个整体；收起态显式写 transparent/0，让上面的 transition 有起点可插值（否则收起会跳变）。
    '.cfw-acc-inner{min-height:0;overflow:hidden;background:transparent;border-radius:0;transition:background .26s cubic-bezier(.4,0,.6,1),border-radius .26s cubic-bezier(.4,0,.6,1);}',
    '.cfw-acc[data-open="true"] .cfw-acc-inner,.cfw-acc.cfw-acc-open .cfw-acc-inner{background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.14));border-radius:0 0 8px 8px;}',
    '.cfw-acc[data-open="true"] .cfw-acc-inner{transition:background .3s cubic-bezier(.22,1,.36,1),border-radius .3s cubic-bezier(.22,1,.36,1);}',
    '.cfw-split{flex:0 0 5px;position:relative;cursor:col-resize;background:transparent;}',
    
    '.cfw-split:hover::after,.cfw-split.cfw-drag::after{background:var(--dsw-alias-border-l3,rgba(128,128,128,.55));}',
    '.cfw-h{border-bottom:1px solid var(--dsw-alias-separator-primary,var(--dsw-alias-border-l2,rgba(128,128,128,.25)));}',
    // 侧栏入口：hover / 选中（面板打开时）都接令牌，和任务看板一致
    '.cfw-entry[data-active="true"]{background:var(--dsw-alias-interactive-bg-active,var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.18)));}',
    // 拖动中的全局状态：禁选文本 / 禁面板交互（减少重排与误触）
    'body.cfw-dragging{user-select:none;-webkit-user-select:none;cursor:col-resize;}',
    // 侧栏入口：平时次要色，hover/选中时文字变深 + 背景高亮；**不做过渡（跳变，与原生一致）**
    '.cfw-entry{color:var(--dsw-alias-label-secondary,rgb(97,102,107));transition:none;}',
    '.cfw-entry:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.14));color:var(--dsw-alias-label-primary,rgb(31,35,40));}',
    '.cfw-entry[data-active="true"]{background:var(--dsw-alias-interactive-bg-active,var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.18)));color:var(--dsw-alias-label-primary,rgb(31,35,40));}',
    // 展开态（与折叠区连成一块）也即时切换
    // 展开态（与折叠区连成一块）也即时切换。
    // 注意：这条排在前面那条 .cfw-entry-open 之后、会覆盖它，两处必须一致 ——
    // 展开态的高亮：入口行**保留上方 8px 圆角**（与收起态一致），下方两角由折叠区补 8px，
    // 拼成一整块 8px 圆角的大行。**不要写 border-radius:0** —— 那会连上圆角一起削平。
    // 必须 !important：入口按钮身上有一条**内联** border-radius:8px（建行时从参考入口复制实测样式写进去的），
    // 内联样式优先级高于任何类选择器 —— 实测类里写 0 时 computed 仍是 8px，只能抬优先级。
    '.cfw-entry-open,.cfw-entry-open:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.14));color:var(--dsw-alias-label-primary,rgb(31,35,40));border-radius:8px 8px 0 0 !important;}',
    // 触发器 hover 也即时
    '.cfw-more2{transition:none;}',
    // ---- ⋯ 菜单：两行图标项 ----
    '.cfw-menu{width:196px;padding:4px;}',
    
    '.cfw-mi:hover{background:var(--dsw-alias-interactive-bg-hover);}',
    '.cfw-mi svg{flex:0 0 auto;opacity:.75;}',
    '.cfw-mi-danger:hover{background:var(--dsw-alias-state-error-primary);color:var(--dsw-alias-label-primary-foreground);}',
    '.cfw-mi-danger:hover svg{opacity:1;}',
    // ===== 左右并排：原生会话留左半、我的面板占右半 =====
    // 常规流子节点：靠父级 padding-right 挤窄；绝对定位子节点：靠 right 挤窄（两种都覆盖）
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"] > *:not([' + PANEL_ATTR + ']):not([data-dsh-taskboard-view]){right:var(--cfw-right,50%) !important;max-width:100%;}',
    
    'html[' + VIEW_ATTR + '] [' + PANEL_ATTR + ']{display:flex;}',
    // 手搓的左栏（对话）不再需要：原生会话取代它
    // splitter 变成面板左边缘的抓手
    // 分割线本体：**这条不能删**（2026-09-14 它被"等价去重"删掉过 → 线直接消失）。
    // 注意 `content:""` 是画的线的必要条件；剩下的规则只改 left / hover 色。
    // 去重时只量了"当前 elements 的 computed style"，而 ::after 不进 elements 列表，
    // 所以"没看到变化"是假象 —— 判据必须显式覆盖伪元素。
    '.cfw-split::after{content:"";position:absolute;left:0;top:0;bottom:0;width:1px;background:var(--dsw-alias-separator-primary,var(--dsw-alias-border-l2,rgba(128,128,128,.25)));transition:background .15s ease;}',
    // 2026-09-13 教训（我踩过）：**竖线不能画到面板外**（试过 left:-8px 去对齐会话卡的内容边）
    //   —— 面板左缘外那块区域被 DSH 的会话卡盖着，线被盖住 → 用户报"中间分割线没了"。
    //   现在画在面板左缘 left:0；横条的下边框也从面板左缘开始 → 两条线**正好相交**。
    //   （左侧会话卡自己的分割线还会短 8px，那是 DSH 给会话卡的 `padding-right: calc(50% + 8px)` 内边距，
    //    属于它的卡片样式，我们不去越界对齐它。）
    // ===== 定稿：用 DSH 官方聊天界面 =====
    // 左半留给官方会话（常规流子节点用父级 padding-right 挤窄；绝对定位子节点用 right 挤窄，两种都覆盖）
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"]{position:relative;padding-right:var(--cfw-right,50%) !important;}',
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"] > *:not([' + PANEL_ATTR + ']):not([data-dsh-taskboard-view]){right:var(--cfw-right,50%) !important;max-width:100%;}',
    
    'html[' + VIEW_ATTR + '] [' + PANEL_ATTR + ']{display:flex;}',
    // 我手搓的左栏不再需要（官方界面取代它）
    '.cfw-split{position:absolute;left:0;top:0;bottom:0;width:5px;flex:none;}',
    // ===== 内嵌感：官方聊天窗口四周留白 + 圆角边框，看起来是嵌在我面板里的一块 =====
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"]{padding:10px calc(var(--cfw-right,50%) + 8px) 10px 10px !important;box-sizing:border-box;}',
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"] > *:not([' + PANEL_ATTR + ']){border:1px solid var(--dsw-alias-border-l2,rgba(128,128,128,.28));border-radius:10px;box-sizing:border-box;overflow:hidden;}',
    // 我这一侧也留 10px 外边距，并给出圆角，两侧看起来是两块并列的卡片
    // 绝对定位里 left+width 会让 right 失效 → 面板被推到屏幕外；这里明确 left:auto
    // ===== 修正：只框左边；右上角操作条放我的 UI；右半恢复原样 =====
    // 顶部留出操作条的高度；左边框住官方会话，右侧不加任何装饰
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"]{padding:44px calc(var(--cfw-right,50%) + 8px) 10px 10px !important;}',
    // ===== 面板占满整列；内部：左=透明缺口（让官方会话透出）、右=我的列表 =====
    ,   /* 缺口里不渲染我早先手搓的那套对话框 */
    // display:contents 容器不生成盒子 → 不能给它加 border/overflow（会把会话内容搞没）
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"] > *:not([' + PANEL_ATTR + ']){border:0;border-radius:0;overflow:visible;}',
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"]{padding:44px calc(var(--cfw-right,50%) + 8px) 12px 12px !important;}',
    // 顶部留白回到 10px（44px 会压坏会话内部百分比高度）；操作条只覆盖左半且按钮靠右
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"]{padding:10px calc(var(--cfw-right,50%) + 8px) 10px 10px !important;}',
    // ===== 回退：面板只占右半（不再铺满整列，避免盖住左边的会话）=====
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"]{padding:10px calc(var(--cfw-right,50%) + 8px) 10px 10px !important;}',
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"] > *:not([' + PANEL_ATTR + ']){border:1px solid var(--dsw-alias-border-l2,rgba(128,128,128,.28));border-radius:10px;box-sizing:border-box;overflow:hidden;right:var(--cfw-right,50%) !important;}',
    // ===== 右边不要卡片：面板贴边、无边框无圆角；返回按钮独立挂在左上角 =====
    '[' + PANEL_ATTR + ']{left:auto;right:0;top:0;bottom:0;width:var(--cfw-right,50%);border:0;border-radius:0;overflow:visible;pointer-events:auto;}',
    
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"]{padding:36px calc(var(--cfw-right,50%) + 8px) 8px 8px !important;}',
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"] > *:not([' + PANEL_ATTR + ']){border:1px solid var(--dsw-alias-border-l2,rgba(128,128,128,.28));border-radius:10px;box-sizing:border-box;overflow:hidden;right:var(--cfw-right,50%) !important;}',    // 左上返回按钮：小尺寸，且只在面板打开时出现（否则每个会话都会露出来）
    'html[' + VIEW_ATTR + '] .cfw-leftback,html[' + VIEW_ATTR + '] .cfw-rotateBtn{display:inline-flex;align-items:center;gap:4px;}',    // 实测：绝对定位下 width 被解析成撑满（874px）→ 写死 fit-content + right:auto 才是小按钮
    // 左上返回按钮：**默认隐藏**，只有面板打开时才显示。
    // ⚠️ 这条 `display:none` 必须在 `[data-dsh-chat-digest-view]` 那条**之前**，而且两者都不能删：
    //    2026-09-14 的"可证明等价"去重把历史上一堆 `.cfw-leftback{display:none…}` 全删了，
    //    只剩下面那条带 !important 的"打开态"，于是**关掉面板后按钮不会隐藏** ——
    //    实测：面板关掉后 `.cfw-leftback` 仍 display:block、可见、49×24 @(290,8)，
    //    表现为"返回按钮在所有会话上都显示"。去重时只看了"这次量到没变"，漏了状态切换。
    '.cfw-leftback,.cfw-rotateBtn{display:none;position:absolute;left:10px;top:8px;right:auto !important;width:fit-content !important;height:24px;padding:0 8px;font-size:12px;line-height:24px;border-radius:6px;border:0 !important;z-index:5;}',
    '.cfw-leftback{max-width:90px;}',
    '.cfw-rotateBtn{left:64px;max-width:190px;}',
    'html[' + VIEW_ATTR + '] .cfw-leftback,html[' + VIEW_ATTR + '] .cfw-rotateBtn{display:inline-flex !important;align-items:center;justify-content:center;gap:4px;}',
    // 右侧列表的顶层大标题
    '.cfw-sec{font-size:15px;font-weight:600;letter-spacing:.3px;color:var(--dsw-alias-label-primary);padding:16px 14px 6px;}',
    // 卡片边框只给"官方会话"那一支，排除返回按钮本身（它也是 centerCol 的子元素）
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"] > *:not([' + PANEL_ATTR + ']):not(.cfw-leftback):not(.cfw-rotateBtn):not(.cfw-quotebar){border:1px solid var(--dsw-alias-border-l2,rgba(128,128,128,.28));border-radius:10px;box-sizing:border-box;overflow:hidden;right:var(--cfw-right,50%) !important;}',
    // 返回按钮：无边框，挪到卡片内部（不压边框）
    // display:contents 容器不生成盒子 → 任何边框都只在顶边画出一根线（多余横线的真凶）
    // 注意必须再排除 .cfw-quotebar：灰色引用框也是 centerCol 的直接子元素，
    // 被这条规则（border:0 !important）扫到就丢了边框和圆角。
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"] > *:not([' + PANEL_ATTR + ']):not(.cfw-leftback):not(.cfw-rotateBtn):not(.cfw-quotebar){border:0 !important;border-radius:0;overflow:visible;right:var(--cfw-right,50%) !important;}',
    // 返回按钮对齐到会话区内部（会话区顶边在 y=36）
    // 返回按钮回到原位（用户：本来是好的）
    // ⚠️ `position:absolute` 必须留在这条上：历史上它只由更早那条
    //    `.cfw-leftback{position:absolute;left:8px;top:6px;z-index:5;}` 提供，
    //    2026-09-14 的"等价去重"把那条删了 —— 探针当时量到的是**已经 static 的元素**（left/top 不生效），
    //    于是把"丢定位"误判成"零影响"。实测后果：按钮从 (290,8) 掉到 (288,769)，左侧输入区被顶高 23px。
    //    教训：去重后必须逐条回比基线，不能只信"这次量到没变"。
    '.cfw-leftback{position:absolute;top:8px !important;left:10px !important;border:0 !important;right:auto !important;width:fit-content !important;max-width:90px;height:24px;padding:0 8px;font-size:12px;line-height:24px;z-index:5;}',
    '.cfw-rotateBtn{position:absolute;top:8px !important;left:64px !important;border:0 !important;right:auto !important;width:fit-content !important;max-width:190px;height:24px;padding:0 8px;font-size:12px;line-height:24px;z-index:5;}',
    // 面板裁边：任何越过面板左边界的元素（多余按钮/线）都被剪掉，不再压到分割线上
    '[' + PANEL_ATTR + ']{overflow:hidden !important;}',
    // 侧栏列表本身不要横向溢出
    '.cfw-h{box-sizing:border-box;max-width:100%;}',
    // 分割线落在真正的分界上：去掉 8px 空隙，让会话右边缘 == 面板左边缘
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"]{padding:36px var(--cfw-right,50%) 8px 8px !important;}',
    '.cfw-split{left:0;width:5px;}',
    
    // 右侧 UI 也要圆角（用户纠正：右边的 UI 没有用圆角）
    '.cfw-h{border-radius:10px 10px 0 0;}',
    '.cfw-mini{border-radius:8px;}',
    '.cfw-menu{border-radius:10px;}',
    '.cfw-mi{border-radius:6px;}',
    '.cfw-more{border-radius:6px;}',
    // 条目行/分组行也统一圆角（悬浮高亮不该是直角）
    '.cfw-item{border-radius:6px;}',
    '.cfw-card{border-radius:10px;}',
    // ===== 会话未就绪时的空白遮罩（极简版）=====
    // 必须显式覆盖 centerCol 那批 `> *:not([data-dsh-chat-digest-panel])` 规则（它们会加 right:50%、
    // 圆角、overflow:hidden，把遮罩裁成半张卡片）。pointer-events:none 是硬要求：
    // 上一版就是因为它吃了指针/判就绪失败，用户报"白屏炸了、不切会话"。
    'html[' + VIEW_ATTR + ']:not([data-dsh-taskboard-active]):not([data-dsh-ssh-active]) [class*="centerCol"] > .cfw-navcover{position:absolute;left:0;top:0;bottom:0;right:var(--cfw-right,50%);z-index:9;border:0 !important;border-radius:0 !important;box-sizing:border-box;overflow:hidden;pointer-events:none !important;}',
    '.cfw-navcover{display:none;}',
    // ===== 「刷新会话」按钮 + DSH 风格确认弹窗（token 取自运行中的 DSH，见 patch 注释）=====
    '.cfw-rotateBtn svg{width:12px;height:12px;flex:0 0 auto;}',
    '.cfw-confirm-mask{position:fixed;inset:0;z-index:2147483000;display:flex;align-items:center;justify-content:center;background:var(--dsw-alias-bg-mask-1,rgba(8,10,16,.45));}',
    '.cfw-confirm{box-sizing:border-box;width:min(440px,calc(100vw - 48px));padding:18px;border:1px solid var(--dsw-alias-border-l2,rgba(128,128,128,.28));border-radius:10px;background:var(--dsw-alias-bg-base,#fff);color:var(--dsw-alias-label-primary,#111);box-shadow:var(--dsw-shadow-lv3,0 12px 40px rgba(16,24,40,.28));font-family:inherit;}',
    '.cfw-confirm-title{margin:0 0 10px;font-size:15px;font-weight:700;line-height:1.4;}',
    '.cfw-confirm-msg{margin:0 0 16px;font-size:13px;line-height:1.6;color:var(--dsw-alias-label-secondary,#61666b);}',
    '.cfw-confirm-foot{display:flex;justify-content:flex-end;gap:10px;}',
    '.cfw-confirm-btn{cursor:pointer;border:0;border-radius:8px;padding:6px 14px;font-family:inherit;font-size:13px;font-weight:600;line-height:1.4;}',
    '.cfw-confirm-cancel{background:transparent;border:.5px solid var(--dsw-alias-border-l3,rgba(128,128,128,.45));color:var(--dsw-alias-label-primary,#111);}',
    '.cfw-confirm-cancel:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.14));}',
    '.cfw-confirm-ok{background:var(--dsw-alias-state-error-primary,#d92d20);color:#fff;}',
    '.cfw-confirm-ok:hover:not(:disabled){filter:brightness(.94);}',
    '.cfw-confirm-ok:disabled{opacity:.5;cursor:default;}',
    'html[' + VIEW_ATTR + '] .cfw-navcover{display:block;opacity:1;transition:opacity .12s linear;}',
    'html[' + VIEW_ATTR + '] .cfw-navcover.cfw-navcover-off{opacity:0;}'].join('')


  function injectStyle() {
    if (document.getElementById('chatfeed-style')) return
    var el = document.createElement('style')
    el.id = 'chatfeed-style'
    el.textContent = CSS
    document.head.appendChild(el)
  }

  // ---------------- 1) 下拉菜单（替代原底栏按钮行）----------------
  var accEl = null
  // ---------------- 内嵌折叠区（取代原来的侧栏浮层菜单）----------------
  function ensureAcc() {
    if (accEl !== null && accEl.isConnected) return
    if (entryRow === null || !entryRow.isConnected) return
    if (accEl === null || !accEl.isConnected) {
      if (document.querySelector('.cfw-acc') !== null) return
      accEl = document.createElement('div')
      accEl.className = 'cfw-acc'
      accEl.setAttribute('data-open', 'false')
      var inner = document.createElement('div')
      inner.className = 'cfw-acc-inner'
      var body = document.createElement('div')
      body.className = 'cfw-acc-body'
      inner.appendChild(body)
      accEl.appendChild(inner)
      accEl.__body = body
    }
    // 紧跟在入口行之后（同一父节点内），随入口行一起被 React 重排时由 ensureEntry 再摆一次
    if (entryRow.parentNode) entryRow.parentNode.insertBefore(accEl, entryRow.nextSibling)
  }
  function isAccOpen() { return accEl !== null && accEl.getAttribute('data-open') === 'true' }
  function syncAccLook() {
    var open = isAccOpen()
    var m = entryRow ? entryRow.querySelector('.cfw-more2') : null
    if (m) { if (open) m.classList.add('cfw-more2-on'); else m.classList.remove('cfw-more2-on') }
    // 入口行也进入"展开"外观，与折叠区连成一块，看起来就是这一栏被展开了
    if (entryRow) { if (open) entryRow.classList.add('cfw-entry-open'); else entryRow.classList.remove('cfw-entry-open') }
    // 折叠区同样切一个类：CSS 里 .cfw-acc-open 与 [data-open="true"] 是并列选择器，
    // 万一以后属性名改了也不会静默失效（历史教训：只靠一个属性/类名，改名即静默丢样式）
    if (accEl) { if (open) accEl.classList.add('cfw-acc-open'); else accEl.classList.remove('cfw-acc-open') }
  }
  function toggleAcc() {
    if (accEl === null) return
    accEl.setAttribute('data-open', isAccOpen() ? 'false' : 'true')
    syncAccLook()
    if (!isAccOpen()) closeGetMenu()        // 折叠时把「获取」悬浮菜单一起收起来
    if (isAccOpen()) { ensureAcc(); renderAcc() }
  }
  // ---- 「获取」下拉：两个提供商（2026-09-17 用户要求）----
  //   点开菜单 → 点某个提供商 → **现场探测它**（宿主 `/collect {route}` 一次请求里做完"探测 + 通了才触发"）
  //   · 探不通：按钮红底白字「获取失败」2600ms 后恢复；宿主**不触发、也不动采集指针**（上次采集时间不变）
  //   · 探得通：正常走采集（面板自动打开）
  // 线路由**宿主配置**（CFG.routes）决定 ⇒ 从 /state.routes 读（2026-09-25 通用化）。
  // 读不到时退回内置两条（旧行为），不至于因为一次请求失败就没有菜单。
  var PROVIDERS_FALLBACK = [
    // 兜底只留一条**通用**线路；真正的线路由 /state.routes 给（配置驱动）。
    { route: 'default', name: '默认线路', hint: '' },
  ]
  var PROVIDERS = PROVIDERS_FALLBACK.slice()
  function syncProviders(list) {
    if (!list || !list.length) return
    var next = list.map(function (r) {
      return { route: String(r.id), name: String(r.menuName || r.label || r.id), hint: String(r.hint || '') }
    })
    if (JSON.stringify(next) === JSON.stringify(PROVIDERS)) return
    PROVIDERS = next
    // 菜单是缓存的：线路变了就把它扔掉，下次打开按新的重建
    if (accMenu && accMenu.parentNode) { accMenu.parentNode.removeChild(accMenu); accMenu = null }
  }
  var TRI_SVG = '<svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true"><path d="M2.6 4.2h6.8L6 8.1z" fill="currentColor"/></svg>'
  var accMenu = null
  var menuOpen = false
  var menuDocBound = false
  var failTimer = 0

  function setGetLabel(btn, text) {
    if (!btn) return
    btn.textContent = ''
    var t = document.createElement('span')
    t.textContent = text
    var wrap = document.createElement('span')
    wrap.innerHTML = TRI_SVG
    btn.append(t)
    if (wrap.firstChild) btn.append(wrap.firstChild)
  }
  // **悬浮列表**（2026-09-17 用户要求：不要内嵌列表）：
  //   菜单挂在 document.body 上（position:fixed + 大 z-index）—— 因为 `.cfw-acc` / `.cfw-acc-inner`
  //   都带 overflow:hidden（折叠动画靠 grid-template-rows 0fr↔1fr），挂在折叠区里的浮层会被**裁掉**。
  //   位置每次打开时按按钮的 getBoundingClientRect() 现算：贴按钮下沿、下面放不下就翻到上方。
  function ensureMenu() {
    if (accMenu && accMenu.isConnected) return accMenu
    var menu = document.createElement('div')
    menu.className = 'cfw-tk-menu'
    menu.setAttribute('data-dsh-plugin', 'dsh-chat-digest')
    PROVIDERS.forEach(function (p) {
      var mi = document.createElement('button')
      mi.type = 'button'
      mi.className = 'cfw-tk-mi'
      mi.title = '用 ' + p.name + ' 跑这一轮：先探测它通不通；不通就不触发，采集时间也不变'
      var nm = document.createElement('span')
      nm.textContent = p.name
      var hs = document.createElement('span')
      hs.className = 'cfw-tk-mi-s'
      hs.textContent = p.hint
      mi.append(nm, hs)
      mi.addEventListener('click', function (ev) { ev.preventDefault(); ev.stopPropagation(); runCollectRoute(p.route) })
      menu.append(mi)
    })
    document.body.append(menu)
    accMenu = menu
    return menu
  }
  function placeMenu() {
    try {
      if (!accMenu || !accGetBtn || !accGetBtn.isConnected) return
      var b = accGetBtn.getBoundingClientRect()
      accMenu.style.width = Math.max(Math.round(b.width) + 44, 178) + 'px'
      accMenu.style.left = Math.round(b.left) + 'px'
      var h = accMenu.offsetHeight || 72
      var top = Math.round(b.bottom) + 4
      if (top + h > window.innerHeight - 8) top = Math.max(8, Math.round(b.top) - h - 4)
      accMenu.style.top = top + 'px'
    } catch (e) {}
  }
  function openGetMenu() {
    ensureMenu()
    menuOpen = true
    try {
      accMenu.classList.add('cfw-tk-menu-on')
      if (accGetBtn) accGetBtn.classList.add('cfw-tk-get-on')
    } catch (e) {}
    placeMenu()
    // 折叠区展开有 .32s 动画 ⇒ 按钮还在移动，隔几拍再对一次位置（否则浮层会偏几像素）
    ;[60, 180, 360].forEach(function (ms) { setTimeout(function () { if (menuOpen) placeMenu() }, ms) })
    bindMenuOutside()
  }
  function closeGetMenu() {
    menuOpen = false
    try {
      if (accMenu) accMenu.classList.remove('cfw-tk-menu-on')
      if (accGetBtn) accGetBtn.classList.remove('cfw-tk-get-on')
    } catch (e) {}
  }
  function toggleGetMenu() { if (menuOpen) closeGetMenu(); else openGetMenu() }
  // 点菜单外面就收起来（capture 阶段先跑：命中的是按钮/菜单自己就不收，交给各自的 handler）；
  // 侧栏滚动 / 窗口尺寸变了要重新定位（fixed 定位的浮层不跟手就会"飘"）。
  function bindMenuOutside() {
    if (menuDocBound) return
    menuDocBound = true
    document.addEventListener('click', function (ev) {
      if (!menuOpen) return
      var t = ev.target
      try {
        if (accMenu && accMenu.contains(t)) return
        if (accGetBtn && accGetBtn.contains(t)) return
      } catch (e) {}
      closeGetMenu()
    }, true)
    window.addEventListener('resize', function () { if (menuOpen) placeMenu() }, true)
    document.addEventListener('scroll', function () { if (menuOpen) placeMenu() }, true)
  }
  // 探不通：红底白字「获取失败」闪一下再恢复（**不动 store.lastCollectAt** —— 那个只有宿主真触发一轮才会变）
  function flashGetFail(msg) {
    try {
      if (!accGetBtn || !accGetBtn.isConnected) return
      if (failTimer) { clearTimeout(failTimer); failTimer = 0 }
      setGetLabel(accGetBtn, '获取失败')
      accGetBtn.classList.add('cfw-tk-fail')
      accGetBtn.title = msg || '探测不通：这一轮没触发，采集时间也没变'
      failTimer = setTimeout(function () {
        failTimer = 0
        try {
          if (!accGetBtn || !accGetBtn.isConnected) return
          accGetBtn.classList.remove('cfw-tk-fail')
          setGetLabel(accGetBtn, store.busy ? '采集中…' : '获取')
        } catch (e) {}
      }, 2600)
    } catch (e) {}
  }
  function runCollectRoute(route) {
    if (store.busy) return
    closeGetMenu()
    try {
      if (accGetBtn && accGetBtn.isConnected) { accGetBtn.disabled = true; setGetLabel(accGetBtn, '探测中…') }
    } catch (e) {}
    call('POST', 'collect', { route: route }).then(function (r) {
      if (!r || r.ok === false) {
        try { if (accGetBtn && accGetBtn.isConnected) accGetBtn.disabled = !!store.busy } catch (e) {}
        flashGetFail((r && r.error) || '探测不通：这一轮没触发')
        return
      }
      store.busy = true
      try { render() } catch (e) {}
      openPanel()
    }).catch(function (e) {
      try { if (accGetBtn && accGetBtn.isConnected) accGetBtn.disabled = false } catch (e2) {}
      flashGetFail('请求失败：' + String((e && e.message) || e))
    })
  }

  function renderAcc() {
    if (accEl === null || !accEl.__body) return
    var body = accEl.__body
    // 按钮左边缘对齐入口的 **SVG 图标**（2026-09-17 用户要求：「两个按钮左对齐 svg 即可，不用再对齐上面的字」）
    //   （原来对齐的是「聊天摘要」四个字的左边缘 —— 改取 .cfw-entryIco）
    try {
      var lbl = entryRow ? entryRow.querySelector('.cfw-entryIco') : null
      if (lbl && entryRow) {
        var off = lbl.getBoundingClientRect().left - entryRow.getBoundingClientRect().left
        if (off > 0) body.style.paddingLeft = Math.round(off) + 'px'
      }
    } catch (e) {}
    body.innerHTML = ''
    var s = store
    var row = document.createElement('div')
    row.className = 'cfw-tk-row'
    var getBtn = document.createElement('button')
    getBtn.type = 'button'
    getBtn.className = 'cfw-tk cfw-tk-get'
    getBtn.disabled = !!s.busy
    setGetLabel(getBtn, s.busy ? '采集中…' : '获取')
    getBtn.title = (s.busy ? '采集中…' : '获取：点开选一个提供商 —— 先探测它通不通，通了才跑这一轮')
      + '（上次采集 ' + (s.lastCollectAt ? stamp(s.lastCollectAt) + '，已过 ' + hhmm(s.lastCollectAt) : '--') + '）'
    getBtn.addEventListener('click', function (ev) { ev.preventDefault(); ev.stopPropagation(); toggleGetMenu() })
    accGetBtn = getBtn
    var autoBtn = document.createElement('button')
    autoBtn.className = 'cfw-tk' + (s.auto ? ' cfw-tk-on' : '')
    autoBtn.textContent = s.auto ? '自动 ✓' : '自动'
    autoBtn.title = (s.auto
      ? 'Auto 已开启：每天 ' + s.autoTime + ' 自动采集，点击关闭'
      : 'Auto 已关闭：点击开启，每天 ' + s.autoTime + ' 自动采集')
      + '。判据是「当前时间 ≥ ' + s.autoTime + ' 且今天还没采集过」→ **已过点时才打开，会立刻补跑一轮**'
    autoBtn.addEventListener('click', function () {
      call('POST', 'set-auto', { on: !store.auto }).catch(function (e) { console.error('[dsh-chat-digest] set-auto', e) })
    })
    // 2026-09-13 实测：这一行的下半截与侧栏「工作区」区域头部的按钮（`.bhn1Oq_searchButton` /
    //   `.bhn1Oq_iconButton`，x 194–258）**同一块地方** → 控件要**贴着左侧**放（右边放什么都点不到）。
    //   所以这一行只有三个控件：获取（下拉）、自动、只读的"上次采集"。
    var el2 = document.createElement('span')
    el2.className = 'cfw-tk-el'
    // **主显"采集于哪一刻"（绝对时间），不显"已过多久"**（2026-09-15 用户实测教训）：
    //   这一行只在 `isAccOpen()` 时才重建（render() 的门禁），折叠着就**冻住**；
    //   冻住的"时长"永远不对，冻住的"绝对时间"却始终正确。时长挪进 title，并随 render 廉价刷新。
    el2.textContent = s.lastCollectAt ? stamp(s.lastCollectAt) : '--'
    el2.title = s.lastCollectAt
      ? ('上次采集：' + stamp(s.lastCollectAt) + '（已过 ' + hhmm(s.lastCollectAt) + '；自动时间见面板里的设置行）')
      : '还没采集过（自动时间见面板里的设置行）'
    accEl2 = el2
    row.append(getBtn, autoBtn, el2)
    body.append(row)
    // 悬浮菜单挂在 body 上（见 ensureMenu）。按钮被重建后位置会变 ⇒ 菜单还开着就重新定位一次。
    if (menuOpen) { ensureMenu(); placeMenu() }
  }

  // 只更新"上次采集"那行文字，不重建整行（重建要走 renderAcc()，而它被展开状态门禁着）。
  // 每次 render() 都调一次 → 时长会跟着 15 秒轮询走；而主显的绝对时间本来就不怕冻。
  function syncAccTime() {
    var s = store
    // 折叠了 / 换了视图就**别在屏幕角落留一个浮层**（悬浮菜单挂在 body 上，不跟着折叠区一起消失）
    if (!isAccOpen() && menuOpen) closeGetMenu()
    var txt = s.lastCollectAt ? stamp(s.lastCollectAt) : '--'
    var tip = s.lastCollectAt
      ? ('上次采集：' + stamp(s.lastCollectAt) + '（已过 ' + hhmm(s.lastCollectAt) + '；自动时间见面板里的设置行）')
      : '还没采集过（自动时间见面板里的设置行）'
    try {
      if (accEl2 && accEl2.isConnected) { if (accEl2.textContent !== txt) accEl2.textContent = txt; accEl2.title = tip }
      if (accGetBtn && accGetBtn.isConnected) {
        if (!accGetBtn.classList.contains('cfw-tk-fail')) {     // 「获取失败」闪红期间别被 title 刷掉
          accGetBtn.title = (s.busy ? '采集中…' : '获取：点开选一个提供商 —— 先探测它通不通，通了才跑这一轮')
            + '（上次采集 ' + (s.lastCollectAt ? stamp(s.lastCollectAt) + '，已过 ' + hhmm(s.lastCollectAt) : '--') + '）'
        }
      }
    } catch (e) {}
  }

  // 【保留但已无调用方】2026-09-17：「获取」改成"选提供商"下拉后，按钮走 runCollectRoute(route)。
  //   留着它是因为它是"不指定线路、由宿主按探测结果自己选"的那条老路径（面板/以后别的入口可能还要）。
  function runCollect() {
    if (store.busy) return
    store.busy = true
    call('POST', 'collect', {}).then(function (r) {
      // 2026-09-13：/collect 现在真的会触发一轮，失败会带 error（如"上一轮还在跑"）→ 显示出来，别静默
      if (r && r.ok === false) { store.busy = false; if (r.error) store.note = r.error; render(); return }
      openPanel()
    })
      .catch(function (e) { console.error('[dsh-chat-digest] collect', e) })
  }

  // ---------------- 2) sidebar entry ----------------
  function sidebarRoot() {
    var column = document.querySelector('[data-pane="sidebar"], [class*="sidebarCol"]')
    if (column === null) return null
    var logo = column.querySelector('[class*="logoRow"]')
    return (logo !== null && logo.parentElement) || column.firstElementChild
  }
  function buildEntry() {
    // 2026-09-13 更正（用户指出）：`data-dsh-part="sidebar-entry"` 是**多个插件共用的属性名**
    //   （任务看板 / 记忆系统 / 技能中心 … 都用它），页面里同时有 4 个是正常的。
    //   ⚠ 曾经在这里写过"清掉旧的"——那会**误删别的插件的入口**，已回退，别再犯。
    //   我们自己的入口要靠 id 类属性区分（见下面的 ENT_ATTR）。
    var btn = document.createElement('button')
    btn.type = 'button'
    btn.setAttribute(ENT_ATTR, '')
    btn.setAttribute('data-dsh-plugin', 'dsh-chat-digest')
    btn.setAttribute('data-dsh-part', 'sidebar-entry')
    btn.setAttribute('aria-label', '聊天摘要')
    btn.title = '聊天摘要：采集聊天记录并更新条目'
    btn.className = 'cfw-entry'
    var ico = document.createElement('span')
    ico.className = 'cfw-entryIco'
    ico.innerHTML = CHAT_SVG
    var lbl = document.createElement('span')
    lbl.className = 'cfw-entryLbl'
    lbl.textContent = '聊天摘要'
    // 右端 ⋯：点开下拉菜单（获取/自动/计时）。stopPropagation 防止触发行本身的点击。
    var more = document.createElement('span')
    more.className = 'cfw-more2'
    more.innerHTML = '<svg viewBox="0 0 14 14" width="14" height="14" fill="none" aria-hidden="true"><path d="M4.25 2.82782L4.25 11.1722C4.25 11.6622 4.84243 11.9076 5.18891 11.5611L9.36109 7.38891C9.57588 7.17412 9.57588 6.82588 9.36109 6.61109L5.18891 2.43891C4.84243 2.09243 4.25 2.33782 4.25 2.82782Z" fill="currentColor"/></svg>'
    more.title = '聊天摘要：获取 / 自动'
    more.setAttribute('role', 'button')
    more.addEventListener('click', function (ev) {
      ev.preventDefault()
      ev.stopPropagation()
      toggleAcc()
    })
    btn.append(ico, lbl, more)
    btn.addEventListener('click', function () { openPanel() })
    return btn
  }
  // 复制同族入口（任务看板/记忆系统/技能中心）的实测样式，保证字体/字号/缩进完全一致。
  // 注意：不能用 span[i] 位置取标签 —— 参考 DOM 结构是 [span_icon, svg, ..., span_label]，
  // 位置假设曾导致取到 svg 子节点、复制静默失败、退回类里的兜底字号（实测差 1px、缩进差 6px）。
  // 改为按 class 语义查找。**类名一旦取不到，就用实测值兜底**（见 CSS 的 .cfw-entry）。
  function syncEntryStyle() {
    if (entryRow === null) return
    var ref = document.querySelector('[data-dsh-taskboard-entry]') ||
      document.querySelector('[data-dsh-mnemon-entry]') ||
      document.querySelector('[data-dsh-skill-explorer-entry]')
    if (ref === null) return
    try {
      var cs = getComputedStyle(ref)
      ;['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'paddingTop', 'paddingBottom', 'paddingLeft', 'paddingRight', 'marginTop', 'marginBottom', 'gap', 'borderRadius'].forEach(function (k) {
        var v = cs[k]
        if (v && v !== 'normal' && v !== 'auto' && v !== '0px' && v !== '0s') entryRow.style[k] = v
      })
      var refIco = ref.querySelector('[class*="entryIcon"]')
      var ico = entryRow.querySelector('.cfw-entryIco')
      if (refIco !== null && ico !== null) {
        var ci = getComputedStyle(refIco)
        if (ci.width) ico.style.width = ci.width
        if (ci.height) ico.style.height = ci.height
      }
      // 标签：按 class 语义找（后缀 entryLabel），找不到再退回"最后一个"非图标 span
      var refLbl = ref.querySelector('[class*="entryLabel"]')
      if (refLbl === null) {
        var spans = Array.prototype.filter.call(ref.querySelectorAll('span'), function (s) {
          return s.querySelector('svg') === null && s.children.length === 0
        })
        refLbl = spans.length ? spans[spans.length - 1] : null
      }
      var lbl = entryRow.querySelector('.cfw-entryLbl')
      if (refLbl !== null && lbl !== null) {
        var cl = getComputedStyle(refLbl)
        if (cl.fontSize) lbl.style.fontSize = cl.fontSize
        if (cl.fontFamily) lbl.style.fontFamily = cl.fontFamily
        if (cl.lineHeight && cl.lineHeight !== 'normal') lbl.style.lineHeight = cl.lineHeight
      }
    } catch (e) { /* 拿不到就用 CSS 里的实测兜底值 */ }
  }
  function ensureEntry() {
    if (entryRow !== null && entryRow.isConnected) return
    if (entryRow === null || !entryRow.isConnected) {
      if (document.querySelector('[' + ENT_ATTR + ']') !== null) return
      entryRow = buildEntry()
    }
    var root = sidebarRoot()
    if (root === null) return
    var ns = root.querySelector('button[class*="newSession"]')
    if (ns === null) return
    var row = ns.closest('[class*="logoRow"]')
    var base = (row !== null && row.parentElement === root) ? row : ns
    var family = Array.prototype.filter.call(root.children, function (el) {
      return el.matches && el.matches(FAMILY)
    })
    var anchor = family.length > 0 ? family[family.length - 1].nextElementSibling : base.nextElementSibling
    root.insertBefore(entryRow, anchor)
    syncEntryStyle()
    ensureAcc()
  }

  // ---------------- 3) center panel ----------------
  // ---------------- 左右分栏：可拖动分隔线（默认 1:1）----------------
  var splitPct = 50
  try {
    var savedSplit = parseFloat(localStorage.getItem('cfw-split'))
    if (!isNaN(savedSplit) && savedSplit >= 25 && savedSplit <= 75) splitPct = savedSplit
  } catch (e) {}
  function applySplit() {
    if (panelEl === null) return
    try {
      panelEl.style.setProperty('--cfw-split', splitPct + '%')
      // --cfw-right = 我的面板占的宽度；必须设在 documentElement 上才能被 centerCol 继承
      document.documentElement.style.setProperty('--cfw-right', (100 - splitPct) + '%')
    } catch (e) {}
  }
  var dragging = false
  function onSplitDown(ev) {
    if (panelEl === null) return
    if (ev) { ev.preventDefault(); ev.stopPropagation() }
    var bar = ev && ev.currentTarget
    if (bar && bar.classList) bar.classList.add('cfw-drag')
    dragging = true
    try { document.body.classList.add('cfw-dragging') } catch (e) {}
    var host = panelEl.parentElement || panelEl   // centerCol：比例以整列为基准
    var rect = host.getBoundingClientRect()       // 拖动期间尺寸不变，量一次即可
    var raf = null
    var pendingX = null
    var flush = function () {
      raf = null
      if (pendingX === null || rect.width <= 0) return
      var pct = ((pendingX - rect.left) / rect.width) * 100
      // 关键：不要 Math.round —— 取整到 1% 在 1100px 宽的面板上相当于每步跳 11px
      splitPct = Math.max(25, Math.min(75, Math.round(pct * 100) / 100))
      applySplit()
    }
    var move = function (e) {
      pendingX = e.clientX
      if (raf !== null) return
      raf = requestAnimationFrame(flush)        // 一帧只应用一次，避免逐事件重排
    }
    var up = function () {
      if (raf !== null) { try { cancelAnimationFrame(raf) } catch (e) {} ; raf = null }
      dragging = false
      try { document.body.classList.remove('cfw-dragging') } catch (e) {}
      if (bar && bar.classList) bar.classList.remove('cfw-drag')
      document.removeEventListener('pointermove', move)
      document.removeEventListener('pointerup', up)
      try { localStorage.setItem('cfw-split', String(splitPct)) } catch (e) {}
    }
    onEvt(document, 'pointermove', move)
    onEvt(document, 'pointerup', up)
  }

  function ensurePanel() {
    if (panelEl !== null && panelEl.isConnected) return
    var column = document.querySelector('[data-pane="conversation"], [class*="centerCol"]')
    if (column === null) return
    if (panelEl === null || !panelEl.isConnected) {
      panelEl = document.createElement('div')
      panelEl.setAttribute(PANEL_ATTR, '')
      panelEl.setAttribute('data-dsh-plugin', 'dsh-chat-digest')
      var right = document.createElement('div')
      right.className = 'cfw-right'
      var rh = document.createElement('div')
      rh.className = 'cfw-h cfw-hr'
      var backRight = document.createElement('button')
      backRight.type = 'button'
      backRight.className = 'cfw-mini'
      backRight.setAttribute('data-dsh-center-view-back', '')
      backRight.textContent = '\u2039 返回'
      backRight.title = '关闭聊天摘要，回到会话'
      backRight.addEventListener('click', function () { closePanel() })
      var rtitle = document.createElement('span')
      var clr = document.createElement('button')
      clr.className = 'cfw-mini'
      // 2026-09-13：原来它叫「清理已完成」、位于标题栏、**一点就把所有已勾选条目直接删掉**（不确认、不留档），
      // 用户问"这是什么鬼"。现在：① 说明后果 + 两步确认；② **标签带已勾选条数**（删完变「无已勾选」并禁用），
      // 这样他知道"这一轮能不能删了、下一轮什么时候能删"；③ 移到不滚动的横条里、和自动时间同一行。
      clr.textContent = '无已勾选'
      clr.title = '把面板上所有已勾选的条目删掉（待办勾＝已完成 / 有用信息勾＝已知晓）。'
        + '平时不用它 —— 每天那轮会先把已勾选的列成清单问你要不要删，删的会留档。'
      clr.setAttribute('data-cfw-clear', '')
      var armed = false, armedTimer = null
      clr.addEventListener('click', function () {
        var n = countDone()
        if (!n) return                                   // 没有已勾选的：禁用态，点了也不动
        if (!armed) {
          armed = true
          clr.textContent = '确认删除 ' + n + ' 条？'
          if (armedTimer) clearTimeout(armedTimer)
          armedTimer = setTimeout(function () { armed = false; syncBar() }, 3000)
          return
        }
        if (armedTimer) clearTimeout(armedTimer)
        armed = false
        clr.textContent = '删除中…'
        clr.disabled = true
        clr.__busy = true
        call('POST', 'item', { action: 'clear-done' }).then(function (r) {
          clr.disabled = false
          clr.__busy = false
          clr.textContent = '已删 ' + n + ' 条'
          setTimeout(function () { try { refresh() } catch (e) {} }, 700)   // 700ms 后回读 → 变「无已勾选」
        }).catch(function (e) { clr.disabled = false; clr.__busy = false; console.error(e); syncBar() })
      })
      // 自动时间行由 right.js 渲染进这个槽（它只往里塞自己的节点，不清空 → 不会把上面的按钮冲掉）
      var autoSlot = document.createElement('div')
      autoSlot.className = 'cfw-rslot'
      var rbar = document.createElement('div')
      rbar.className = 'cfw-rbar'
      clr.style.marginLeft = 'auto'                       // 删除按钮靠右
      rbar.append(autoSlot, clr)
      barSlot = autoSlot
      barEl = rbar
      clrEl = clr
      listEl = document.createElement('div')
      listEl.className = 'cfw-rbody'
      // 2026-09-13：**不再挂那个空的标题栏 rh** —— 它的内容（返回/清理按钮）都搬走了，
      // 留着只会是一条空白带 + 一条多余的分割线（用户截图问"上面空一栏/上面的分割线干什么"）。
      // "返回"另有 leftBackBtn（独立挂在中央列左上角），关面板的能力不受影响。
      right.append(rbar, listEl)
      var splitter = document.createElement('div')
      splitter.className = 'cfw-split'
      splitter.title = '拖动调整左右比例'
      splitter.addEventListener('pointerdown', onSplitDown)
      panelEl.append(splitter, right)
      // 独立的左上角返回按钮：挂在中央列上（不属于面板，避免铺满整列盖住左边的会话）
      leftBackBtn = document.createElement('button')
      leftBackBtn.type = 'button'
      leftBackBtn.className = 'cfw-mini cfw-leftback'
      // 注意：不要加 data-dsh-center-view-back —— DSH 会据此套上大号返回按钮样式
      leftBackBtn.textContent = '\u2039 返回'
      leftBackBtn.title = '关闭聊天摘要，回到会话'
      leftBackBtn.addEventListener('click', function () { closePanel() })
      // 「刷新会话」：放在返回旁边（同一个左上角操作区）。图标是内联 SVG，不引外部资源。
      rotateBtn = document.createElement('button')
      rotateBtn.type = 'button'
      rotateBtn.className = 'cfw-mini cfw-rotateBtn'
      rotateBtn.setAttribute('data-cfw-rotate', '')
      rotateBtn.innerHTML = ICON_ROTATE
      var rotateLabel = document.createElement('span')
      rotateLabel.textContent = '刷新会话'
      rotateBtn.appendChild(rotateLabel)
      rotateBtn.title = '刷新会话：归档当前主 agent 会话并新建一个'
      rotateBtn.addEventListener('click', function (ev) {
        if (ev && ev.stopPropagation) ev.stopPropagation()
        openRotateConfirm()
      })
      if (column) column.appendChild(leftBackBtn)
      if (column) column.appendChild(rotateBtn)
      // 左上操作条：返回等 UI 放这里（只占左边，不动右侧列表）
      panelEl.__rtitle = rtitle
    }
    var host = column.querySelector('[' + PANEL_ATTR + ']')
    if (host === null) column.appendChild(panelEl)
    else if (host !== panelEl) { host.parentNode.removeChild(host); column.appendChild(panelEl) }
    if (getComputedStyle(column).position === 'static') column.style.position = 'relative'
    applySplit()
    renderPanel()
  }
  /* ---------------- 「刷新会话」确认框（DSH 风格） ---------------- */
  function closeRotateConfirm() {
    try { if (confirmEl && confirmEl.parentNode) confirmEl.parentNode.removeChild(confirmEl) } catch (e) {}
    confirmEl = null
    try { document.removeEventListener('keydown', onConfirmKey, true) } catch (e) {}
  }
  function onConfirmKey(ev) {
    if (!confirmEl) return
    if (ev.key === 'Escape') { closeRotateConfirm(); return }
    if (ev.key === 'Enter') {
      var ok = confirmEl.querySelector('.cfw-confirm-ok')
      if (ok && !ok.disabled) { ok.click() }
    }
  }
  function openRotateConfirm() {
    if (confirmEl) return
    // ⚠ 这里**不要**再 rebase：此刻插件已经展开过「聊天摘要」，把当时的样子记成基线 = 记住变形后的状态。
    var mask = document.createElement('div')
    mask.className = 'cfw-confirm-mask'
    mask.setAttribute('data-cfw-confirm', '')
    var box = document.createElement('div')
    box.className = 'cfw-confirm'
    box.setAttribute('role', 'dialog')
    box.setAttribute('aria-modal', 'true')
    box.setAttribute('aria-label', '刷新会话')
    var h = document.createElement('div')
    h.className = 'cfw-confirm-title'
    h.textContent = '刷新会话'
    var p = document.createElement('div')
    p.className = 'cfw-confirm-msg'
    p.textContent = '会归档当前这个主 agent 会话，并新建一个空会话（旧会话的聊天记录不会删除，只是收进归档）。确定继续？'
    var foot = document.createElement('div')
    foot.className = 'cfw-confirm-foot'
    var cancel = document.createElement('button')
    cancel.type = 'button'
    cancel.className = 'cfw-confirm-btn cfw-confirm-cancel'
    cancel.textContent = '取消'
    var ok = document.createElement('button')
    ok.type = 'button'
    ok.className = 'cfw-confirm-btn cfw-confirm-ok'
    ok.textContent = '确认刷新'
    cancel.addEventListener('click', function (ev) { if (ev) ev.stopPropagation(); closeRotateConfirm() })
    ok.addEventListener('click', function (ev) {
      if (ev) ev.stopPropagation()
      if (rotateBusy) return
      rotateBusy = true
      ok.disabled = true
      ok.textContent = '正在刷新…'
      rotateSession().then(function (r) {
        rotateBusy = false
        closeRotateConfirm()
        if (!r || !r.ok) {
          store.err = '刷新会话失败：' + String((r && r.error) || '未知错误')
          render()
          return
        }
        // 归档+新建都成功了 → 关面板、等它的还原跑完第一趟，再重开挂到新会话上。
        var newId = String(r.sessionId || '')
        closePanel()
        navEpoch += 1
        navTimers.push(setTimeout(function () {
          openPanel()
          // 重开之后确认"选中的是新会话那一行"：closePanel 的异步还原可能追到这里把它拽回旧会话。
          var wantTitle = String(store.sessionTitle || '聊天摘要 · 主 Agent')
          var tries = 0
          var ensureSel = function () {
            tries++
            try {
              var rows = document.querySelectorAll('[class*="sessionRow"]')
              var cur = ''
              for (var i = 0; i < rows.length; i++) {
                if (rows[i].getAttribute('aria-selected') === 'true') { cur = String(rows[i].textContent || ''); break }
              }
              var okNow = cur && (cur.indexOf(wantTitle) >= 0)
              if (!okNow) {
                for (var j = 0; j < rows.length; j++) {
                  if ((rows[j].textContent || '').indexOf(wantTitle) >= 0) { realClick(rows[j]); break }
                }
              }
            } catch (e) {}
            if (tries < 6) navTimers.push(setTimeout(ensureSel, 350))
          }
          navTimers.push(setTimeout(ensureSel, 600))
        }, 260))
      })
    })
    // 点遮罩空白处关闭
    mask.addEventListener('click', function (ev) { if (ev.target === mask) closeRotateConfirm() })
    foot.append(cancel, ok)
    box.append(h, p, foot)
    mask.append(box)
    document.body.appendChild(mask)
    confirmEl = mask
    try { document.addEventListener('keydown', onConfirmKey, true) } catch (e) {}
    try { ok.focus() } catch (e) {}
  }
  // 真正干活：交给 Host 一次原子操作（归档旧会话 + 新建 + rebase 锚点 + 给新会话排唤醒）
  function rotateSession() {
    var oldId = store.sessionId || sessionId || ''
    return call('POST', 'rotate', { sessionId: oldId }).then(function (r) {
      if (r && r.ok && r.sessionId) {
        sessionId = String(r.sessionId)
        store.sessionId = sessionId
        if (r.sessionTitle) store.sessionTitle = String(r.sessionTitle)
        try { if (window.__cfwRight && window.__cfwRight.clearQuote) window.__cfwRight.clearQuote() } catch (e) {}
      }
      return r
    }).catch(function (e) { return { ok: false, error: String((e && e.message) || e) } })
  }

  function setEntryActive(on) {
    try { if (entryRow) entryRow.setAttribute('data-active', on ? 'true' : 'false') } catch (e) {}
  }
  // 专属会话（主 agent 的对话窗口）：按需创建，然后切过去
  var sessionId = ''
  function applySessionResp(r) {
    if (r && r.ok && r.sessionId) {
      sessionId = String(r.sessionId)
      store.sessionId = sessionId
      // Host 的 /ss 返回的是 sessionTitle（不是 title）——以前读 r.title 永远读到空，
      // 于是 openNativeSession 一直用兜底标题找行；会话被改名就再也找不到。
      if (r.sessionTitle || r.title) store.sessionTitle = String(r.sessionTitle || r.title)
      render()
      return sessionId
    }
    store.err = (r && r.error) || '无法创建专属会话'
    render()
    return ''
  }
  // /tell 只解析、不创建（Host v30 起）。blank 的会话会被 DSH 从侧栏隐藏，点不开，
  // 这时用 \u002fsay 发一条唤醒文案（它跑过一个 turn 后 blank 变 false，侧栏就有那一行了）。
  // 之所以不再无脑调 /ss：/ss 在"会话不存在"时会**新建**一个，而新建的会话天然是 blank，
  // 于是在打开面板的路径上多留一个没人看的空会话。
  function tellSession() {
    return api('POST', 'tell', {}).then(function (r) {
      if (!r || !r.ok) return { ok: false }
      // ⚠ 这里原来会在 blank 时补发一条 wakeText —— 那是"每点一次入口就往主 agent 里多发一条
      //   初始化说明"的真凶之一（用户 2026-09-13 报）。唤醒交给 Host 的 /ss：它用
      //   `needWake` + `S.seeded` 记账，只发一次；前端再补一份就是重复。
      // 保留一条 debug 线索：blank 的会话会走 /ss 的 needWake 分支。
      return r
    }).catch(function () { return { ok: false } })
  }
  function ensureSession() {
    // 每次都问 Host 要最新 id：Host 会自愈（归档/被删 → 重建），缓存会过期
    return tellSession().then(function (t) {
      // 已有且非 blank：直接用（免掉 /ss 的一次 ensureSession 往返，也不会误建空会话）
      if (t && t.ok && t.sessionId && t.exists && !t.blank) {
        store.sessionId = String(t.sessionId)
        render()
        return String(t.sessionId)
      }
      return api('POST', 'ss', {}).then(applySessionResp)
    }).catch(function (e) {
      store.err = 'ensure-session 失败：' + String((e && e.message) || e)
      render()
      return ''
    })
  }
  // 实测：element.click() 在 DSH 侧栏行上不生效，必须派发真实事件序列
  //
  // 这里同时负责"让 onDocClick 知道这次点击是插件自己发起的"。以前用的是**全局时间窗**
  // navGuardOn(2500)：插件切完会话后的 2.5 秒内，用户点侧栏任何一行都会被一起忽略 ——
  // 表现就是"面板刚打开（或刚切完）时点别的会话，面板关不掉"，而且**概率触发**（看手速）。
  // 2026-09-14 实测：面板打开后立刻点另一行 → 属性摘掉又被守卫吞掉、面板照旧开着。
  //
  // 改成**按元素打标记**：只忽略"被插件点过的那一行"上的那一次点击，其余点击一律按用户意图处理。
  // 这样既不会自我关闭，也不会吞用户的点击。
  var CLICK_MARK = 'data-cfw-plugin-click'
  function realClick(node) {
    // 同样要临时摘掉 data-dsh-chat-digest-view：热重载可能留下上一版 ui.js 的 document 监听，
    // 它一看到属性在，就会把"插件自己切会话的这次点击"当成用户点击而关掉面板。
    var root = document.documentElement
    var had = root.hasAttribute(VIEW_ATTR)
    if (had) root.removeAttribute(VIEW_ATTR)
    var marked = false
    try { if (node && node.setAttribute) { node.setAttribute(CLICK_MARK, String(Date.now())); marked = true } } catch (e) {}
    try {
      var types = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']
      for (var i = 0; i < types.length; i++) {
        node.dispatchEvent(new MouseEvent(types[i], { bubbles: true, cancelable: true, view: window }))
      }
      return true
    } catch (e) { return false } finally {
      if (had) root.setAttribute(VIEW_ATTR, '')
      if (marked) { try { node.removeAttribute(CLICK_MARK) } catch (e) {} }
    }
  }
  // 找到"官方输入框"：中央列里可见的大 textarea（或 contenteditable）
  function officialComposer() {
    try {
      var col = document.querySelector('[class*="centerCol"]')
      if (!col) return null
      var tas = col.querySelectorAll('textarea')
      for (var i = 0; i < tas.length; i++) {
        var r = tas[i].getBoundingClientRect()
        if (r.width > 120 && r.height > 0) return tas[i]
      }
      var ce = col.querySelector('[contenteditable="true"]')
      if (ce) return ce
    } catch (e) {}
    return null
  }
  // 把文本写进官方输入框（native setter + input 事件，React 收得到）
  // 这一行是不是"当前已选中"的会话。
  // 用来避免"已经在主 agent 会话里、还去点它" —— 那次点击会让 DSH 重新加载并重渲染整个会话，
  // 实测约 1 秒；而刷新页面后 DSH 恢复的往往正是主 agent 会话，所以这一条命中率很高。
  function isRowActive(el) {
    try {
      if (!el) return false
      if (el.getAttribute('aria-selected') === 'true') return true
      if (el.getAttribute('data-active') === 'true') return true
      if (/active|selected/i.test(String(el.className || ''))) return true
      // 有些实现把选中态放在子节点上（如内部的高亮层）
      var inner = el.querySelector('[class*="active"],[class*="selected"],[aria-selected="true"]')
      return inner !== null
    } catch (e) { return false }
  }

  function openNativeSession(id, epoch) {
    if (epoch !== undefined && epoch !== navEpoch) return false   // 迟到的续作：面板已关/已重开，别动
    navClickDone = false
    wsExpanded = false
    var want = store.sessionTitle || '聊天摘要 · 主 Agent'
    // ① 优先用 Cordis client 半边提供的桥（最可靠，但刷新页面后会失效）
    try {
      if (typeof window.__chatfeedOpenSession === 'function') {
        if (window.__chatfeedOpenSession(String(id)) !== false) return true
      }
    } catch (e) {}
    // ② DOM 兜底：列表异步刷新 / 被折叠，所以先展开，再重试多次
    var clickRow = function () {
      if (navClickDone) return false          // 整个切换只点一次，避免重复切换
      // 这里原来还有 navGuardOn(2500)。已删除：它用全局时间窗去"别让 onDocClick 把插件自己的点击
      // 当成用户点击"，代价是把用户在这 2.5 秒里的点击也吞了（面板关不掉的根因）。
      // 现在由 realClick 给被点的那一行打 CLICK_MARK，只忽略那一次点击。
      // 0) 工作区行默认是折叠的 → 会话行压根不在 DOM 里，先把「聊天摘要」工作区展开
      // 先确认目标行在不在；只有"确实看不到"时才点工作区行（它是折叠开关，乱点会把展开的收起）
      var targetVisible = false
      try {
        var pre = document.querySelectorAll('[class*="sessionRow"]')
        for (var q = 0; q < pre.length; q++) {
          if ((pre[q].textContent || '').indexOf(want) >= 0) { targetVisible = true; break }
        }
      } catch (e) {}
      // 只在"确实看不到目标行"时展开，而且**一次面板会话只展开一次**（wsExpanded 由 openPanel 重置）。
      // 这里点的就是"聊天摘要"工作区行 —— 它会改变用户侧栏的展开态，所以关面板时要按 savedTree 还原。
      if (!targetVisible && !wsExpanded) {
        try {
          var projs = document.querySelectorAll('[class*="projectRow"]')
          for (var p = 0; p < projs.length; p++) {
            // 工作区行按**文本**匹配 ⇒ 改名后必须新旧都认：老工作区还叫旧名（宿主下次 ensureSession 才会改过来），
            // 只认新名会让这段永远匹配不到 ⇒ 展开不了工作区 ⇒ 找不到会话行（2026-09-25 实测踩过）。
            var wsNames = ['聊天摘要', '聊天情报'];
            if (wsNames.some(function (t) { return (projs[p].textContent || '').indexOf(t) >= 0 })) {
              wsExpanded = true
              realClick(projs[p])
              return false        // 展开后由观察器再跑一次，这次就能找到会话行
            }
          }
        } catch (e) {}
      }
      try {
        var more = document.querySelectorAll('button[class*="Overflow"], button[class*="overflow"]')
        for (var k = 0; k < more.length; k++) {
          var mt = more[k].textContent || ''
          if (mt.indexOf('展开') >= 0) { realClick(more[k]); break }
        }
      } catch (e) {}
      // ① 先只看会话行，且必须含完整标题
      try {
        var rows = document.querySelectorAll('[class*="sessionRow"]')
        for (var i = 0; i < rows.length; i++) {
          if ((rows[i].textContent || '').indexOf(want) >= 0) {
            // 已经是当前会话就别再点：点一下会让 DSH 把整个会话重新加载/重渲染一次（实测约 1 秒白等）。
            // 刷新后 DSH 恢复的往往就是主 agent 会话，所以这条命中率很高。
            if (isRowActive(rows[i])) { navClickDone = true; return true }
            navClickDone = true; realClick(rows[i]); return true
          }
        }
      } catch (e) {}
      // ② 退一步：任何 treeitem，但排除工作区行（它的文字可能恰好就是「聊天摘要」，点它只会折叠工作区）
      try {
        var any = document.querySelectorAll('[role="treeitem"]')
        for (var k2 = 0; k2 < any.length; k2++) {
          var node = any[k2]
          try { if (node.closest('[class*="projectRow"]') !== null) continue } catch (e2) {}
          if ((node.textContent || '').indexOf(want) >= 0) {
            if (isRowActive(node)) { navClickDone = true; return true }
            navClickDone = true; realClick(node); return true
          }
        }
      } catch (e) {}
      return false
    }
    if (clickRow()) return true
    // 侧栏是异步更新的：用观察器等那一行出现（最多 18 秒），比定时轮询可靠
    var settled = false
    var finish = function (ok) {
      if (settled) return
      settled = true
      clearNavWatch()   // 观察器 + 两个定时器一起撤（关面板时也调它）
      if (!ok) {
        store.err = '还没能自动切到「' + want + '」——它已经建好了，稍后再点一次入口，或直接在侧栏点开它即可。'
        render()
      }
    }
    try {
      navObs = new MutationObserver(function () {
        if (epoch !== navEpoch) return
        if (clickRow()) finish(true)
      })
      navObs.observe(document.body, { childList: true, subtree: true })
    } catch (e) {}
    // 找不到那一行的第二种真因：会话从没跑过（blank）→ DSH 把它从侧栏隐藏 → 永远等不到。
    // 等 4 秒还没出现就发一条消息把它唤醒；它跑过一个 turn 后 blank 变 false，侧栏立刻有行。
    var woke = false
    navTimers.push(setTimeout(function () {
      if (settled || woke || epoch !== navEpoch) return
      woke = true
      // 同一个会话只唤醒一次：免得侧栏偶尔重渲染时把"唤醒文案"重复灌进对话
      if (wokeFor === String(id)) return
      wokeFor = String(id)
      call('POST', 'say', { text: wakeText() }).catch(function (e) {
        console.error('[dsh-chat-digest] 唤醒会话失败', e)
      })
    }, 4000))
    navTimers.push(setTimeout(function () {
      if (epoch !== navEpoch) return
      if (clickRow()) finish(true); else finish(false)
    }, 18000))
    return false
  }
  // 打开面板前记住"现在还开着哪个会话"，关面板时按标题点回去
  var prevSessionTitle = ''
  function cleanTitle(s) {
    return String(s || '')
      .replace(/\d+\s*(秒|分钟|小时|天|刚刚|个月|年).*$/, '')   // 去掉相对时间
      .replace(/\s*(标准模式|对话|轨迹|系统提示词|创造模式).*$/, '')  // 去掉中央列标题后面的栏目名
      .replace(/\s+/g, ' ').trim()
  }
  function rememberCurrentSession() {
    try {
      var rows = document.querySelectorAll('[class*="sessionRow"]')
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].getAttribute('aria-selected') === 'true') {
          var t1 = cleanTitle(rows[i].textContent)
          if (t1) { prevSessionTitle = t1; return }
        }
      }
    } catch (e) {}
    // 侧栏没有选中行（重渲染/折叠）时，用中央列的会话标题兜底
    try {
      var t2 = cleanTitle((document.querySelector('[class*="centerCol"]') || {}).innerText)
      if (t2) prevSessionTitle = t2
    } catch (e) {}
  }
  /* ---------------- 侧栏状态：进面板前保存，关面板时还原 ---------------- */
  // 用户的原话是"返回原会话之后侧栏都会消失"。侧栏 = 工作区树，最容易丢的是**展开态**：
  // 我们为了找到主 agent 会话会去点工作区行展开它，关面板时又乱点候选行，最后用户的树就变样了。
  var savedTree = null
  var savedSelectedTitle = ''
  var savedTreeScroll = 0
  var sidebarSnapEpoch = -1   // 这份快照属于哪个"面板周期"；同一周期只拍第一次
  function projectRows() {
    try { return document.querySelectorAll('[class*="projectRow"]') } catch (e) { return [] }
  }
  // 当前侧栏选中的会话标题（没有就返回 ''）
  function selectedSidebarTitle() {
    try {
      var rows = document.querySelectorAll('[class*="sessionRow"]')
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].getAttribute('aria-selected') === 'true') return cleanTitle(rows[i].textContent)
      }
    } catch (e) {}
    return ''
  }
  function rowKey(el) {
    try { return String(el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40) } catch (e) { return '' }
  }
  function rememberSidebar() {
    // 一个面板周期只拍一次：入口 pointerdown（用户意图的起点、还没被插件动过）那次最干净。
    // 否则 openPanel 会在"插件已经展开工作区/切了会话"之后再拍一份变形的快照，还原就还原错了。
    var epoch = navEpoch + 1
    if (sidebarSnapEpoch === epoch) return
    sidebarSnapEpoch = epoch
    var states = []
    try {
      var projs = projectRows()
      for (var i = 0; i < projs.length; i++) {
        states.push({ key: rowKey(projs[i]), expanded: projs[i].getAttribute('aria-expanded') === 'true' })
      }
      // 只在"当前选中的不是主 agent"时写快照 —— 否则会把"插件已切到主 agent"误当成用户的起点
      var cur = selectedSidebarTitle()
      if (cur && cur.indexOf('主 Agent') < 0) savedSelectedTitle = cur
      var sc = document.querySelector('[class*="treeBody"]') || document.querySelector('[class*="sidebarCol"] [class*="scroll"]')
      savedTreeScroll = sc ? (sc.scrollTop || 0) : 0
    } catch (e) {}
    savedTree = states
  }
  function restoreSidebar() {
    if (!savedTree) return
    var states = savedTree
    try {
      var projs = projectRows()
      for (var i = 0; i < projs.length; i++) {
        var k = rowKey(projs[i])
        for (var j = 0; j < states.length; j++) {
          if (states[j].key === k) {
            var now = projs[i].getAttribute('aria-expanded') === 'true'
            if (now !== states[j].expanded) realClick(projs[i])   // 该展开的展开、该收起的收起
            break
          }
        }
      }
      // DSH 是异步重渲染的：它可能在我们的点击之后又改一次树，所以延时再收口一遍。
      if (!restoreSidebar.pass2) {
        restoreSidebar.pass2 = true
        navTimers.push(setTimeout(function () {
          restoreSidebar.pass2 = false
          try {
            var ps = projectRows()
            for (var m = 0; m < ps.length; m++) {
              var kk = rowKey(ps[m])
              for (var n = 0; n < states.length; n++) {
                if (states[n].key === kk) {
                  var cur = ps[m].getAttribute('aria-expanded') === 'true'
                  if (cur !== states[n].expanded) realClick(ps[m])
                  break
                }
              }
            }
          } catch (e) {}
        }, 700))
      }
    } catch (e) {}
    // 选中的会话行也还回去。**要重试**：DSH 标选中态有延迟（实测 ~96ms），
    // 一次性的同步检查很容易"还没生效就放弃"（上一版就是这样，看起来像没还原）。
    try {
      if (savedSelectedTitle && savedSelectedTitle.indexOf('主 Agent') < 0) {
        var want = savedSelectedTitle
        var tries = 0
        var fix = function () {
          tries++
          var rows = document.querySelectorAll('[class*="sessionRow"]')
          var cur = selectedSidebarTitle()
          if (cur && cur.indexOf(want) >= 0) return          // 已经是它了
          for (var r2 = 0; r2 < rows.length; r2++) {
            if ((rows[r2].textContent || '').indexOf(want) >= 0) { realClick(rows[r2]); break }
          }
          if (tries < 10) navTimers.push(setTimeout(fix, 300))
        }
        fix()
      }
    } catch (e) {}
    try {
      var sc = document.querySelector('[class*="treeBody"]') || document.querySelector('[class*="sidebarCol"] [class*="scroll"]')
      if (sc && savedTreeScroll) sc.scrollTop = savedTreeScroll
    } catch (e) {}
  }

  function restorePrevSession() {
    // 进来之前就是主 agent 的话，无需还原
    if (!prevSessionTitle || prevSessionTitle.indexOf('主 Agent') >= 0) return
    var want = prevSessionTitle
    var tries = 0
    var expandedIdx = []
    var attempt = function () {
      tries++
      try {
        var rows = document.querySelectorAll('[class*="sessionRow"]')
        for (var i = 0; i < rows.length; i++) {
          if ((rows[i].textContent || '').indexOf(want) >= 0) {
            // 不再用 navGuardOn（全局时间窗会吞掉用户点击）；realClick 会给这一行打标记
            realClick(rows[i])
            return
          }
        }
        // ⚠ 这里原来会"挨个点工作区行"去找会话 —— 那是把用户侧栏点花的元凶之一：
        //   DSH 侧栏一次只展开一个工作区树，挨个点等于把侧栏里那些工作区全展开。
        //   现在改成：不点任何工作区行，交给 restoreSidebar() 把展开态**调回快照的样子**
        //   （快照是用户按下入口那一刻的真实状态），目标行自然会重新可见；
        //   然后由本函数的重试再去找那一行。
      } catch (e) {}
      if (tries < 6) navTimers.push(setTimeout(attempt, 400))
    }
    attempt()
  }

  /* ---- DSH 全屏视图（任务看板 / SSH）的接管与交还 ----
     打开我们的面板时，DSH 会把 html[data-dsh-taskboard-active] 摘掉（把视图让给我们），
     但它**不会**在我们关面板时加回来 —— 于是任务看板永远 display:none（用户："返回后右边的就没了"）。
     所以：开面板前记下它是谁，关面板时还回去。 */
  var savedDshViews = null
  function rememberDshViews() {
    try {
      savedDshViews = {
        taskboard: document.documentElement.hasAttribute('data-dsh-taskboard-active'),
        ssh: document.documentElement.hasAttribute('data-dsh-ssh-active'),
      }
    } catch (e) { savedDshViews = null }
  }
  function restoreDshViews() {
    if (!savedDshViews) return
    try {
      var root = document.documentElement
      var changed = false
      if (savedDshViews.taskboard && !root.hasAttribute('data-dsh-taskboard-active')) { root.setAttribute('data-dsh-taskboard-active', ''); changed = true }
      if (savedDshViews.ssh && !root.hasAttribute('data-dsh-ssh-active')) { root.setAttribute('data-dsh-ssh-active', ''); changed = true }
      // 让 DSH 重新量一次布局（它的视图切回来自带重排，这里补一次以防万一）
      if (changed) {
        try { window.dispatchEvent(new Event('resize')) } catch (e) {}
        setTimeout(function () { try { window.dispatchEvent(new Event('resize')) } catch (e) {} }, 120)
      }
    } catch (e) {}
  }

  function openPanel() {
    rememberDshViews()
    ensurePanel()
    rememberCurrentSession()   // 先记住原会话，返回时还原
    rememberSidebar()          // 再记住侧栏（工作区展开态/选中行/滚动），关面板时还原
    // 不重置 wsExpanded：DSH 一次只展开一个工作区树，插件重复去展开只会反复收起用户的树。
    document.documentElement.setAttribute(VIEW_ATTR, '')
    // 左半此时还是"上一个会话"（常常就是用户自己的对话）→ 先盖白，等目标会话就绪再揭。
    // 注意：这层 pointer-events:none，不参与任何点击判定；1.5 秒硬揭。
    showNavCover(store.sessionTitle || '聊天摘要 · 主 Agent', navEpoch + 1)
    setEntryActive(true)     // 面板打开时入口保持高亮（对齐任务看板的 active 效果）
    renderPanel()
    // A30（2026-09-27）：打开面板**必须取一次新数据**。
    //   以前这里只 renderPanel()（用的是内存里那份 store）—— 15 秒轮询一旦没跑起来
    //   （boot 中途抛异常，或本实例被 cleanup() 清成僵尸而后继实例又没顶上来），面板就**永久停在
    //   开机那一刻**，而界面上毫无提示。用户 09-26 报的"右边栏根本没更新"就是这么来的：
    //   服务端 28→30 条都写进去了，他那页一次请求都没发。
    //   打开面板＝用户的"我要看现在"，所以在这里补一次真取数。
    refresh()
    // 面板一变，输入框的位置/宽度就变了 → 让右栏重摆引用框（它自己另有 250ms 贴身跟随兜底）
    try { if (window.__cfwRight && window.__cfwRight.reposition) setTimeout(window.__cfwRight.reposition, 50) } catch (e) {}
    navEpoch += 1                 // 本次开面板的编号；关面板/再开一次都会 +1，让旧续作作废
    var epoch = navEpoch
    // 先切：手里有 id 就立刻切过去，不等 /ss 的体检（体检最坏 5-6 秒，就是"点了没反应"的真因）。
    // **冷启动第一点**时模块变量 sessionId 还是空的（它要等 /tell 或 /ss 回包，实测约 300ms），
    // 而 store.sessionId 在开机 refresh() 的 GET /state 里就拿到了（实测 15ms）→ 用它让第一次也立刻切。
    var beforeId = sessionId || store.sessionId || ''
    if (beforeId && !sessionId) sessionId = beforeId
    if (beforeId) openNativeSession(beforeId, epoch)
    // 体检放后台：Host 会自愈（被归档/被删/被移走 → 换新 id），id 变了再切一次
    ensureSession().then(function (id) {
      if (epoch !== navEpoch) return   // 面板已经关了（或又开了一次）→ 别再切会话、别再排定时器
      if (id && id !== beforeId) openNativeSession(id, epoch)
    })
  }
  // ---------------- 左半空白遮罩（极简版） ----------------
  function navCoverHost() {
    try { return document.querySelector('[data-pane="conversation"], [class*="centerCol"]') } catch (e) { return null }
  }
  function navCoverColor() {
    try {
      var host = navCoverHost()
      var c = host ? getComputedStyle(host).backgroundColor : ''
      if (!c || c === 'rgba(0, 0, 0, 0)' || c === 'transparent') c = getComputedStyle(document.body).backgroundColor
      if (!c || c === 'rgba(0, 0, 0, 0)' || c === 'transparent') c = '#fff'
      return c
    } catch (e) { return '#fff' }
  }
  function clearNavCover() {
    if (navCoverTimer !== null) { try { clearInterval(navCoverTimer) } catch (e) {} ; navCoverTimer = null }
    if (navCoverHardT !== null) { try { clearTimeout(navCoverHardT) } catch (e) {} ; navCoverHardT = null }
    var d = navCoverEl
    navCoverEl = null
    if (!d) return
    // 平滑揭开：先淡出（120ms）再摘。带兜底 —— 动画没跑也不会留下这一层。
    try {
      d.classList.add('cfw-navcover-off')
      setTimeout(function () { try { if (d.parentNode) d.parentNode.removeChild(d) } catch (e) {} }, 140)
    } catch (e) { try { if (d.parentNode) d.parentNode.removeChild(d) } catch (e2) {} }
  }
  function rowSelected(want) {
    if (!want) return false
    try {
      var rows = document.querySelectorAll('[class*="sessionRow"]')
      for (var i = 0; i < rows.length; i++) {
        if ((rows[i].textContent || '').indexOf(want) >= 0 && isRowActive(rows[i])) return true
      }
    } catch (e) {}
    return false
  }
  function colTitled(want) {
    if (!want) return false
    try {
      var t = cleanTitle((navCoverHost() || {}).innerText)
      return !!(t && t.indexOf(want) >= 0)
    } catch (e) { return false }
  }
  function showNavCover(want, epoch) {
    // 已经是目标会话就别铺（免得白闪一下）
    if (rowSelected(want) || colTitled(want)) { clearNavCover(); return }
    clearNavCover()
    var host = navCoverHost()
    if (!host) return
    var d = document.createElement('div')
    d.className = 'cfw-navcover'
    d.setAttribute('data-dsh-plugin', 'dsh-chat-digest')
    d.setAttribute('aria-hidden', 'true')
    try { d.style.background = navCoverColor() } catch (e) {}
    try { host.appendChild(d) } catch (e) { return }
    navCoverEl = d
    navCoverEpoch = epoch
    var done = function () { if (epoch !== navCoverEpoch) return; clearNavCover() }
    // 只读判断，100ms 一次；任何异常都当成"就绪"立刻揭开，绝不卡住
    navCoverTimer = setInterval(function () {
      if (epoch !== navCoverEpoch) return
      try {
        if (rowSelected(want) || colTitled(want)) done()
      } catch (e) { done() }
    }, 100)
    navCoverHardT = setTimeout(function () { navCoverHardT = null; done() }, 1500)
  }

  // opts.keepNav：用户自己点了侧栏别的会话/工作区/新会话 —— 面板收起来就行，
  // 不要再 restorePrevSession() 把他拽回原会话（那就是"点其他会话自动返回"的真因）。
  function closePanel(opts) {
    clearNavWatch()   // 面板一关，就不要再替它等侧栏/唤醒会话/切会话了
    navEpoch += 1     // 让这次开面板遗留的异步续作全部作废
    document.documentElement.removeAttribute(VIEW_ATTR)
    navCoverEpoch = -1
    clearNavCover()
    closeRotateConfirm()
    setEntryActive(false)
    // 面板关了 → 丢弃待发引用（否则它会一直挂在内存里，跟着输入框漂），并停掉跟随定时器
    try { if (window.__cfwRight && window.__cfwRight.clearQuote) window.__cfwRight.clearQuote() } catch (e) {}
    if (opts && opts.keepNav) prevSessionTitle = ''
    else restorePrevSession()   // 只有「返回」按钮才负责回到进来之前那个会话
    // 把 DSH 自己的全屏视图（任务看板 / SSH）还回去：不然它会一直 display:none。
    restoreDshViews()
    // 侧栏（工作区展开态 / 选中行 / 滚动位置）还原：用户报"返回原会话后原来的侧栏消失了"。
    // 放在 restorePrevSession 之后：那次点击可能又展开了别的项目，这里按保存值最终收口。
    restoreSidebar()
  }
  function syncEntryActive() {
    setEntryActive(document.documentElement.hasAttribute(VIEW_ATTR))
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag)
    if (cls) n.className = cls
    if (text !== undefined && text !== null) n.textContent = text
    return n
  }
  // ---------------- 左侧对话 ----------------

  // 右栏委托：真正实现见 lib/right.js（独立文件）
  function renderPanel() {
    try {
      if (window.__cfwRight && listEl !== null) {
        if (!renderPanel.mounted) {
          renderPanel.mounted = true
          window.__cfwRight.mount({
            el: el,
            api: function (method, endpoint, body) { return call(method, endpoint, body) },
            store: store,
            getListNode: function () { return listEl },
            getBarNode: function () { return barSlot },   // 不滚动横条里给 right.js 的槽（自动采集时间行）
            onError: function (msg) { store.err = String(msg); render() },
          })
        }
        window.__cfwRight.render(store)
        return
      }
    } catch (e) { console.error('[dsh-chat-digest] right.js 渲染失败', e) }
    // right.js 没挂上（或它自己抛错）→ 在右栏显示**可见**的错误，别再静默空白
    try {
      if (listEl !== null) {
        listEl.innerHTML = ''
        var eb = el('div', 'cfw-card')
        eb.append(el('div', 'cfw-gl', '右栏模块没加载'))
        eb.append(el('div', 'cfw-txt', 'lib/right.js 没挂上（刚热重载过？）——刷新一次即可；详情看 console。'))
        listEl.append(eb)
      }
    } catch (e) {}
  }

  // 「删除已勾选」按钮的状态：标签带条数，0 条时禁用并显示「无已勾选」
  // （用户 2026-09-13："不要删除以后就一直显示清理已完成，这样我怎么删除下一轮"）
  function countDone() {
    try { return (store.items || []).filter(function (i) { return i && i.done }).length } catch (e) { return 0 }
  }
  function syncBar() {
    if (!clrEl) return
    if (clrEl.__busy) return
    var n = countDone()
    clrEl.textContent = n ? ('删除已勾选 ' + n) : '无已勾选'
    clrEl.disabled = !n
    clrEl.className = 'cfw-mini' + (n ? '' : ' cfw-mini-off')
    if (!n) clrEl.title = '现在没有已勾选的条目（待办勾＝已完成 / 有用信息勾＝已知晓）'
    else clrEl.title = '把面板上已勾选的 ' + n + ' 条删掉。平时不用它 —— 每天那轮会先列清单问你要不要删，删的会留档。'
  }

  // refresh() 一直在调 render()，但它此前从未被定义 —— 每次刷新都抛 ReferenceError，
  // 界面永远不更新（表现为"点了没反应/框框点不动"）。这里补上。
  function render() {
    if (dragging) return   // 拖动中跳过重渲染，避免抢帧
    renderPanel()
    syncBar()              // 横条上「删除已勾选」的标签要跟着已勾选条数走
    ensureAcc()
    syncAccLook()
    syncAccTime()          // 「上次采集」那行：折叠状态下 renderAcc 不跑，这里单独刷新（见 syncAccTime 注释）
    syncEntryActive()
    if (isAccOpen()) renderAcc()
  }

  // 点击侧栏里的会话/新会话/工作区时，把中央列还给会话。
  // 已废弃：全局"插件点击时间窗"。它解决了"插件切会话被自己关掉"，但会把用户在同一时间窗里的
  // 点击也吞掉（面板关不掉、概率触发）。现在改用按元素打标记 realClick + CLICK_MARK。
  // 保留这两个符号只为兼容外部引用，onDocClick 已不再读它。
  var navByPluginUntil = 0
  function navGuardOn(ms) { navByPluginUntil = Date.now() + (ms || 2500) }
  var navClickDone = false
  var wsExpanded = false
  var wokeFor = ''   // 已经为哪个会话发过"唤醒"消息（同一个只发一次）
  // openNativeSession 为了"等侧栏出现那一行"排下的观察器与定时器。
  // 必须能被 closePanel 一起撤掉 —— 否则用户点了返回之后，4 秒时还会真往会话里发唤醒消息、
  // 18 秒时还会 realClick 切会话（实测复现过：关面板后 turn/start 仍 +1、会话里多出一条初始化文案）。
  var navTimers = []
  var navObs = null
  // 每次开/关面板都 +1。openPanel 里那些异步续作（尤其是 ensureSession().then 里的第二次切换）
  // 回来时必须核对编号：对不上说明面板早关了（或又开了一次）→ 一律不许再切会话、不许再排定时器。
  // 实测过：只用 clearNavWatch 不够，迟到的 .then 会重新武装"4 秒后往会话写唤醒消息"的定时器。
  var navEpoch = 0
  // 会话未就绪时的空白遮罩（用户 2026-09-15 要求：别露出他当前那个会话）
  // 上一版用 MutationObserver(document.body) 判就绪 —— 实测把点击/切换都拖死了（用户报"白屏炸了、
  // 不切会话"）。这一版三条铁律：① pointer-events:none，绝不拦点击；② 只用 100ms 定时器判就绪；
  // ③ 1.5 秒硬超时，无条件揭开。宁可偶尔早露一下，也绝不留在空白里。
  var navCoverEl = null
  var navCoverEpoch = -1
  var navCoverTimer = null
  var navCoverHardT = null
  function clearNavWatch() {
    navTimers.forEach(function (t) { try { clearTimeout(t) } catch (e) {} })
    navTimers = []
    try { if (navObs) navObs.disconnect() } catch (e) {}
    navObs = null
  }
  function onDocClick(event) {
    if (!isCurrent()) return                   // 僵尸实例（已被更新的实例替换）不许动手
    if (!document.documentElement.hasAttribute(VIEW_ATTR)) return
    var t = event.target
    if (t === null || typeof t.closest !== 'function') return
    if (t.closest('[' + ENT_ATTR + ']') !== null) return
    if (t.closest('[' + PANEL_ATTR + ']') !== null) return
    // 只忽略"插件自己刚点过的那一行"上的这一次点击（按元素打标记，见 realClick）。
    // 以前这里是 `Date.now() < navByPluginUntil` 的全局 2.5 秒窗口 —— 那会把用户在这段时间里
    // 点别的会话也一起吞掉，导致"面板关不掉、且概率触发"。不要改回时间窗。
    if (t.closest('[' + CLICK_MARK + ']') !== null) return
    if (t.closest('[class*="sessionRow"],[class*="projectRow"],[class*="newSession"],[class*="searchResult"]') !== null) closePanel({ keepNav: true })
  }

  // 入口行上"按下"的捕获阶段就拍侧栏快照：这是用户意图的起点，比 openPanel 里更早、更准。
  function wireEntrySnapshot() {
    if (!window.__cfwWired) window.__cfwWired = {}
    var W = window.__cfwWired
    if (W.entrySnap) return
    W.entrySnap = true
    document.addEventListener('pointerdown', function (ev) {
      try {
        var t = ev.target
        if (t && t.closest && t.closest('.cfw-entry')) { rememberCurrentSession(); rememberSidebar() }
      } catch (e) {}
    }, true)
  }
  function boot() {
    // A30（2026-09-27）：**轮询先注册**。
    //   它原来在 boot 末尾，而 boot 里 injectStyle/ensureEntry/ensurePanel/ensureSession
    //   任何一步抛异常，这一行就永远执行不到 —— 表现是"面板挂上了、条目也渲染了、但从此不再刷新"，
    //   而且**界面上没有任何错误**（2026-09-27 实测：属性设上、等 42 秒，零次 /state 请求，
    //   同一页把 ui.js 重挂一次后就恢复成每 15 秒一次）。
    //   副作用最重的注册提到最前，其余部分用 try/catch 兜住：出问题要**看得见**，不能静默死掉。
    intervalIds.push(setInterval(function () {
      if (!isCurrent()) return
      if (!document.documentElement.hasAttribute(VIEW_ATTR)) return   // 面板没开：不发请求、不渲染
      refresh()
    }, 15000))
    try {
      injectStyle()
      wireEntrySnapshot()
      ensureEntry()
      ensurePanel()
      refresh()
      onEvt(document, 'click', onDocClick, true)
      // 少了这一行"点外部关闭面板内 ⋯ 菜单"的监听就永远不会生效。
      // 提前把专属会话建好：侧栏那一行需要时间才出现，先建好，用户点入口时就能直接切
      ensureSession()
    } catch (e) {
      store.err = 'boot 失败：' + String((e && e.message) || e)
      try { render() } catch (e2) {}
      console.error('[dsh-chat-digest] boot', e)
    }
    // ⚡ 性能：原先 (a) 每 5s refresh、(b) 每 2s 轮询 ensureEntry/ensurePanel/renderAcc、
    //    (c) MutationObserver 盯 document.body 子树且每次变动都跑 —— 三者叠加会把页面主线程占满，
    //    表现为界面卡顿、浏览器调试工具（CDP 命令）全部超时无响应。改成低频 + 抖动合并。
    var obsPending = null
    // A31（2026-09-27）：**"还没建出来"时也要重试**。
    //   原来的重试条件只覆盖"建出来了、又被 DSH 冲掉"（`!== null && !isConnected`）。
    //   而 boot 那次 ensurePanel() 常常撞上"DSH 中心列还没渲染"→ 直接 return，panelEl 仍是 null
    //   ⇒ 之后永远不重试，**新载入的页面里右栏是空的，必须点一下入口才出来**。
    //   2026-09-27 实测：刚载入 `.cfw-right` 不存在、0 条；点一下入口 → 出现、30 条。
    //   中心列一渲染出来就是一次 body 子树变动，所以这个 Observer 会自然被唤醒；上限只是防
    //   "这个页面永远没有中心列"时白转。侧栏入口行（ensureEntry）有同样的静默失败，一并修。
    var buildTries = 0
    var o = new MutationObserver(function () {
      if (!isCurrent()) return
      if (obsPending !== null) return          // 抖动合并：一帧最多处理一次
      obsPending = setTimeout(function () {
        obsPending = null
        try {
          var needEntry = (entryRow === null) || !entryRow.isConnected
          if (needEntry) ensureEntry()
          var needPanel = (panelEl === null) || !panelEl.isConnected
          if (needPanel) ensurePanel()
          if ((!needEntry || (entryRow !== null && entryRow.isConnected)) &&
              (!needPanel || (panelEl !== null && panelEl.isConnected))) {
            buildTries = 0                       // 两样都在位：计数归零
          } else if (buildTries < 200) {
            buildTries += 1
            if (buildTries === 200) console.error('[dsh-chat-digest] 侧栏入口或右栏面板一直建不出来'
              + '（DSH 的 DOM 选择器可能变了）')
          }
        } catch (e) {}
      }, 400)
    })
    o.observe(document.body, { childList: true, subtree: true })
    observers.push(o)
    onEvt(document, 'DOMContentLoaded', function () { if (!isCurrent()) return; ensureEntry(); ensurePanel() })
    console.log('[dsh-chat-digest] ui 已挂载（sidebar entry + ⋯ 菜单 + panel）')
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot)
  else boot()
})()
