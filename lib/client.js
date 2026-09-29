// dsh-chat-digest · 浏览器半边（客户端插件，DSH >= 0.1.7-rc.2）
//
// 为什么要有这个文件（2026-09-29 用户报「dsh 更新了，UI 需要更新」）：
//   0.1.7-rc.2 起侧栏的「全局面板」是**槽位驱动**的 —— 壳自己
//     `ctx.slots.entriesOfSlot("sidebar.panellist")` 生成行（button 的样式、标题、
//     tooltip、选中态都归壳），点击走 `ctx.layout.selectPanel(id)`，而主区渲染
//     `renderSlot("main", {}, { entryKey: activePanelId ?? "conversation" })`。
//   旧做法（宿主改写 HTML 注入 ui.js，由脚本自己往侧栏插行、自己用
//   `[class*="centerCol"]` 抢主列）在新壳里插不进那批行，也不走壳的选中态。
//
// 形状照 `@deepseek-ai/dsh-agent-preset/skills/cordis-plugin-development/templates/decoration/`
// 与 `@linxin666/dsh-client-ui-task-board`（engines.dsh >= 0.1.7-rc.2）：
//   · 本文件由壳按 package.json 的 `dsh.client` + `exports["./client"]` 加载；
//   · 文件必须调用 `window.__ModuleLoader__.load({ id, factory })`，工厂返回
//     `{ inject, apply }`；React 由 `require('react')` 从浏览器模块表拿，不自带。
//
// 面板本体仍然是 `lib/ui.js`（1870 行纯 DOM 逻辑，不重写）：
//   · 这里注册侧栏行与 main 槽页；页只给一个容器；
//   · ui.js 以「被承载」模式挂进那个容器（`window.__cfwUi.mountInto`），
//     不再自己插行、不再设 `data-dsh-chat-digest-view` 抢主列。
window.__ModuleLoader__.load({
  id: 'dsh-chat-digest',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    //: 面板 id：同时是 sidebar.panellist 的 list id 与 main 的 keyed key（必须一致）。
    const PANEL_ID = 'chat-digest'
    //: 行在「全局面板」里的次序（升序）。任务看板用 20；这颗排在它前面。
    const PANEL_ORDER = 10
    const UI_SRC = '/chat-feed/ui.js'

    /** 侧栏行的图标：只画图形，按钮/标题/选中态都由壳渲染。 */
    function Glyph(props) {
      const size = (props && props.size) || 16
      return h('svg', {
        'data-dsh-panel-entry': PANEL_ID,
        viewBox: '0 0 16 16',
        width: size,
        height: size,
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.3,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        'aria-hidden': 'true',
      }, [
        h('path', { key: 'b', d: 'M2 3.1h12v8.1H8.4L5 14.2v-3H2z' }),
        h('path', { key: 'l', d: 'M5 6.1h6M5 8.5h3.8' }),
      ])
    }

    //: 把 ui.js 取进页面（宿主仍在 /chat-feed/ui.js 提供它，只是不再自动注入）。
    //: 关键：**载入前先置 `window.__cfwHosted`** —— ui.js 是"载入即 boot()"，boot 那一刻若还按
    //: 非承载模式走，就会插一条旧入口行（侧栏两个「聊天摘要」）并把面板挂到 `.centerCol`
    //: （那个位置没有我们容器的确定高度 → 主区看着是空的）。2026-09-29 实测踩到过。
    function loadUi() {
      window.__cfwHosted = true
      if (window.__cfwUi) return Promise.resolve(window.__cfwUi)
      if (!window.__cfwUiLoading) {
        window.__cfwUiLoading = new Promise((resolve, reject) => {
          const s = document.createElement('script')
          s.src = UI_SRC
          s.async = true
          s.onload = () => (window.__cfwUi ? resolve(window.__cfwUi) : reject(new Error('ui.js 载入后没挂 window.__cfwUi')))
          s.onerror = () => reject(new Error('ui.js 载入失败：' + UI_SRC))
          document.head.appendChild(s)
        })
      }
      return window.__cfwUiLoading
    }

    /** main 槽页：壳只在「聊天摘要」被选中时挂它，切回会话就卸载。 */
    function makePage(ctx) {
      return function Page() {
        const ref = React.useRef(null)
        React.useEffect(() => {
          let gone = false
          const el = ref.current
          const api = {
            //: 面板里的「返回」：交给壳切回会话界面（旧版是自己清 VIEW_ATTR）。
            selectPanel: (id) => { try { ctx.layout.selectPanel(id) } catch (e) {} },
          }
          loadUi().then((ui) => {
            if (gone || !ui || typeof ui.mountInto !== 'function') return
            ui.mountInto(el, api)
          }).catch((e) => console.error('[dsh-chat-digest] 面板挂载失败：', e))
          return () => {
            gone = true
            try { if (window.__cfwUi && window.__cfwUi.unmount) window.__cfwUi.unmount() } catch (e) {}
          }
        }, [])
        return h('div', {
          'data-dsh-chat-digest-panel': '',
          ref,
          // 与兄弟插件同口径：撑满壳给的主区（skill-explorer 的页就是 height:100%;min-height:0;flex column）。
          style: {
            position: 'relative', height: '100%', width: '100%',
            minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden',
          },
        })
      }
    }

    return {
      inject: ['slots', 'layout'],
      apply(ctx) {
        const slots = ctx.slots
        //: 两个座位都由壳声明；用 inject 包住 ⇒ 壳没声明这个座位时本插件静默缺席，不让整页启动失败。
        ctx.effect(() => slots.inject('sidebar.panellist', () => slots.register({
          name: 'sidebar.panellist',
          id: PANEL_ID,
          order: PANEL_ORDER,
          label: () => '聊天摘要',
        }, Glyph)), 'chat-digest: sidebar row')
        ctx.effect(() => slots.inject('main', () => slots.register({
          name: 'main',
          key: PANEL_ID,
        }, makePage(ctx))), 'chat-digest: main panel')
      },
    }
  },
})
