/* ============================================================================
 * dsh-chat-digest · 右栏（独立文件）
 * ---------------------------------------------------------------------------
 * 由 ui.js 加载并挂载：window.__cfwRight.mount(env)  →  window.__cfwRight.render(state)
 *
 * env（由 ui.js 注入，右栏不自己抓数据、不自己找容器）：
 *   el(node, cls, text)  建元素的小工具
 *   api(method, url, body)  Host 接口调用
 *   store                实时状态对象（含 items / err）
 *   getListNode()        取右栏列表容器
 *   getPanelNode()       取面板根节点
 *   onError(msg)         上报错误（ui.js 统一显示）
 *
 * 设计要点（2026-09-13 用户定案）：
 *   1. 每个条目有【显示编号】：待办 T1/T2…，信息 I1/I2…
 *      **注意（2026-09-19 更正）**：这个编号是**按渲染顺序派生的**（见本文件 render 里 `t += 1; x.__no = 'T' + t`），
 *      **不是稳定键** —— 条目一增删/重排，同一个 `#T1` 就可能指向另一条。
 *      **改条目一律按 `id`**（`items-patch` / `POST /item` 都按 id 定位）；编号只是给人看的。
 *      （原注释写"由条目 id 稳定派生、渲染多少次都不变"，与实现不符，已改正。
 *       注入给主 agent 的引用段现在**同时**带 `#T1` 与稳定 id。）
 *   2. 「引用它」→【独立于官方 UI 的灰色引用框】，画在官方输入框上方，正文形如
 *      「引用：#T1 报名截止：10/08…」+ 关闭按钮
 *   3. **引用不写进输入框**（2026-09-15 用户要求）：点「引用它」时 POST /api/quote 交给 Host，
 *      由 Host 在主 agent 组装提示词时作为**独立上下文**注入（见 host-v34 的 dsh-chat-digest:quote 段）。
 *      用户自己打的话保持干净；旧的 DOM 前缀注入（prefixOnce）已整段删除。
 * ==========================================================================*/

(function () {
  'use strict'

  var el = null          // 建元素工具
  var api = null         // Host 调用
  // 面板结构（数据驱动 + 热更新，2026-09-14）：来自 GET /chat-feed/api/panel ——
  //   主 agent 只改数据（panel.json / POST /api/panel），渲染由本模块负责；改数据即时生效，不用改 JS、不用刷页。
  var panelCfg = null         // { sections:[{id,title,kinds,order,count}], fallbackKind, ... }
  var panelTimer = null
  var barNode = null     // 不滚动横条里给本模块的槽（放"自动采集时间"行）
  var myBarRow = null    // 本模块在槽里那一行（重渲染时先删自己再插，避免重复）
  var store = null       // 状态
  var listNode = null    // 右栏列表容器
  var onError = null     // 错误上报

  var openMenuId = ''    // 当前展开的 ⋯ 菜单（条目 id）
  var quoteRef = null    // 当前引用 { no, text }
  var quoteSynced = false // 这份引用是否已经 POST 给 Host（只同步一次）
  var quotePoll = null   // 「服务端还有没有这条引用」的轮询句柄（只在有引用时跑）
  var styleInjected = false

  /* ---------------------------------------------------------------- 样式 */
  var CSS = [
    // 右栏的全部布局归这里独管（ui.js 里那些 .cfw-right 历史规则已删）：
    // 铺满面板、无边框无外边距（用户否掉过"卡片"），只留 8px 左内边距躲开拖拽分割线。
    '.cfw-right{flex:1 1 auto;width:100%;display:flex;flex-direction:column;min-width:0;pointer-events:auto;border:0;border-radius:0;margin:0;padding-left:8px;box-sizing:border-box;overflow:hidden;}',
    '.cfw-h{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 16px;border-bottom:1px solid var(--dsw-alias-separator-primary,var(--dsw-alias-border-l2,rgba(128,128,128,.25)));font-size:13px;font-weight:600;color:var(--dsw-alias-label-primary);border-radius:10px 10px 0 0;}',
    '.cfw-sec{font-size:15px;font-weight:600;letter-spacing:.3px;color:var(--dsw-alias-label-primary);padding:16px 14px 6px;}',
    '.cfw-gl{font-size:12px;color:var(--dsw-alias-label-tertiary);padding:10px 16px 4px;}',
    '.cfw-item{display:flex;align-items:flex-start;gap:8px;padding:8px 14px;font-size:13px;line-height:1.6;position:relative;border-radius:6px;color:var(--dsw-alias-label-primary);}',
    '.cfw-item:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.14));}',
    '.cfw-item.cfw-clickable{cursor:pointer;}',
    '.cfw-no{flex:none;font-size:11px;font-variant-numeric:tabular-nums;color:var(--dsw-alias-label-tertiary);min-width:26px;}',
    '.cfw-chk{flex:none;width:16px;height:16px;border-radius:4px;border:1.5px solid var(--dsw-alias-border-l3,rgba(128,128,128,.6));display:inline-flex;align-items:center;justify-content:center;font-size:11px;line-height:1;cursor:pointer;}',
    '.cfw-item.cfw-done .cfw-chk{background:var(--dsw-alias-state-success-primary,#4caf50);border-color:var(--dsw-alias-state-success-primary,#4caf50);color:#fff;}',
    '.cfw-txt{flex:1 1 auto;min-width:0;word-break:break-word;}',
    // 勾选后的样式＝**原来那一套**（2026-09-13 用户："我只让你改对齐，没让你改其他的，其他的统一为原来的"）：
    // 灰字 + 删除线；两类条目共用同一条规则（原来就只这一条）。
    '.cfw-item.cfw-done .cfw-txt{color:var(--dsw-alias-label-tertiary);text-decoration:line-through;}',
    // 本次**只改对齐**：勾选框/编号/⋯ 顶端对齐（否则 16px 的框会飘在整段中间，长卡片尤其明显）。
    '.cfw-no,.cfw-chk,.cfw-more{margin-top:3px;}',
    '.cfw-txt{white-space:pre-wrap;}',
    '.cfw-txt strong{font-weight:600;}',
    // 链接色：DSH 主题里**没有蓝色令牌**（`--dsw-alias-brand-primary` 实测是近黑 `#0f1115`），
    // 所以按用户 2026-09-13 的要求（"链接最好改成蓝色吧"）写死一档标准蓝。
    '.cfw-txt a{color:#1677ff;text-decoration:underline;text-underline-offset:2px;}',
    // 新条目标识（主 agent 追加新信息时打上；旧标识由它清掉）
    '.cfw-new{display:inline-block;font-size:10px;line-height:14px;padding:0 4px;border-radius:4px;font-weight:600;color:#fff;background:var(--dsw-alias-state-success-primary,#4caf50);margin-right:4px;vertical-align:1px;}',
    // 自动采集时间设置行（2026-09-13）：放在右栏**顶部**。
    // 侧栏那行放不下——实测 `.cfw-acc-body` 下半截与侧栏"工作区"区域头部的按钮同一块地方，
    // 任何交互控件在那里 elementFromPoint 命中的都是那些按钮（真实鼠标点不到）。
    // 时间行现在住在 ui.js 的横条 .cfw-rbar 里 → **自己不带边框/内边距**（否则会多出一条短分割线，
    // 用户截图指过："下面的短分割线干什么"）。横条自己那条通栏线才是唯一的分隔。
    '.cfw-auto{display:flex;align-items:center;gap:8px;padding:0;font-size:12px;color:inherit;}',
    '.cfw-auto-time{box-sizing:border-box;width:82px;height:24px;font-size:12px;line-height:22px;padding:0 4px;border-radius:6px;border:1px solid var(--dsw-alias-border-l2);background:transparent;color:inherit;font-family:ui-monospace,Consolas,monospace;}',
    '.cfw-auto-hint{opacity:.75;}',
    // 网关状态条（2026-09-17 加、**当天用户要求删掉**）：它替用户决定"要不要花钱"，而用户要的是
    //   「我自己点哪条线路就试哪条」⇒ 决定权搬进侧栏「获取」按钮的下拉菜单（见 lib\ui.js 的 cfw-tk-menu），
    //   现场探测 + 探不通就红一下「获取失败」。策略字段 `gwPolicy` 仍留在宿主侧（只影响**自动**触发那一轮）。
    // 2026-09-14：`.cfw-src` 从"右侧固定列"改成"**正文末尾的浮动小字**"。
    //   float:right 会贴它所在那一行的右侧；那一行放不下就自动落到下一行 —— 正是用户要的"末行居右，放不下换行"。
    //   关键收益：它不再按条目全高预留宽度（原来 flex:none 会把正文每行都挤窄约 1/3）。
    //   text-decoration:none：避免"已勾选条目"的删除线把来源一起划掉。
    '.cfw-src{float:right;margin-left:8px;font-size:11px;line-height:1.5;color:var(--dsw-alias-label-tertiary);opacity:.85;text-decoration:none;}',
    // 2026-09-14：菜单挂在 ⋯ **按钮内部**（见 itemRow 的注释），所以按钮必须是定位祖先。
    '.cfw-more{flex:0 0 auto;width:24px;height:24px;padding:0;display:inline-flex;align-items:center;justify-content:center;font-size:15px;line-height:1;border-radius:6px;cursor:pointer;opacity:.6;color:var(--dsw-alias-label-tertiary);position:relative;}',
    '.cfw-more:hover{opacity:1;background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.16));}',
    // 2026-09-14：菜单以 ⋯ 按钮为基准（`top:100%` = 紧贴按钮下沿；`right:0` = 右缘对齐按钮右缘）。
    // 不再写死 `top:26px`（那假设了包含块是条目行，实测不成立 → 菜单会飘到别处）。
    '.cfw-menu{position:absolute;right:0;top:100%;margin-top:6px;z-index:30;width:196px;padding:4px;background:var(--dsw-alias-bg-layer-2,var(--cfw-panelBg,#fff));border:1px solid var(--dsw-alias-border-l2,rgba(128,128,128,.28));border-radius:10px;box-shadow:var(--dsw-shadow-lv3,0 8px 28px rgba(16,24,40,.3));}',
    '.cfw-mi{display:flex;align-items:center;gap:8px;width:100%;padding:7px 10px;border:0;background:transparent;color:var(--dsw-alias-label-primary);font-family:inherit;font-size:13px;line-height:1.4;text-align:left;border-radius:6px;cursor:pointer;}',
    '.cfw-mi:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.14));}',
    '.cfw-mi svg{flex:0 0 auto;opacity:.75;}',
    '.cfw-mi-danger:hover{background:var(--dsw-alias-state-error-primary,#d33);color:#fff;}',
    '.cfw-mi-danger:hover svg{opacity:1;}',
    '.cfw-mini{border:1px solid var(--dsw-alias-border-l2,rgba(128,128,128,.28));background:transparent;color:var(--dsw-alias-label-secondary);border-radius:8px;padding:3px 9px;font-family:inherit;font-size:12px;cursor:pointer;}',
    '.cfw-mini:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(128,128,128,.14));color:var(--dsw-alias-label-primary);}',
    /* 灰色引用框：**绝对定位、被输入框遮罩的灰条** */
    // 历史上它是绝对定位浮层，踩过两次坑：写 bottom:96px 时正好落进输入区被盖住（"引用框根本看不到"）；
    // 后来改成按实测矩形摆，又出现"比输入框宽""拖动分割线后不跟随"。
    // 2026-09-14 用户定案（逐步四句）："从输入框 UI 上方延展出来，圆角、灰色"、
    // "下面与输入框连接，上面与输入框一样的圆角与尺寸"、"把**上面**的 UI 往上挤，不要把**输入框**往下挤"，
    // 以及最后纠错："你把输入框本来的UI动了（高度变高了，圆角没了），你不要动原来的UI，保持输入框上方的圆角，
    //   然后你向上'延展'出来，相当于输入框遮罩一下你的引用框。"
    // 「占位块 + 负 margin」那一版错在哪（实测）：负 margin 会连卡片的 padding-top(8px) 一起算进高度，
    //   卡片 138→150、整体上移 12px，而 syncQuoteRadius 又去改卡片自己的圆角 —— 两件都在动**输入框本体**。
    // 现在：引用框 absolute + bottom:100%，压在卡片上沿**之上**，靠卡片自己的白色背景遮住它的下半截，
    //   读起来就是"从输入框后面长出来、被输入框遮了一下"；卡片几何与没有引用框时**逐项一致**
    //   （基线 y=624 h=138 padTop=8 radius=22px，输入框 y=632，seat h=168）。
    // 灰底写死中性灰：主题令牌 `--dsw-alias-bg-layer-2` 在这个主题里是**白色**，用它反而不灰。
    '/* 卡片必须自成层叠上下文，否则 z-index:-1 的引用框会掉到 .composerSeat(z-index:7) 后面看不见。\n       position:relative 卡片本来就是，z-index:0 与 auto 同层，不改变卡片自身观感。 */',
    '.cfw-quotebar-host{position:relative;z-index:0;}',
    // 占位块：卡片**前面**的流内元素，高度 = 引用框露在卡片上方的那一截（实测 27px）。
    // 它长出来时把输入框**上方**的 UI 顶上去（实测 seat y 624→597、h 168→195，而卡片与输入框都不动）。
    // 高度由 JS 按实测写成内联像素；这里只负责过渡，本身不可见。
    '.cfw-quotespacer{flex:0 0 auto;width:100%;height:0;background:transparent;pointer-events:none;transition:height .2s cubic-bezier(.22,1,.36,1);}',
    // 上圆角与输入框同款（实测卡片 22px）：写死，别去读卡片实测值（那种隐式联动历史上改坏过输入框本体）。
    // **光有 border-radius 不够**：引用框是实心的，会把它覆盖区域里卡片自己的上圆角"填平"，
    // 于是看起来不是与输入框融为一体（用户报"你得和输入框上方融为一体"）。必须用 clip-path 真把角外裁掉，
    // 上两角才会与输入框同心；下两角本来是 0，裁切不影响。
    // bottom 由 JS 按实测写成像素（= 卡片高 −(输入框顶−卡片顶)，实测 130px）：
    //   底边正好落在**输入框顶边**，于是下沿被输入框遮罩，只有露在卡片上方的那一截被看见。
    // 内边距对齐**输入框自身**的排版基准（实测输入框 padding 为 4px 14px）：
    //   padding-left 14px → 引用文字与输入框内的文字左对齐（用户要求"引用的字也最好对齐下面输入框"），实测误差 0。
    //   padding-top 10px  → 文字距条顶固定 10px；**不要用 align-items:center**：居中会把文字在条里上下均分，
    //                       一旦高度略大就会出现"上面空一大截、下面不留距离"（用户报的现象）。
    //                       改成 align-items:flex-start，上下留白完全由 padding 决定。
    //   padding 4px 上下 → 文字在**可见区**内上下居中。
    //     关键认识：条的下半截（R=22px 那段）是藏在卡片后面的，**可见区高度 = 条高 − R**。
    //     所以高度必须写成"内容(含padding) + R"（公式②），让可见区正好等于内容高度，文字才不会偏上。
    //     上一版 padding-top:9/bottom:0 时，可见区 28px、文字 18px，文字被顶到上面 → 上 9 / 下 1（用户报"上比下宽"）。
    //   padding 8px / 7px → 可见区内上下间隔**相等且不过小**。
    //     模型（实测校验过）：可见区上间隔 = padding-top；下间隔 = padding-bottom + 1（那 1px 是下边框）。
    //     故取 top 8 / bottom 7 ⇒ 两边都是 8。
    //     上一版 4px/4px ⇒ 上 4、下 5（用户报"下比上宽"且"太小了"）。
    //     再上一版 top12/bottom4 ⇒ 上 12、下 5（用户报"上面空一大截"）。
    //     要调大小只动这两个数，并把 bottom 取成 top − 1。
    '.cfw-quotebar{display:none;box-sizing:border-box;position:absolute;left:0;right:0;bottom:0;z-index:-1;border-radius:22px 22px 0 0;clip-path:inset(0 round 22px 22px 0 0);align-items:flex-start;gap:8px;padding:8px 14px 7px;background:var(--cfw-quotebg,#f2f3f5);border-bottom:1px solid var(--dsw-alias-border-l2,rgba(0,0,0,.10));color:var(--dsw-alias-label-secondary,rgb(97,102,107));font-size:12px;line-height:1.5;}',
    'html[data-dsh-chat-digest-view] .cfw-quotebar.cfw-quotebar-on{display:flex;opacity:1;transform:scaleY(1);}',
    // 平滑出现/消失：只动 opacity 与 scaleY，**绝不碰 height/margin** ——
    // 所以动画期间卡片高度不变、输入框一动不动（这是这个控件的硬要求）。
    // transform-origin 贴底：底边固定钉在输入框顶边，只有高度在长/缩 —— 即"长出来 / 沉回去"。
    // 不能用 translateY：整体上移会让底边从输入框顶边露出来（实测底边 626 vs 输入框顶 632），与"被遮罩"矛盾。
    '.cfw-quotebar{opacity:0;transform:scaleY(.4);transform-origin:bottom center;transition:opacity .2s ease-out,transform .2s cubic-bezier(.22,1,.36,1);}',
    // 「消失」分两步（见 patch_quotebar_hide_anim.py）：先过渡到 opacity:0，等 .2s 后再彻底隐藏。
    // 隐藏态用 display:none 时元素会离开 render tree，再次显示会被当作"初始渲染"而不生成过渡；
    // 所以显示方向靠 JS 的"先挂类 + 强制 reflow + 下一轮再加 -on"（见 renderQuoteBar）保证起止值。
    'html[data-dsh-chat-digest-view] .cfw-quotebar:not(.cfw-quotebar-on):not(.cfw-quotebar-hide){display:flex;opacity:0;transform:scaleY(.4);}',
    '.cfw-quotebar.cfw-quotebar-hide{display:none;}',
    '@media (prefers-reduced-motion: reduce){.cfw-quotebar{transition:none;transform:none;}}',
    // 文案默认**一行**、超出用省略号，且**绝不越过 ×**（用户要求"引用内容默认显示一行，超出部分用...代替，不要越过叉叉"）。
    // flex:1 1 0 + min-width:0 是关键：flex 子项默认 min-width:auto 会拒绝收缩到内容以下，
    // 那样长文案会把 × 顶出去/自己溢出；置 0 后才会在剩余宽度处截断并出省略号。
    '.cfw-quotebar-txt{flex:1 1 0;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;}',
    // margin-left:auto 把 × 顶到条的最右边（用户要求"叉叉改到最右边"）。
    // 条是 flex-start 对齐、文字后跟 ×，不加这条就会紧贴文字末尾。
    // × 与文字**同高**（用户报"叉叉掉下面去了"）。
    // 不能用 align-self:center —— 在"文字靠上(flex-start)"的条里居中会把它压到文字下方；
    // 也不能用 baseline —— 文字是 overflow:hidden 的块级盒，baseline 会退化成"按块底边对齐"，反而更靠下。
    // 用 flex-start + 2px 微调：文字行 18px、×14px，补 2px 即视觉居中。
    '.cfw-quotebar-x{flex:none;margin-left:auto;align-self:flex-start;margin-top:2px;cursor:pointer;opacity:.6;font-size:14px;line-height:1;}',
    '.cfw-quotebar-x:hover{opacity:1;}',
    // 本机文件 / 图片（2026-09-20 审计 A01③）：`[名字](file:…)` 的可点链接与 `![说明](img:…)` 的内嵌图。
    // 图限宽并保持比例（面板窄，原图会撑破），失败时 alt 文字要看得见。
    '.cfw-img{display:block;max-width:100%;height:auto;margin:6px 0;border-radius:6px;background:rgba(127,127,127,.12);}',
    '.cfw-file{word-break:break-all;}',
    // A20：点击后用系统默认应用打开，旁边给一行小字状态（打开中 / 已打开 / 失败原因）
    '.cfw-open-note{margin-left:6px;font-size:12px;opacity:.6;}',
    // A22：主 agent 在等你回答 —— 面板顶部的一张显眼卡片（自动轮不弹前台，只能靠它提示）
    '.cfw-ask{border-left:3px solid #e0a030;background:rgba(224,160,48,.10);}',
    '.cfw-ask-h{margin:6px 0 2px;font-weight:600;font-size:13px;}',
    '.cfw-ask-o{margin:4px 0;font-size:12px;opacity:.75;}',
    '.cfw-ask-btn{margin-top:8px;padding:5px 10px;font-size:13px;cursor:pointer;border-radius:6px;'
      + 'border:1px solid rgba(127,127,127,.45);background:transparent;color:inherit;}',
    '.cfw-ask-btn:hover{background:rgba(127,127,127,.16);}',
    // A23：多余的同标题主 agent 卡片
    '.cfw-extra{border-left:3px solid #a060a0;background:rgba(160,96,160,.10);}',
    '.cfw-extra-hint{margin:4px 0 6px;font-size:12px;opacity:.7;}',
    '.cfw-extra-row{display:flex;align-items:center;gap:8px;margin:4px 0;}',
    '.cfw-extra-id{font-size:12px;opacity:.85;word-break:break-all;}',
  ].join('\n')

  function injectStyle() {
    // 热重载友好：已存在就把内容重写成当前 CSS（否则改了样式必须 F5 才生效）
    var old = document.getElementById('cfw-right-style')
    if (old !== null) { old.textContent = CSS; styleInjected = true; return }
    if (styleInjected) return
    var s = document.createElement('style')
    s.id = 'cfw-right-style'
    s.textContent = CSS
    document.head.appendChild(s)
    styleInjected = true
  }

  /* ------------------------------------------------------- 唯一编号 */
  // 待办 T1/T2…，信息 I1/I2…，按**当前显示顺序**每次重排。
  // 为什么不缓存：编号的用途是"用户看一眼就能指着说第几条"，所以它必须和面板里
  // 从上往下的顺序一致。缓存下来会出现 I4 排在 I3 上面这种指错行的情况。
  // 引用消息里同时带原文，所以即使后来重排也不会误伤。
  function numberInOrder(list) {
    var t = 0, i = 0
    ;(list || []).forEach(function (x) {
      if (x.kind === 'todo') { t += 1; x.__no = 'T' + t }
      else { i += 1; x.__no = 'I' + i }
    })
  }

  /* ------------------------------------------------------- 渲染 */
  var TODO_GROUPS = [
    ['today', '🔴 今天 / 24 小时内'],
    ['week', '🟡 本周'],
    ['later', '⚪ 更远'],
  ]
  var INFO_GROUPS = [
    ['official', '3.1 官方信息'],
    ['peer', '3.2 同学与群里的经验（听说 / 个例）'],
    ['resource', '3.3 资源与工具'],
    ['life', '3.4 生活与办事'],
  ]
  /* 2026-09-13 用户要求：可报名 / 可申请的机会单独立一节（「二、机会与招募」），
     原来的「二、有用信息」顺延为「三」；分档按"距截止的时间"排，与待办同一套 urgency 取值。 */
  var CHANCE_GROUPS = [
    ['today', '2.1 ⏳ 24 小时内截止'],
    ['week', '2.2 🟡 本周内截止'],
    ['later', '2.3 ⚪ 更远的截止 / 长期开放'],
  ]
  // 注：**没有「待确认」这一类**（2026-09-13 用户纠正："待确认不是让主 agent 确认的意思吗"）——
  // 「待确认 / 待核对」是**主 agent 自己**要跟的清单，写进它的手册（它的工作手册里），不占用户的列表。

  function addGroup(title, list, withChk) {
    if (!list.length) return
    var wrap = el('div', 'cfw-grp')
    wrap.append(el('div', 'cfw-gl', title + '（' + list.length + '）'))
    list.forEach(function (it) { wrap.append(itemRow(it, withChk)) })
    listNode.append(wrap)
  }

  /* 本机文件 / 图片（2026-09-20 审计 A01③ ＋ 2026-09-21 A20）。用户原话：
     「像这种地方，不是应该给出本地文件的超链接，我点一下就可以打开吗」，
     随后纠正：「我点击后会在浏览器又下载一遍这个文件」「最好所有文件都用本机默认应用打开吧」。
     ⇒ 所以：`[名字](file:路径)` 渲染成链接，**点击时 POST `/api/open`，由宿主用系统默认应用打开**
     （docx→Word、pdf→PDF 阅读器…），不再让浏览器下载；`href` 仍指向字节路由作为兜底
     （ctrl/中键点击、或 POST 失败时回落到下载）。`![说明](img:路径)` 必须走 `/api/file`（要字节才能内嵌）。
     路径匹配**允许空格与一层括号**：实测文件名有 `Maas-vscode工具调用指南(cline、claude code、kilo code).pdf`
     这种，写成 `[^)]+` 会在第一个 `)` 处断掉。 */
  function fileHref(p) {
    var t = String(p || '').trim().replace(/&amp;/g, '&')     // 正文先过了一次 HTML 转义，这里还原
    return '/chat-feed/api/file?p=' + encodeURIComponent(t)
  }
  var LOCAL_RE = /(!?)\[([^\]\n]*)\]\(((?:[^()\n]|\([^()\n]*\))*)\)/g
  function localLinks(s) {
    return s.replace(LOCAL_RE, function (all, bang, label, target) {
      var t = String(target || '').trim()
      if (!/^(file|img):/i.test(t)) return all                // 只吃 file:/img: 两种 scheme
      var raw = t.replace(/^(file|img):/i, '')
      if (bang === '!' || /^img:/i.test(t)) {
        return '<img class="cfw-img" src="' + fileHref(raw) + '" alt="' + String(label || '') + '" loading="lazy">'
      }
      return '<a class="cfw-file" href="' + fileHref(raw) + '" data-cfw-open="' + encodeURIComponent(raw) + '"'
           + ' target="_blank" rel="noreferrer" title="点击用本机默认应用打开">'
           + String(label || raw) + '</a>'
    })
  }

  /* 条目正文的极小富文本：**加粗** → <strong>、http(s) 链接 → 可点 <a>、
     **本机文件/图片** → 可点链接 / 内嵌图。先转义再替换，别把正文当 HTML 执行。 */
  function richText(raw) {
    var s = String(raw === undefined || raw === null ? '' : raw)
    s = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    s = localLinks(s)                                   // 必须在 http 链接之前（`file:` 不是 http，但顺序更清楚）
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    // 链接只吃 **ASCII 可见字符**（`[!-~]`）——中文、全角括号、空格都会自然截断。
    // 踩过的坑（2026-09-13 用户报"链接识别不对，点都打不开了"）：原来只排除了 `）` 没排除 `（`，
    // 于是 `https://…/a564/（免登录可打开）` 把"（免登录可打开"也吞进了 href。
    s = s.replace(/(https?:\/\/[!-~]+)/g, function (u) {
      while (u.length > 8 && ".,)]}>'\"".indexOf(u.charAt(u.length - 1)) >= 0) u = u.slice(0, -1)   // 去掉句末的 ASCII 标点
      return '<a href="' + u + '" target="_blank" rel="noreferrer">' + u + '</a>'
    })
    return s
  }

  function autoRow() {
    // 每天自动采集时间（2026-09-13）：右栏顶部一行，改完立刻 POST set-auto{time}
    var s = store || {}
    var row = el('div', 'cfw-auto')
    row.append(el('span', '', '自动采集时间'))
    var t = document.createElement('select')
    t.className = 'cfw-auto-time'
    t.title = '每天到点自动跑一轮（需要 DSH 在这个时刻活着；过了时间才打开页面会补触发）'
    // 用 select 而不是 <input type="time">：实测那个框在面板里"能选中 hh/mm 但敲不进两个数字"
    // （键盘事件被应用层吃掉），select 靠鼠标点选，不依赖按键。
    ;(function () {
      var cur = s.autoTime || '23:00', opts = []
      for (var h = 0; h < 24; h++) for (var m = 0; m < 60; m += 30) opts.push((h < 10 ? '0' : '') + h + (m === 0 ? ':00' : ':30'))
      if (opts.indexOf(cur) < 0) opts.push(cur)
      opts.sort()
      opts.forEach(function (v) {
        var o = document.createElement('option')
        o.value = v; o.textContent = v
        t.append(o)
      })
      t.value = cur           // **建完选项后再设值**（只靠 option.selected 实测会显示成第一项 00:00）
    })()
    t.addEventListener('change', function () {
      var v = String(t.value || '')
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(v)) { if (onError) onError('时间要 HH:MM（例如 23:00）'); return }
      api('POST', 'set-auto', { time: v }).then(function () {
        store.autoTime = v
        api('GET', 'state').then(function (st) { if (st) { store.autoTime = st.autoTime || v; store.auto = !!st.auto } })
          .catch(function () {})
      }).catch(function (e) { if (onError) onError('改时间失败：' + String((e && e.message) || e)) })
    })
    row.append(t)
    row.append(el('span', 'cfw-auto-hint', s.auto ? '已开启（在侧栏「自动」处开关）' : '自动已关闭（在侧栏「自动」处开启）'))
    return row
  }

  function itemRow(it, withChk) {
    // 两类条目（待办 / 有用信息）**同一套样式与逻辑**：不按 kind 加类（2026-09-13 用户要求统一）
    var row = el('div', 'cfw-item' + (withChk ? ' cfw-clickable' : '') + (it.done ? ' cfw-done' : ''))
    // 唯一编号（放最左，主 agent 按它定位）
    row.append(el('span', 'cfw-no', it.__no || ''))
    if (withChk) {
      var chk = el('span', 'cfw-chk', it.done ? '✓' : '')
      row.append(chk)
    }
    // 「新」标识：主 agent 追加新信息时打上，下一轮由它清掉（见它的产出规范）。
    // 2026-09-13 用户要求：放在**勾选框后面、文字前方**、**行内**（只影响第一行，不把整段文字挤窄），且只一个「新」字。
    var txtNode = el('span', 'cfw-txt')
    txtNode.innerHTML = (it.isNew ? '<span class="cfw-new">新</span>' : '') + richText(it.text)
    row.append(txtNode)
    // 来源：放在**正文末尾**（CSS 用 float:right → 贴最后一行右侧；放不下自动落到下一行）。
    // 2026-09-14 用户要求：原来它是行内 flex 的固定列（flex:none），会**按条目全高预留宽度** → 正文每行都被挤窄约 1/3。
    if (it.src) txtNode.append(el('span', 'cfw-src', String(it.src)))
    var more = el('span', 'cfw-more', '⋯')
    more.title = '更多'
    more.addEventListener('click', function (ev) {
      if (ev) { ev.stopPropagation(); ev.preventDefault() }
      openMenuId = openMenuId === it.id ? '' : it.id
      render()
    })
    row.append(more)
    if (withChk) {
      row.addEventListener('click', function (ev) {
        if (ev && ev.target && ev.target.closest && ev.target.closest('.cfw-more')) return
        if (ev && ev.target && ev.target.closest && ev.target.closest('.cfw-txt a')) return   // 点正文里的链接不勾选
        // 长卡片上"拖着选字"松手也会触发 click → 会把条目误勾上；选区非空就不当点击
        try { if (window.getSelection && String(window.getSelection() || '').trim()) return } catch (e) {}
        api('POST', 'item', { action: 'toggle', id: it.id }).then(render).catch(function (e) { if (onError) onError('切换失败：' + String(e && e.message || e)) })
      })
    }
    // ⚠ 2026-09-14 两次踩坑后的定案：菜单必须挂在 **⋯ 按钮自己**里面，用"按钮为相对基准 + top:100%"定位。
    //   踩坑史：① 原来是 `position:absolute; top:26px` 挂在**条目行**上，但包含块不是这一行 → 浮到 ⋯ 上方很远处；
    //   ② 我改成 `position:fixed` + getBoundingClientRect → **更糟**：最近的 transform 祖先会当它的包含块
    //      （面板里有 transform 动画），于是菜单跑到**整个页面左上角**。
    //   ⇒ 唯一稳的做法：锚在按钮本体上，不做任何坐标计算。
    if (openMenuId === it.id) {
      var _mb = row.querySelector('.cfw-more')
      if (_mb) _mb.append(buildMenu(it))
    }
    return row
  }

  function buildMenu(it) {
    var menu = el('div', 'cfw-menu')
    menu.addEventListener('click', function (ev) { if (ev) ev.stopPropagation() })
    var ICON_QUOTE = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 4 3 7l3 3"/><path d="M3 7h6.2A3.8 3.8 0 0 1 13 10.8V12"/></svg>'
    var ICON_TRASH = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 4.6h10"/><path d="M6.5 4.6V3.2h3v1.4"/><path d="M4.6 4.6l.6 8.1h5.6l.6-8.1"/></svg>'

    var miQuote = el('button', 'cfw-mi')
    miQuote.type = 'button'
    miQuote.innerHTML = ICON_QUOTE
    miQuote.append(el('span', 'cfw-miLabel', '引用它'))
    miQuote.title = '引用这条：会作为独立上下文注入主 agent，不写进你的输入框'
    miQuote.addEventListener('click', function () {
      // 编号与正文都从**当下 DOM 里那一行**现读，别用闭包里那份 it（可能来自上一次 render，
      // 编号会被 numberInOrder 重排过 → 出现过"#I4 配 I3 的正文"这类错配）。
      var row = (miQuote.closest ? miQuote.closest('.cfw-item') : null)
      var noNow = it.__no || ''
      var textNow = String(it.text || '')
      try {
        if (row) {
          var sn = row.querySelector('.cfw-no')
          var st = row.querySelector('.cfw-txt')
          if (sn && String(sn.textContent || '').trim()) noNow = String(sn.textContent).trim()
          if (st && String(st.textContent || '').trim()) textNow = String(st.textContent)
        }
      } catch (e) {}
      setQuote({ id: String(it.id || ''), no: noNow, text: textNow })
      openMenuId = ''
      render()
    })

    var miDel = el('button', 'cfw-mi cfw-mi-danger')
    miDel.type = 'button'
    miDel.innerHTML = ICON_TRASH
    miDel.append(el('span', 'cfw-miLabel', '删除'))
    miDel.addEventListener('click', function () {
      api('POST', 'item', { action: 'delete', id: it.id })
        .then(function () { openMenuId = ''; render() })
        .catch(function (e) { if (onError) onError('删除失败：' + String(e && e.message || e)) })
    })

    menu.append(miQuote, miDel)
    return menu
  }

  function render() {
    if (!listNode) return
    injectStyle()
    // ★ 2026-09-14 修「点一下条目整个右栏就往上滚」：
    //   点勾选/点删除走的是 `api(...).then(render)`，而本函数开头 `listNode.innerHTML = ''` 会把
    //   滚动容器清空重建 → scrollTop 被重置为 0（用户看到的就是"整栏往上滚"）。
    //   这里渲染前记住位置、渲染后在**微任务**里复原（微任务早于绘制，所以不会闪一帧）。
    //   高度明显变矮（删条目/清理）时不复原，避免滚到空白处。
    var keepTop = listNode.scrollTop
    var keepH = listNode.scrollHeight
    try {
      Promise.resolve().then(function () {
        try {
          if (keepTop > 0 && Math.abs(listNode.scrollHeight - keepH) < 60) listNode.scrollTop = keepTop
        } catch (e) {}
      })
    } catch (e) {}
    var items = (store && store.items) || []
    listNode.innerHTML = ''
    // 自动时间行**不放列表里**（会跟着滚走）→ 塞进 ui.js 提供的不滚动横条槽。
    // 只增删自己那一个节点，不清空槽（槽里还有 ui.js 的「删除已勾选」按钮）。
    try {
      if (barNode) {
        if (myBarRow && myBarRow.parentNode) myBarRow.parentNode.removeChild(myBarRow)
        myBarRow = autoRow()
        barNode.append(myBarRow)
      }
    } catch (e) { if (onError) onError('自动时间行渲染失败：' + String((e && e.message) || e)) }
    if (store && store.err) {
      var ec = el('div', 'cfw-card')
      ec.append(el('div', 'cfw-gl', '出错了'))
      ec.append(el('div', 'cfw-txt', String(store.err)))
      listNode.append(ec)
    }
    // A22（2026-09-22 用户："你跑自动的时候都不弹到前台，我怎么知道他在问问题"）：
    //   主 agent 在自动轮里调 `ask_user_question` 之后会一直等，而自动轮**不弹前台** ⇒
    //   2026-09-21 那一轮就这样静默死掉（90 秒后 turn 被 interrupted，整晚白跑）。
    //   所以面板顶部必须**显式**给出：它在等什么 + 一键跳到那条会话去回答。
    try {
      var pa = store && store.pendingAsk
      if (pa && pa.questions && pa.questions.length) {
        var ac = el('div', 'cfw-card cfw-ask')
        ac.append(el('div', 'cfw-gl', (pa.stale ? '（上一轮）主 agent 问过一个问题，没人回答' : '主 agent 在等你回答')))
        pa.questions.forEach(function (q) {
          if (q.header) ac.append(el('div', 'cfw-ask-h', String(q.header)))
          if (q.question) ac.append(el('div', 'cfw-txt', String(q.question)))
          if (q.options && q.options.length) ac.append(el('div', 'cfw-ask-o', '选项：' + q.options.join(' / ')))
        })
        var btn = el('button', 'cfw-ask-btn', pa.stale ? '去会话看看' : '去回答（打开那条会话）')
        btn.addEventListener('click', function (ev) {
          if (ev) ev.preventDefault()
          var ok = false
          try { if (window.__cfwOpenSession) ok = window.__cfwOpenSession((store && store.sessionId) || '') } catch (e) {}
          if (!ok) btn.textContent = '请到侧栏打开「聊天摘要 · 主 Agent」那条会话回答'
        })
        ac.append(btn)
        listNode.append(ac)
      }
    } catch (e) { if (onError) onError('提问卡片渲染失败：' + String((e && e.message) || e)) }
    // A23（2026-09-25 用户问"为什么多了一堆主agent"）：把**多出来的同标题主 agent** 显示出来 + 一键归档。
    //   此前插件自己都不知道有这回事（只认 sessionId 那一条），用户只能靠侧栏肉眼发现。
    //   **门槛＝≥2 条**（用户 2026-09-25 定）：留 1 条当备份是正常选择，不该一直挂着一张卡。
    try {
      var em = store && store.extraMains
      if (em && em.length >= 2) {
        var xc = el('div', 'cfw-card cfw-extra')
        xc.append(el('div', 'cfw-gl', '工作区里有 ' + em.length + ' 条多余的同标题主 agent'))
        xc.append(el('div', 'cfw-extra-hint', '它们不在用（当前会话与两个槽都不指向它们）。归档＝移出侧栏，不删内容。'))
        em.forEach(function (x) {
          var row = el('div', 'cfw-extra-row')
          row.append(el('span', 'cfw-extra-id', String((x && x.id) || '').slice(0, 20)))
          var b = el('button', 'cfw-ask-btn', '归档')
          b.addEventListener('click', function (ev) {
            if (ev) ev.preventDefault()
            b.disabled = true
            b.textContent = '归档中…'
            fetch('/chat-feed/api/archive', {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ sessionId: (x && x.id) || '' }),
            }).then(function (r) {
              return r.json().catch(function () { return {} })
            }).then(function (j) {
              if (j && j.ok) { b.textContent = '已归档（约 10 秒后从列表消失）'; return }
              b.disabled = false
              b.textContent = '失败：' + String((j && j.error) || '未知')
            }).catch(function (e) {
              b.disabled = false
              b.textContent = '失败：' + String(e)
            })
          })
          row.append(b)
          xc.append(row)
        })
        listNode.append(xc)
      }
    } catch (e) { if (onError) onError('多余主 agent 卡片渲染失败：' + String((e && e.message) || e)) }
    var todos = items.filter(function (i) { return i.kind === 'todo' })
    // 2026-09-13 用户要求：kind === 'chance' ＝ 可报名 / 可申请的机会，单独成节
    var chances = items.filter(function (i) { return i.kind === 'chance' })
    var infos = items.filter(function (i) { return i.kind !== 'todo' && i.kind !== 'chance' })
    var knownU = TODO_GROUPS.map(function (g) { return g[0] })
    var knownK = INFO_GROUPS.map(function (g) { return g[0] })
    // 先把"显示顺序"算出来：分组顺序就是用户从上往下读的顺序
    var todoGroups = TODO_GROUPS.map(function (g) {
      return [g[1], todos.filter(function (i) { return i.urgency === g[0] })]
    })
    todoGroups.push(['其他待办', todos.filter(function (i) { return knownU.indexOf(i.urgency) < 0 })])
    var chanceGroups = CHANCE_GROUPS.map(function (g) {
      return [g[1], chances.filter(function (i) { return i.urgency === g[0] })]
    })
    chanceGroups.push(['其他机会', chances.filter(function (i) { return knownU.indexOf(i.urgency) < 0 })])
    var infoGroups = INFO_GROUPS.map(function (g) {
      return [g[1], infos.filter(function (i) { return i.kind === g[0] })]
    })
    infoGroups.push(['其他信息', infos.filter(function (i) { return knownK.indexOf(i.kind) < 0 })])
    // —— 分节表：**数据驱动**（2026-09-14）——来自 GET /api/panel；取不到就用内置默认（与改造前语义一致）
    var secs = (panelCfg && panelCfg.sections && panelCfg.sections.length)
      ? panelCfg.sections.slice().sort(function (a, b) { return (a.order || 0) - (b.order || 0) })
      : [{ id: 'todo', title: '一、待办', kinds: ['todo'], order: 1 },
         { id: 'chance', title: '二、机会与招募', kinds: ['chance'], order: 2 },
         { id: 'info', title: '三、有用信息', kinds: ['official', 'resource', 'peer', 'life'], order: 3 }]
    // 未知/新增节：它自己在 panel.json 里加的那种 —— 也参与统一编号，并走通用渲染（不用改本文件）
    var extraItems = []
    secs.forEach(function (s) {
      if (s.id === 'todo' || s.id === 'chance' || s.id === 'info') return
      s.__items = items.filter(function (i) { return (s.kinds || []).indexOf(i.kind) >= 0 })
      extraItems = extraItems.concat(s.__items)
    })
    numberInOrder(todoGroups.concat(chanceGroups).concat(infoGroups).reduce(function (acc, g) { return acc.concat(g[1]) }, []).concat(extraItems))
    secs.forEach(function (s) {
      var title = (s.title || s.id)
      if (s.id === 'todo') {
        if (todos.length) { listNode.append(el('div', 'cfw-sec', title)); todoGroups.forEach(function (g) { addGroup(g[0], g[1], true) }) }
        return
      }
      if (s.id === 'chance') {
        if (chances.length) { listNode.append(el('div', 'cfw-sec', title)); chanceGroups.forEach(function (g) { addGroup(g[0], g[1], true) }) }
        return
      }
      if (s.id === 'info') {
        if (infos.length) { listNode.append(el('div', 'cfw-sec', title)); infoGroups.forEach(function (g) { addGroup(g[0], g[1], true) }) }
        return
      }
      // 新增节（来自数据，不是代码）
      if (s.__items && s.__items.length) { listNode.append(el('div', 'cfw-sec', title)); addGroup(title, s.__items, true) }
    })
    if (!items.length) {
      var em = el('div', 'cfw-gl', '还没有条目 —— 点侧栏 ⋯ 里的「获取」开始采集。')
      listNode.append(em)
    }
  }

  /* ------------------------------------------------- 灰色引用框 + 发送注入 */
  function quoteBarNode() {
    var bar = document.getElementById('cfw-quotebar')
    if (bar) return bar
    bar = document.createElement('div')
    bar.id = 'cfw-quotebar'
    bar.className = 'cfw-quotebar'
    var col = document.querySelector('[class*="centerCol"]')
    ;(col || document.body).appendChild(bar)
    return bar
  }

  // 引用框放进输入框**卡片内部的最前面**（不是浮层）：
  //   卡片 `uV2eYG_card` 是 flex 列、圆角 22px、白底、padding:8px 0 0 ——
  //   把引用框插到它的第一个子节点，输入框自然被**挤下去**，不再有任何遮挡。
  // 拿不到卡片时退回"绝对定位浮层"（至少不消失）。
  function quoteCard() {
    try {
      var col = document.querySelector('[class*="centerCol"]')
      if (!col) return null
      return col.querySelector('[class*="uV2eYG_card"]') || col.querySelector('[class*="composerStack"] > *') || null
    } catch (e) { return null }
  }
  // 占位块要插在卡片**前面**（同一个父节点），才能参与布局把上方 UI 顶上去。
  function quoteHost() {
    var card = quoteCard()
    return card && card.parentNode ? card.parentNode : null
  }
  // 引用框露在卡片上方的那一截高度 = 本体实测高度（实测 35px）。
  // 由它驱动占位块高度 → 上方 UI 被顶开的距离，与视觉上多出来的高度一致。
  // 输入框顶相对卡片顶的偏移（＝卡片 padding-top，实测 8px）。
  // 它同时决定两件事：引用框底边该落在哪（被遮罩），以及露出来的那一截有多高。
  function quoteOffset() {
    try {
      var card = quoteCard()
      var ta = officialComposer()
      if (card && ta) {
        var d = Math.round(ta.getBoundingClientRect().top - card.getBoundingClientRect().top)
        if (d >= 0 && d < 40) return d
        return 8
      }
      return 8
    } catch (e) { return 8 }
  }
  // 当前占位块高度（= 上方 UI 被顶开的距离）。placeQuoteBar 里已按实测写好，
  // 这里只读不算，避免两处各算一套导致不一致。
  // 最近一次实测得到的"露出高度"（= 需要把上方 UI 顶开的距离）。
  // placeQuoteBar 测量时会先把占位块归零，所以那一刻不能再读占位块高度，必须记在这里。
  var lastReveal = 0
  function quoteReveal() {
    try { return lastReveal } catch (e) { return 0 }
  }
  // 占位块必须"先存在于 DOM、且高度为 0"，之后改高度才会生成过渡 ——
  // 现建现写高度会被浏览器当作初始渲染，直接跳到目标值（实测：createElement 后立刻写 27px，computed 就是 27px、无过渡）。
  function ensureQuoteSpacer() {
    try {
      var host = quoteHost()
      if (!host) return null
      if (!spacerEl || !spacerEl.isConnected || spacerEl.parentNode !== host) {
        if (spacerEl && spacerEl.parentNode) spacerEl.parentNode.removeChild(spacerEl)
        spacerEl = document.createElement('div')
        spacerEl.className = 'cfw-quotespacer'
        spacerEl.setAttribute('data-dsh-plugin', 'dsh-chat-digest')
        spacerEl.style.height = '0px'
        host.insertBefore(spacerEl, quoteCard())
      }
      return spacerEl
    } catch (e) { return null }
  }
  // 写占位块高度（= 向上挤开的高度）。
  // 首次出现时**不挂过渡**：本环境的合成器不推进 height 过渡，会把值永久钉在起始帧
  //   （实测 inline=35px 而 computed=0px、offsetHeight=0 —— 挤开量因此恒为 0）。
  //   首次直接落值，保证布局正确；过渡只用于之后的变化（拖分割线/窗口缩放等）。
  // 写完强制一次 reflow（读 offsetHeight）：把可能被延迟计算的值冲掉。
  function setReveal(h, animate) {
    try {
      var sp = ensureQuoteSpacer()
      if (!sp) return
      var v = Math.round(h) > 0 ? Math.round(h) : 0
      var next = v + 'px'
      if (sp.style.height === next) return
      if (!animate) {
        var prev = sp.style.transition
        sp.style.transition = 'none'
        sp.style.height = next
        void sp.offsetHeight
        sp.style.transition = prev
      } else {
        sp.style.height = next
        void sp.offsetHeight
      }
    } catch (e) {}
  }
  // 输入框圆角半径 R：引用框的上两角与它同心，且"被遮罩"的高度要正好等于它。
  // 写死 22px：实测卡片 border-radius = 22px；圆角没有主题令牌，读实测值反而引入隐式联动。
  var QUOTE_R = 22
  // 定死引用框几何，满足用户给的三条公式：
  //   ② 实际高度 H = 视觉高度 + 圆角宽度 R
  //   ③ 被遮罩高度 = 圆角半径 R
  //   ① 视觉高度 = 向上挤开的高度
  // 关系（H、R、offset 定义见下）：
  //   H = 内容自然高度（**不再加 R**：内容里已含上下 padding，再加一次会重复计）
  //   被遮罩 = R                ← 由 CSS `bottom: calc(100% - R)` 保证（底边落在卡片顶下方 R）
  //   视觉   = H − offset − R   ← 卡片上方露出的部分（实测 57−8−22 = 27）
  //   挤开   = 视觉             ← 公式①
  // 为什么用 `bottom: calc(100% - R)`：`bottom:100%` 的语义是"底边贴卡片顶"，减 R 即"底边在卡片顶下方 R"，
  //   表达式**与卡片高度无关** → 不会出现"卡片高随挤开量变化、bottom 跟着变"的循环。
  // 为什么高度要显式写：本环境渲染时间线冻结在 t=0，动画 transform 会把 getBoundingClientRect 缩小
  //   （实测把 57px 的框量成 15px），显式写 height 可让布局几何与动画状态解耦。
  function applyQuoteSize(bar) {
    try {
      var card = quoteCard()
      if (!card || !bar) return 0
      // 量内容自然高度：清内联高度，用布局量 offsetHeight（不受动画 transform 影响）
      var prevT = bar.style.transform
      bar.style.height = ''
      bar.style.transform = 'none'
      var content = Math.round(bar.offsetHeight)
      if (!(content > 0)) content = Math.round(bar.getBoundingClientRect().height)
      bar.style.transform = prevT
      // 公式②：实际高度 H = 内容高度 + 圆角半径 R
      var H = content + QUOTE_R
      bar.style.height = H + 'px'
      bar.style.top = 'auto'
      // 公式③：被遮罩高度 = R ⇒ 底边落在卡片顶下方 R ⇒ bottom = 100% − R
      // （100% 的语义是"底边贴卡片顶"，减去 R 即"底边在卡片顶下方 R"；该式与卡片高度无关，不会形成循环）
      bar.style.bottom = 'calc(100% - ' + QUOTE_R + 'px)'
      // 公式①：视觉高度 = 挤开高度 = H − R
      lastReveal = H - QUOTE_R
      if (!(lastReveal > 0)) lastReveal = 0
      return lastReveal
    } catch (e) { return 0 }
  }
  // 只做定位：把底边钉在输入框顶边（被遮罩）。不碰占位块高度。
  function syncQuoteGeometry(bar) {
    try {
      var card = quoteCard()
      if (!card || !bar) return
      bar.style.bottom = Math.round(card.getBoundingClientRect().height - quoteOffset()) + 'px'
    } catch (e) {}
  }
  // 上一次挂到的宿主卡片：官方重挂 composer（切换会话等）时要把引用框搬回新卡片；
  // 换宿主时顺手把旧宿主的 class 摘掉，不留脏属性。
  var quoteHostEl = null
  var spacerEl = null

  function attachQuoteBar(bar) {
    var host = quoteHost()
    if (!host) {
      // 拿不到卡片（官方 DOM 变了）→ 退回 centerCol 直接挂，至少别消失
      var col = document.querySelector('[class*="centerCol"]')
      if (col && bar.parentNode !== col) col.appendChild(bar)
      return null
    }
    // 层叠上下文由 CSS 的 .cfw-quotebar-host 静态提供（position:relative;z-index:0），
    // 这里只做一次兜底赋值，保证宿主真的是叠层根（不依赖 CSS 是否被主题/其它规则盖掉）。
    if (quoteHostEl !== host) {
      if (quoteHostEl) quoteHostEl.classList.remove('cfw-quotebar-host')
      quoteHostEl = host
      host.classList.add('cfw-quotebar-host')
      if (getComputedStyle(host).position === 'static') host.style.position = 'relative'
      host.style.zIndex = '0'
    }
    // 引用框本体挂在**卡片**里（绝对定位，不被裁切）；占位块挂在卡片**前面**参与布局。
    var card = quoteCard()
    var target = card || host
    if (bar.parentNode !== target) target.insertBefore(bar, target.firstChild)
    else if (target.firstChild !== bar) target.insertBefore(bar, target.firstChild)
    // 占位块在这一刻就建好（h=0 已在 DOM 里渲染过），之后"长"才有起点可插值
    ensureQuoteSpacer()
    return host
  }

  // 把引用框摆到"官方输入区正上方"：直接量它的矩形，别猜、也别用魔法数字。
  // 取"可视输入框"本体（实测 `uV2eYG_input`，499px），而不是最外层 `composerSeat`（535px）——
  // 后者比可视输入框宽 32–36px，按它摆会两边都探出一截（2026-09-14 用户实测指出）。
  // 门槛放宽到 80px：拖动分割线把面板拖宽时，输入框会被挤到 200 多 px，不能因为它窄就认不出。
  function composerBox() {
    try {
      var col = document.querySelector('[class*="centerCol"]')
      if (!col) return null
      var ta = officialComposer()
      var r2 = ta ? ta.getBoundingClientRect() : null
      if (r2 && r2.width > 80 && r2.height > 0) return ta
      var cand = col.querySelector('[class*="composer"]')
      var r1 = cand ? cand.getBoundingClientRect() : null
      if (r1 && r1.width > 80 && r1.height > 0) return cand
      var seat = document.querySelector('[class*="composerSeat"]')
      return seat || null
    } catch (e) { return null }
  }

  // 摆放只剩一件事：确保它挂在卡片里（定位、圆角、宽度全部交给 CSS）。
  // 不再写 height / marginTop / border-radius —— 那三样都会动到输入框本体，
  // 而"引用框绝不能影响卡片几何"正是这个控件的硬要求（基线实测见文件头补丁说明）。
  var barStyleDone = false
  // 打开时调用一次：先定位 → 再量露出高度 → 设占位块（这一步产生"长出来"的过渡）。
  // 顺序不能反：`bottom:0` 时引用框在卡片**下方**，此时量出来是负数（实测 −102）；
  // 必须先 syncQuoteGeometry 把它挪到接缝处，量到的才是真正的露出高度（实测 27）。
  function placeQuoteBar(bar) {
    try {
      attachQuoteBar(bar)
      if (!barStyleDone) {
        // 清掉上一版实现留在同一节点上的内联样式（热重载会复用节点），只清一次
        bar.style.marginTop = '0px'
        bar.style.height = ''
        bar.style.borderTopLeftRadius = ''
        bar.style.borderTopRightRadius = ''
        bar.style.borderBottomLeftRadius = ''
        bar.style.borderBottomRightRadius = ''
        barStyleDone = true
      }
      var over = applyQuoteSize(bar)
      // 挤开量 == 视觉高度（用户公式①），把上方 UI 顶开这么多。
      // 首次出现不加过渡：否则本环境会把值钉在起始帧、挤开量恒为 0（见 setReveal 注释）。
      setReveal(over, false)
    } catch (e) {}
  }

  // 引用框开着的时候，持续跟着输入框走。
  // 为什么需要：输入框的**宽高都会变**（拖动分割线 → 列宽变；输入文字 → Lexical 长高；
  // 侧栏开合 / 窗口缩放 → 整体位移）。只在 window.resize 里重算是不够的 ——
  // 2026-09-14 用户实测：拖完分割线，引用框就不贴输入框了。
  // 做法：250ms 量一次，几何真的变了才写样式（不空转、不抖动）；关掉引用框即停。
  var followTimer = null
  var lastGeom = ''
  function geomKey(bar, box) {
    try {
      var b = bar.getBoundingClientRect(), t = box ? box.getBoundingClientRect() : null
      return [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height),
        t ? Math.round(t.left) : -1, t ? Math.round(t.top) : -1, t ? Math.round(t.width) : -1, t ? Math.round(t.height) : -1].join(',')
    } catch (e) { return '' }
  }
  function followTick() {
    try {
      // 面板一关就停：待发引用这时已经没有意义（注入入口也都会拦），别让定时器空转、别留脏状态
      if (!quoteRef || !document.documentElement.hasAttribute('data-dsh-chat-digest-view')) {
        // 面板关掉时引用已由 clearQuote() 清（含服务端）；这里只负责收尾 UI，不再悄悄丢状态
        var b0 = document.getElementById('cfw-quotebar')
        if (b0) { b0.innerHTML = ''; hideQuoteBar(b0) }   // 也走"先淡出、再隐藏"的两步，别一帧消失
        stopFollow()
        return
      }
      var bar = document.getElementById('cfw-quotebar')
      if (!bar || String(bar.className).indexOf('cfw-quotebar-on') < 0) { stopFollow(); return }
      // **先量、后判、再写** —— 这是性能关键。
      // 旧版每 250ms 无条件跑 applyQuoteSize（它既写 height/bottom 又读 offsetHeight）＝
      // 每秒 4 次强制同步重排；切换会话时 DSH 正在大范围重渲染，两者叠加会让切换明显卡顿。
      // 现在几何没变就直接返回，一次写都不做（"读"不会造成重排，"写后再读"才会）。
      var key = geomKey(bar, composerBox())
      if (key === lastGeom) return
      // 宿主可能被官方重挂（切换会话/重渲染）→ 先搬回卡片，再按公式重算尺寸与挤开量
      attachQuoteBar(bar)
      setReveal(applyQuoteSize(bar), true)
      lastGeom = geomKey(bar, composerBox())
    } catch (e) { }
  }
  function stopFollow() {
    if (followTimer !== null) { try { clearInterval(followTimer) } catch (e) { } followTimer = null }
  }
  function startFollow() {
    stopFollow()
    lastGeom = ''
    try { followTimer = setInterval(followTick, 250) } catch (e) { followTimer = null }
  }

  // 「消失」的第二步：等过渡跑完再真正 display:none；「出现」也要分两帧（见下）。
  var barHideTimer = null
  var barShowTimer = null
  function hideQuoteBar(bar) {
    if (barHideTimer !== null) { try { clearTimeout(barHideTimer) } catch (e) {} ; barHideTimer = null }
    bar.className = 'cfw-quotebar'                 // 摘掉 -on：仍在渲染（display:flex）、opacity 过渡到 0
    // 占位块同步"沉回去"：高度归零 → 上方 UI 落回原位。
    // 同样不加过渡（理由见 setReveal）：否则收起时高度会钉在起始帧、UI 落不回去。
    setReveal(0, false)
    try {
      barHideTimer = setTimeout(function () {
        barHideTimer = null
        try { bar.className = 'cfw-quotebar cfw-quotebar-hide' } catch (e) {}
      }, 260)                                        // 略长于 .2s，保证下沉与淡出跑完
    } catch (e) { bar.className = 'cfw-quotebar' }
  }

  function renderQuoteBar() {
    var bar = quoteBarNode()
    if (!quoteRef) { stopFollow(); bar.innerHTML = ''; hideQuoteBar(bar); return }
    if (barHideTimer !== null) { try { clearTimeout(barHideTimer) } catch (e) {} ; barHideTimer = null }
    if (barShowTimer !== null) { try { clearTimeout(barShowTimer) } catch (e) {} ; barShowTimer = null }
    // ——「出现」的补间：必须分**两次样式重算** ——
    // 1) 先挂 .cfw-quotebar：display 从 none 变 flex、opacity 仍是 0（元素先"在位但透明"）；
    // 2) 强制 reflow 固定这个起始值；
    // 3) 用 setTimeout 在下一轮再挂 .cfw-quotebar-on → 浏览器从 opacity:0/T(-6px) 补间到 1/0。
    // 为什么不能用同帧两段式、也不能用 rAF（都实测过）见本文件 patch_quotebar_show_timer.py 的说明。
    bar.className = 'cfw-quotebar'
    void bar.offsetHeight
    // 把"露出来的高度"交给占位块 → 上方 UI 被顶开（这就是"长出来"）。
    // 占位块此时已在 DOM 且高度为 0（attachQuoteBar 里建的），所以这次写入会**走过渡**而不是跳变。
    // 注意要等一帧再写：同一帧内"建元素 + 写目标高度"会被当作初始渲染而跳过过渡。
    // 占位块高度由 placeQuoteBar（下方）统一负责，这里不再重复写：
    // 两处都写会出现"先写 0 再写目标值"的抖动，且本环境会把过渡钉在起始帧。
    // 引用框自身的淡入仍由下面的 barShowTimer 加 -on 触发。
    barShowTimer = setTimeout(function () {
      barShowTimer = null
      try { bar.className = 'cfw-quotebar cfw-quotebar-on' } catch (e) {}
    }, 30)
    bar.innerHTML = ''
    bar.append(el('span', 'cfw-quotebar-txt', '引用：#' + quoteRef.no + ' ' + String(quoteRef.text).slice(0, 90)))
    var x = el('span', 'cfw-quotebar-x', '×')
    x.title = '取消引用'
    x.addEventListener('click', function () { clearQuote() })
    bar.append(x)
    placeQuoteBar(bar)
    lastGeom = geomKey(bar, composerBox())
    startFollow()
  }

  // 把待发引用同步给 Host（Host 在组装主 agent 提示词时注入；只同步一次）
  function syncQuoteToServer() {
    if (!quoteRef || quoteSynced) return
    quoteSynced = true
    try {
      api('POST', 'quote', { id: quoteRef.id || '', no: quoteRef.no || '', text: String(quoteRef.text || '') })
        .then(function (r) {
          // 服务端明确告知"这条引用定位不到主 agent 会话"时，不要留一个永远发不出去的框
          if (r && r.quote && !r.quote.for) {
            quoteRef = null; quoteSynced = false; stopQuotePoll(); stopFollow(); renderQuoteBar()
            if (onError) onError('这条引用没能定位到主 agent 会话，已取消（不会串到别的会话）')
          }
        })
        .catch(function (e) { quoteSynced = false; if (onError) onError('引用同步失败：' + String((e && e.message) || e)) })
    } catch (e) { quoteSynced = false; if (onError) onError('引用同步失败：' + String((e && e.message) || e)) }
  }

  function stopQuotePoll() {
    if (quotePoll !== null) { try { clearInterval(quotePoll) } catch (e) {} ; quotePoll = null }
  }

  // 服务端把引用用掉（注入后即清）时，前端要自己退场 —— 否则引用框会一直挂着
  function watchQuoteOnServer() {
    if (quotePoll !== null) return
    try {
      quotePoll = setInterval(function () {
        if (!quoteRef) { stopQuotePoll(); return }
        api('GET', 'state').then(function (s) {
          if (!s) return
          if (s.quoteNo) return            // 还在
          quoteRef = null                  // 服务端已经消费掉了（或别处清了）→ 本地退场，别回 POST
          quoteSynced = false
          stopQuotePoll()
          stopFollow()
          renderQuoteBar()
        }).catch(function () {})
      }, 4000)
    } catch (e) { quotePoll = null }
  }

  // 只清本地（**不通知服务端**）：用户一按发送就收框，服务端那条引用留给主 agent 注入。
  // 为什么不能顺手发 {clear:true}：那会在注入发生之前把引用删掉——正是之前"没注入"的另一条路。
  function dropLocalQuote() {
    if (!quoteRef) return
    quoteRef = null
    quoteSynced = false
    stopQuotePoll()
    stopFollow()
    renderQuoteBar()
  }

  // "要发送了"的两个入口：Enter（无 Shift）与点发送按钮。
  // 判据沿用 2026-09-14 的教训：① 面板必须开着（官方输入框是所有会话共用的）；
  // ② 点击必须落在官方输入区内（侧栏会话行本身也是 button，曾经误判过）。
  function onSendKey(ev) {
    if (!quoteRef) return
    if (ev.key !== 'Enter' || ev.shiftKey) return
    if (!document.documentElement.hasAttribute('data-dsh-chat-digest-view')) return
    var n = officialComposer()
    if (n && ev.target === n) dropLocalQuote()
  }
  function onSendClick(ev) {
    if (!quoteRef) return
    if (!document.documentElement.hasAttribute('data-dsh-chat-digest-view')) return
    var t = ev.target
    if (!t || !t.closest) return
    // 我自己的 UI 一律排除
    if (t.closest('.cfw-right, .cfw-quotebar, .cfw-menu, .cfw-leftback')) return
    // ① 必须在输入区里
    if (!t.closest('[class*="composer"]')) return
    // ② 必须是"发送控件"：从 target 起沿祖先找（点图标子元素也能命中）
    //    —— 不做任何"猜按钮"的兜底！点输入框时 target 是 div.uV2eYG_input，
    //    若在这一步去 querySelector 捞"composer 里的第一个 button"，捞到的正是发送按钮，
    //    于是"点一下输入框引用就没了"（2026-09-15 用户报，已用 trace 复现）。
    var node = t, hit = null
    for (var i = 0; node && i < 6; i++) {
      var cls = String(node.className || '')
      var label = String(node.getAttribute ? (node.getAttribute('aria-label') || node.title || '') : '')
      if (/primary|send|submit/i.test(cls) || /发送|提交|send|submit/i.test(label)) { hit = node; break }
      node = node.parentElement
    }
    if (!hit) return
    var btn = t.closest('button,[role="button"]') || hit
    var r = btn.getBoundingClientRect ? btn.getBoundingClientRect() : null
    if (r && (r.width <= 0 || r.height <= 0)) return
    dropLocalQuote()
  }

  // 服务端清引用（× 与关面板都走这里）：本地立刻清、UI 立刻收，服务端失败不回滚
  function clearQuote() {
    quoteRef = null
    quoteSynced = false
    stopQuotePoll()
    try { api('POST', 'quote', { clear: true }).catch(function () {}) } catch (e) {}
    stopFollow()
    renderQuoteBar()
  }

  function setQuote(q) {
    quoteRef = q
    quoteSynced = false
    renderQuoteBar()
    syncQuoteToServer()      // 一选就交给 Host，等用户自己按回车发消息
    watchQuoteOnServer()     // Host 消费掉之后前端要自己退场
    var node = officialComposer()
    if (node) { try { node.focus() } catch (e) {} }
  }

  function officialComposer() {
    try {
      var col = document.querySelector('[class*="centerCol"]')
      if (!col) return null
      var tas = col.querySelectorAll('textarea')
      for (var i = 0; i < tas.length; i++) {
        var r = tas[i].getBoundingClientRect()
        if (r.width > 120 && r.height > 0) return tas[i]
      }
      return col.querySelector('[contenteditable="true"]')
    } catch (e) { return null }
  }

  // 点别处收起点开的 ⋯ 菜单。
  // 注：这条原来挂在 ui.js 的旧菜单变量上（那个变量只由已被删掉的旧渲染器写），
  // 对右栏自己的菜单其实从来没生效过 —— 2026-09-14 挪到这里，用的是本模块的 openMenuId。
  function onDocClick(ev) {
    if (!openMenuId) return
    var t = ev.target
    if (t && t.closest && (t.closest('.cfw-menu') || t.closest('.cfw-more'))) return
    openMenuId = ''
    render()
  }

  // 点别处收起点开的 ⋯ 菜单（转交给当前实例，见下）；顺带挂"发送即收框"的两个监听。
  function wireDocClick() {
    if (!window.__cfwWired) window.__cfwWired = {}
    var W = window.__cfwWired
    if (!W.send) {
      W.send = true
      document.addEventListener('keydown', function (ev) {
        var api = window.__cfwRight
        if (api && typeof api.onSendKey === 'function') api.onSendKey(ev)
      }, true)
      document.addEventListener('click', function (ev) {
        var api = window.__cfwRight
        if (api && typeof api.onSendClick === 'function') api.onSendClick(ev)
      }, true)
    }
    if (!W.doc) {
      W.doc = true
      document.addEventListener('click', function (ev) {
        var api = window.__cfwRight
        if (api && typeof api.onDocClick === 'function') api.onDocClick(ev)
      }, true)
    }
    if (!W.open) {
      W.open = true
      /* A20（2026-09-21 用户要求「最好所有文件都用本机默认应用打开吧」）：
         `file:` 链接**不要让浏览器再下载一份** —— 改为 POST `/api/open`，由宿主用系统默认应用打开。
         `img:` 不受影响（它走 `<img src>`，必须取字节）。
         失败时**回落到原来的字节路由**（至少还能下载），并把原因写在这条链接后面 —— 不静默失败。 */
      document.addEventListener('click', function (ev) {
        var a = ev.target
        while (a && a !== document && !(a.tagName === 'A' && a.getAttribute && a.getAttribute('data-cfw-open'))) {
          a = a.parentNode
        }
        if (!a || a === document || !a.getAttribute) return
        var enc = a.getAttribute('data-cfw-open')
        if (!enc) return
        ev.preventDefault()
        var note = function (txt) {
          var box = a.parentNode
          if (!box) return
          var old = box.querySelector('.cfw-open-note[data-for="' + enc + '"]')
          if (old) { old.textContent = txt; return }
          var s = document.createElement('span')
          s.className = 'cfw-open-note'
          s.setAttribute('data-for', enc)
          s.textContent = txt
          box.insertBefore(s, a.nextSibling)
        }
        var fallback = function (why) {
          note('（' + why + '，改用下载）')
          try { window.open(a.getAttribute('href'), '_blank') } catch (e) {}
        }
        note('（正在用默认应用打开…）')
        var raw = enc
        try { raw = decodeURIComponent(enc) } catch (e) {}
        fetch('/chat-feed/api/open', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ p: raw }),
        }).then(function (r) {
          return r.json().catch(function () { return {} }).then(function (j) { return { s: r.status, j: j || {} } })
        }).then(function (r) {
          if (r.j && r.j.ok) { note('（已用默认应用打开）'); return }
          fallback((r.j && r.j.error) || ('HTTP ' + r.s))
        }).catch(function (e) { fallback(String(e)) })
      }, true)
    }
    if (!W.resize) {
      W.resize = true
      // 窗口尺寸变了要重算引用框位置（它是按输入区实测矩形摆的，不重算就会飘）
      window.addEventListener('resize', function () {
        var api = window.__cfwRight
        if (api && typeof api.reposition === 'function') api.reposition()
      })
    }
  }

  /* ------------------------------------------------------- 对外接口 */
  function mount(env) {
    el = env.el
    api = env.api
    // —— 面板结构：挂载时取一次，之后每 10 秒重取 → **改 panel.json 即时生效**（热更新，不用刷页/重启）——
    ;(function loadPanel() {
      var tick = function () {
        try {
          Promise.resolve(api('GET', 'panel')).then(function (r) {
            if (r && r.sections && r.sections.length) {
              var before = panelCfg ? JSON.stringify(panelCfg.sections) : ''
              panelCfg = r
              if (before !== JSON.stringify(r.sections) && typeof render === 'function') render()
            }
          }).catch(function () {})
        } catch (e) {}
      }
      tick()
      if (panelTimer === null) { try { panelTimer = setInterval(tick, 10000) } catch (e) {} }
    })()
    store = env.store
    onError = env.onError || function () {}
    listNode = env.getListNode()
    barNode = env.getBarNode ? env.getBarNode() : null
    injectStyle()
    wireDocClick()
    // ⚠ 这里原来"刷新后按 /state 的 quoteNo/quoteText 把灰条恢复回来"。
    // 2026-09-15 实测它是有害的：Host 重建后内存里的待发引用已经没了，恢复出来的框没有
    // 服务端对象——引用发不出去、框也永远不消失（用户报"我发送的时候引用框没有消失，且没有注入"）。
    // 现在引用框只由**本页自己 POST 成功的那一条**驱动（服务端回包带 for 字段）。
    renderQuoteBar()
    return { render: render, setQuote: setQuote }
  }

  var API = {
    mount: mount,
    render: render,
    setQuote: setQuote,
    onDocClick: onDocClick,
    onSendKey: onSendKey,
    onSendClick: onSendClick,
    // 显式丢弃待发引用（关面板时由 ui.js 调用）：本地清 + 通知 Host clear，别等定时器兜底
    clearQuote: function () {
      try { clearQuote() } catch (e) {}
    },
    // 重摆引用框：窗口 resize、面板开合、以及外部任何"几何可能变了"的时刻都由它兜底。
    // 常态跟随不靠这个，靠 renderQuoteBar 启动的 250ms 贴身定时器（见 followTick）。
    reposition: function () {
      try {
        var bar = document.getElementById('cfw-quotebar')
        if (bar && String(bar.className).indexOf('cfw-quotebar-on') >= 0) {
          attachQuoteBar(bar)
          setReveal(applyQuoteSize(bar), true)
          lastGeom = geomKey(bar, composerBox())
          startFollow()
        } else stopFollow()
      } catch (e) {}
    },
    // 自检用：这一份到底有没有被 mount（listNode 还在不在文档里）
    debug: function () {
      return {
        version: API.version,
        mounted: listNode !== null,
        inDoc: !!(listNode && listNode.isConnected),
        wired: window.__cfwWired ? Object.keys(window.__cfwWired).join(',') : '',
        quote: quoteRef ? quoteRef.no : '',
      }
    },
    version: '2026-09-13-newbadge-inline',
  }
  window.__cfwRight = API
  // 挂监听不依赖 mount()：脚本一执行就挂（反正它会转交给当前实例）。
  wireDocClick()
})()
