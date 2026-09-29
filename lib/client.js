// dsh-chat-digest · 浏览器半边（客户端插件，DSH >= 0.1.7-rc.2）
//
// **只负责侧栏那一行。** 面板（左右分栏）仍旧走旧路径：宿主把 `lib/ui.js` 注入页面，
// ui.js 自己抢 `.centerCol`、自己管返回/刷新会话 —— 那条路 2026-09-29 用户确认「本来是能用的」。
// 为什么行要单独走这里：0.1.7-rc.2 的侧栏「全局面板」是**槽位驱动**的（壳按
// `ctx.slots.entriesOfSlot("sidebar.panellist")` 自己渲染每一行），脚本自己往侧栏塞
// `<button class="cfw-entry">` 塞不进那串行里 —— 塞进去也不是壳的行，样式对不上
// （用户原话：「没有融入啊，样式都不一样」）。
//
// 形状照官方模板 `dsh-agent-preset/skills/cordis-plugin-development/templates/decoration/`。
window.__ModuleLoader__.load({
  id: 'dsh-chat-digest',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    //: 面板 id：sidebar.panellist 的 list id 与 main 的 keyed key 必须是同一个。
    const PANEL_ID = 'chat-digest'
    //: 行在「全局面板」里的次序（升序）；任务看板用 20，这颗排在它前面。
    const PANEL_ORDER = 10

    /** 打开旧面板（ui.js 的那条路）；ui.js 还没到就现取一次。 */
    function openLegacyPanel() {
      const ui = window.__cfwUi
      if (ui && typeof ui.openPanel === 'function') { ui.openPanel(); return }
      try {
        const s = document.createElement('script')
        s.src = '/chat-feed/ui.js'
        s.async = true
        s.onload = function () { try { window.__cfwUi.openPanel() } catch (e) {} }
        document.head.appendChild(s)
      } catch (e) {}
    }

    /**
     * 侧栏行的图标。按钮、标题、悬停/选中态全部由壳渲染，这里只画图形。
     * 点击时**阻止冒泡**：不阻止的话壳会把这一次点击当成"选中该全局面板"（selectPanel），
     * 而我们的面板不由壳的主区渲染 —— 那正是上一版把左右栏搞坏的地方。
     */
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
        style: { pointerEvents: 'auto' },
        onClick: function (ev) {
          try { ev.preventDefault(); ev.stopPropagation() } catch (e) {}
          openLegacyPanel()
        },
      }, [
        h('path', { key: 'b', d: 'M2 3.1h12v8.1H8.4L5 14.2v-3H2z' }),
        h('path', { key: 'l', d: 'M5 6.1h6M5 8.5h3.8' }),
      ])
    }

    /**
     * 兜底页：只在"壳真的选中了这个面板"时才会挂 —— 鼠标点击已被 Glyph 拦掉，
     * 走得到的只有键盘 Enter/Space。它什么也不画，立刻把主区还给会话，再开旧面板，
     * 这样 `selectPanel` 不会因为缺 key 抛错，用户看到的面板仍旧是旧那套。
     */
    function makeBounce(ctx) {
      return function Bounce() {
        React.useEffect(function () {
          try { ctx.layout.selectPanel(null) } catch (e) {}
          openLegacyPanel()
        }, [])
        return null
      }
    }

    return {
      inject: ['slots', 'layout'],
      apply(ctx) {
        // ① 告诉 ui.js：侧栏行由壳渲染，你自己别再插一行（否则侧栏出现两个「聊天摘要」）。
        window.__cfwSidebarRow = true
        // ② 清掉可能已经被旧路径插进去的那一行 —— ui.js 是宿主注入的 defer 脚本，
        //    它可能先于本模块执行；只删我们自己的属性，绝不碰别的插件。
        try {
          const stale = document.querySelectorAll('[data-dsh-chatfeed-entry]')
          for (let i = 0; i < stale.length; i++) {
            const el = stale[i]
            if (el.parentNode) el.parentNode.removeChild(el)
          }
        } catch (e) {}

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
        }, makeBounce(ctx))), 'chat-digest: bounce page')
      },
    }
  },
})
