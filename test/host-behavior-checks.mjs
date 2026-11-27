// Isolated regression probes: evaluate current source with in-memory services only.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const dir=path.dirname(fileURLToPath(import.meta.url));
// 这个文件在 test/ 下（2026-09-25 从 docs/audit-2026-09-20/ 迁来）：它是**验收探针**，不是文档。
const body=fs.readFileSync(path.resolve(dir,'../lib/host-body.txt'),'utf8');
const results=[];
{
  const source=body.slice(body.indexOf('const TPL ='),body.indexOf('const DEMO_ITEMS'));
  const tpl=new Function('CF','AGENT_ROOT','AGENT_CWD','INBOX_DIR',source+'return TPL;')(
    {pkgDir:'P',localDir:'L',python:'python'},'A','W','I');
  record('H27_round_cursor_uses_last_successful_delivery',
    ['2026-09-26 12:00 CST','无（首次运行）','I'],
    [tpl('{since}',null,null,Date.UTC(2026,8,26,4)),tpl('{since}',null,null,0),tpl('{inbox}')]);
}
// 路由层通用化（A29）后，切出来的片段会引用这些**外部常量**，而探针作用域里没有它们。
// 按项目既有约定「定义在片段内」：给每个片段前置一段线路常量。
// 故意**不**声明 DEFAULT_ROUTE / PROBE_URL —— 那两个本来就是按参数注入的，重名会撞。
const ROUTE_SHIM = "const ROUTES=[{id:'thu',label:'线路1·免费',ctxRatio:0.75},{id:'paratera',label:'paratera',ctxRatio:0.5}];"
  + "const R0='thu',R1='paratera';const routeIds=()=>ROUTES.map(r=>r.id);"
  + "const routeDef=(id)=>ROUTES.find(r=>String(r.id)===String(id))||ROUTES[0];const ctxRatioOf=()=>0.75;\n";
function chunk(a,b){const start=body.indexOf(a), end=body.indexOf(b,start+a.length);if(start<0||end<0)throw Error(a);return ROUTE_SHIM + body.slice(start,end);}
function record(id, expected, actual){results.push({id,expected,actual,pass:JSON.stringify(expected)===JSON.stringify(actual)});}
{
 const S={busy:true,busyFor:'test-session',busySawOpen:true,busyBase:0,autoRetry:true,retryCount:0};let prompts=0;
 const check=new Function('S','ctx','turnState','turnEnds','saveState','checkCtx','cstHM','noteError','FAKE_SIGNAL',
   'routeOfActive','triggerRound',chunk('const checkBusy = async () => {','// 自动：')+'return checkBusy;')(
   S,{get:()=>({prompt:async()=>prompts++})},async()=>({open:false,ends:1,lastReason:'error'}),async()=>1,
   async()=> 'saved',async()=>{},()=>'',()=>{},{},()=> 'thu',()=>({ok:true}));
 await check();record('H01_error_auto_retry',1,prompts);
}
// Exercise stream truncation detection, persistence, backoff and halt behavior.
// Ordinary failures continue to follow the normal retry policy.
async function busyProbe(S, turnStateImpl) {
  const prompts = [], triggers = [];
  const src = chunk('const checkBusy = async () => {', '// 自动：') + 'return checkBusy;';
  const fn = new Function('S','ctx','turnState','turnEnds','saveState','checkCtx','cstHM','noteError','FAKE_SIGNAL',
    'routeOfActive','triggerRound', src);
  const cb = fn(S, { get: () => ({ prompt: async (p) => { prompts.push(p) } }) }, turnStateImpl,
    async () => 7, async () => 'saved', async () => {}, () => '18:00', () => {}, {},
    () => 'thu', (reason, opts) => { triggers.push({ reason, opts }); return { ok: true } });
  await cb();                      // ← 构造出来的是"装着 checkBusy 的工厂"，必须真的调一次
  return { prompts, triggers };
}
const FLAKY = 'Unterminated string in JSON at position 4705 (line 1 column 4706)';
const stFlaky = async () => ({ open: false, ends: 7, lastReason: 'error', lastErrorMsg: FLAKY });
{
  const S = { busy: true, busyFor: 'sess-1', busySawOpen: true, busyBase: 0, autoRetry: true, retryCount: 0 };
  const r = await busyProbe(S, stFlaky);
  record('H36_flaky_stream_signature_is_recorded_and_backed_off',
    { prompts: 1, flakyCount: 1, backoffMs: 60000, kept: true, retryTextMentionsStream: true },
    { prompts: r.prompts.length, flakyCount: S.streamFlakyCount,
      backoffMs: S.retryAt - Date.now() > 55000 && S.retryAt - Date.now() <= 60000 ? 60000 : (S.retryAt - Date.now()),
      kept: String(S.lastStreamError).indexOf('Unterminated string') === 0 && (S.streamErrors || []).length === 1,
      retryTextMentionsStream: String((r.prompts[0] || {}).content?.[0]?.text || '').indexOf('流式截断') >= 0 });
}
{
  const S = { busy: true, busyFor: 'sess-1', busySawOpen: true, busyBase: 0, autoRetry: true, retryCount: 2,
              retryAt: Date.now() + 45 * 1000 };
  const r = await busyProbe(S, stFlaky);
  record('H37_backoff_window_does_not_pester_the_session',
    { prompts: 0, stillBusy: true, noteMentionsWait: true },
    { prompts: r.prompts.length, stillBusy: S.busy === true, noteMentionsWait: String(S.note || '').indexOf('退避中') >= 0 });
}
{
  // 用户 2026-10-01 定案：**试满不许换线路**（「他自己服务侧就是会有问题，像现在回复继续就好了，
  //   不然你这不必然切到 paratera 去了」）⇒ 停在原会话 + 留痕，等下一轮或手点获取。
  const S = { busy: true, busyFor: 'sess-1', busySawOpen: true, busyBase: 0, autoRetry: true, retryCount: 5 };
  const r = await busyProbe(S, stFlaky);
  record('H38_exhausted_flaky_stops_without_switching_route',
    { prompts: 0, fired: 0, noteMentionsStop: true, notePointsToLastStreamError: true },
    { prompts: r.prompts.length, fired: r.triggers.length,
      noteMentionsStop: String(S.note || '').indexOf('先停下') >= 0,
      notePointsToLastStreamError: String(S.note || '').indexOf('lastStreamError') >= 0 });
}
{
  // 普通错误（非该签名）：**老行为一字不变** —— cap 3、不退避、续跑文本就是「继续」
  const S = { busy: true, busyFor: 'sess-1', busySawOpen: true, busyBase: 0, autoRetry: true, retryCount: 0 };
  const r = await busyProbe(S, async () => ({ open: false, ends: 3, lastReason: 'error',
    lastErrorMsg: 'Stream ended without finish_reason' }));
  record('H39_other_errors_keep_the_old_retry_behaviour',
    { prompts: 1, retryAt: 0, text: '继续', flakyCount: 0 },
    { prompts: r.prompts.length, retryAt: Number(S.retryAt || 0), text: (r.prompts[0] || {}).content?.[0]?.text,
      flakyCount: Number(S.streamFlakyCount || 0) });
  const S2 = { busy: true, busyFor: 'sess-1', busySawOpen: true, busyBase: 0, autoRetry: true, retryCount: 3 };
  const r2 = await busyProbe(S2, async () => ({ open: false, ends: 3, lastReason: 'error', lastErrorMsg: 'x' }));
  record('H40_other_errors_stop_after_three', { prompts: 0, fired: 0 },
    { prompts: r2.prompts.length, fired: r2.triggers.length });
}
{
 const S={items:[{id:'demo'}]},fsSvc={resolve:async x=>x,readText:async()=>JSON.stringify({items:[]})};
 const load=new Function('S','fsSvc','STATE_FILE',chunk('const loadState = async () => {','const readArchived =')+'return loadState;')(S,fsSvc,'memory');
 await load();record('H02_empty_items_restore',[],S.items);
}
{
 const handlers={},S={items:[{id:'a',text:'old',done:true}]};
 new Function('route','routeOk','S','saveState','collectRunFailed','cstHM',chunk("routeOk.items = route('POST', 'items'",'routeOk.item = route'))((method,name,fn)=>(handlers[name]=fn),{},S,async()=> 'save-fail',async()=> '',()=> '00:00');
 const response=await handlers['items-patch']({upsert:[{id:'a',text:'new'}]});
 record('H03_patch_persist_failure','save-fail',response.persist);
 record('H04_patch_preserve_done',true,S.items[0].done);
 const many=Array.from({length:301},(_,i)=>({id:'i'+i,text:'test'}));
 const r=await handlers.items({items:many});record('H05_301_items_preserved_or_rejected',true,r.ok===false||S.items.length===301);
}
{
 const S={busy:false,sessionId:'test',routePick:'paratera',lastCollectAt:1};let prompts=0;
 const fire=new Function('S','cstDay','turnEnds','roundPrompt','roundPromptLive','FAKE_SIGNAL','noteError','saveState',chunk('const fireRound = async (sc, reason, pick, mode, probeRes) => {','// ---- 上下文用量探测')+'return fireRound;')(S,()=> '2026-09-20',async()=>0,()=>'',async()=>'',{},()=>{},async()=> 'saved');
 await fire({prompt:async()=>prompts++},'manual',{},'full',{});
 record('H06_cursor_waits_for_successful_delivery',1,S.lastCollectAt);
}
{
 const S={busy:false,routePick:'paratera'};let fires=0;
 const trigger=new Function('S','ctx','pluginProbe','pickRoute','fireRound','saveState','cstHM','cstDay',chunk('const triggerRound = async (reason, opts) => {','// 真正把提示词发出去')+'return triggerRound;')(S,{get:()=>({})},async()=>{await new Promise(r=>setTimeout(r,5));return {ok:true,route:'paratera'};},async()=>({ok:true}),async()=>{fires++;S.busy=true;return {ok:true};},async()=>{},()=>'',()=> '2026-09-20');
 await Promise.all([trigger('manual',{probeRoute:'paratera'}),trigger('manual',{probeRoute:'paratera'})]);
 record('H07_concurrent_collect_single_dispatch',1,fires);
}
{
 const S={};let requested='';
 const probe=new Function('S','DEFAULT_ROUTE','PROBE_URL','fetch','saveState',chunk('const pluginProbe = async (want) => {','// 载入后')+'return pluginProbe;')(S,'paratera',{thu:'synthetic-thu',paratera:'synthetic-paratera'},async url=>{requested=url;return {status:200};},async()=>{});
 const r=await probe();record('H08_default_probe_route_matches_target',{requested:'synthetic-paratera',route:'paratera'},{requested,route:r.route});
}
{
 // A100（2026-10-01 用户报「图片显示不出来」）：条目把路径写成 `output/window/images/…`，
 //   而提示词里那条相对路径的**根就是 `{profile}\output`** ⇒ 拼出来 `…\output\output\window\…` 一律 404
 //   （实测：同一张图去掉 `output/` 前缀就 200 image/png）。
 //   修法＝`fileCandidates` 再试一次"抹掉开头的 output/"，且仍逐个过 `inRoot()`（可读范围不扩大）。
 const ROOT = 'P:\\output';
 const src = chunk('const fileCandidates = (p) => {', 'const serveLocal = ()');
 const mk = () => new Function('FILE_ROOTS', 'inRoot', src + 'return fileCandidates;')(
   [ROOT],
   (abs) => String(abs).toLowerCase().indexOf(ROOT.toLowerCase()) === 0);
 const fc = mk();
 const withPrefix = fc('output/window/images/grp/abc_h.png');
 const withoutPrefix = fc('window/images/grp/abc_h.png');
 const outside = fc('../secret.txt');
 record('H35_file_candidate_tolerates_a_spurious_output_prefix',
   { withPrefixResolves: true, bothSame: true, dotDotRejected: true, stillInsideRoot: true },
   { withPrefixResolves: withPrefix.some((c) => c.toLowerCase() === (ROOT + '\\window\\images\\grp\\abc_h.png').toLowerCase()),
     bothSame: withoutPrefix.some((c) => c.toLowerCase() === (ROOT + '\\window\\images\\grp\\abc_h.png').toLowerCase()),
     dotDotRejected: outside.length === 0,
     stillInsideRoot: fc('output/window/x.png').every((c) => c.toLowerCase().indexOf(ROOT.toLowerCase()) === 0) });
}
// A19（2026-09-21 追加，用户报「启用了自动今天却没有自动」）：把自动 tick 抽出来单跑。
// A99（2026-10-01 用户定案口径）：**Auto ＝「过了 auto 时间还没跑过 auto，就立刻跑」**，
//   判据从"今天跑过没"改成"上次成功跑过的时刻 vs 最近一个应跑时刻"，所以探针要**给一个真实的 now**，
//   `cstDay/cstHM` 必须按传入的 ms 算（旧版是常量函数，测不出跨天/跨欠账）。
const PREV_DAY_SRC = (() => {
  const start = body.indexOf('const prevDayOf =');
  return body.slice(start, body.indexOf('};', start) + 2);
})();
const CST_AT = (nowMs) => (ms) => new Date((ms === undefined ? nowMs : Number(ms)) + 8 * 3600 * 1000);
const prevDayOf = new Function(PREV_DAY_SRC + 'return prevDayOf;')();
async function autoTick(S, nowMs, opts) {
  const o = opts || {};
  let fires = 0, captured = null;
  const reasons = [];
  const timerSvc = { interval: (cb) => { captured = cb; return null; } };
  const fn = new Function('timerSvc', 'S', 'checkBusy', 'checkCtx', 'cstDay', 'cstHM', 'prevDayOf', 'saveState', 'triggerRound', 'noteError', 'ctx', 'turnState',
    chunk('const offTick = timerSvc.interval(async () => {', '}, 30000);') + '}, 30000); return offTick;');
  fn(timerSvc, S, async () => {}, async () => {}, (ms) => CST_AT(nowMs)(ms).toISOString().slice(0, 10),
    (ms) => CST_AT(nowMs)(ms).toISOString().slice(11, 16), prevDayOf, async () => o.persist ?? 'saved',
    (reason) => { fires += 1; reasons.push(String(reason || '')); return { ok: true }; }, () => {},
    // A105：补跑闸门会独立问一次会话有没有未结束的回合 ⇒ 探针给一个可控的 turnState
    { get: () => (o.noSessionController ? null : {}) },
    async () => (o.turnState === undefined ? { open: false, ends: 0, lastReason: '', ask: null } : o.turnState));
  await captured();
  return { fires, reasons, S };
}
const AT = (iso) => Date.parse(iso);
{
 // 09-20 真实字段值：auto=true / autoTime=23:30 / collectDay=2026-09-20 / autoFiredDay=''
 //   旧代码在这里回 0 次（被 collectDay 拦掉），修好后必须触发 1 次。
 const S = { auto: true, autoTime: '23:30', busy: false, collectDay: '2026-09-20', autoFiredDay: '' };
 record('H09_auto_not_cancelled_by_manual_round', 1, (await autoTick(S, AT('2026-09-20T23:30:00+08:00'))).fires);
 // 已经在"最近这个应跑时刻"之后跑过 ⇒ 不欠（旧判据看 autoFiredDay，现在看上次成功的时刻）
 record('H10_auto_dedup_by_last_success', 0,
   (await autoTick({ auto: true, autoTime: '23:30', busy: false, autoLastOkAt: AT('2026-09-20T23:31:00+08:00') },
     AT('2026-09-20T23:31:00+08:00'))).fires);
 // 刚跑过 80 分钟、还没跨过下一个 23:30 ⇒ 不欠
 record('H11_auto_not_due_before_next_boundary', 0,
   (await autoTick({ auto: true, autoTime: '23:30', busy: false, autoLastOkAt: AT('2026-09-20T23:30:00+08:00') },
     AT('2026-09-21T00:50:00+08:00'))).fires);
 // A99 的核心：**宿主整晚没开**（09-30 23:30 时进程不在）⇒ 次日 14:00 一起来就该补跑
 record('H33_missed_night_fires_on_next_start', 1,
   (await autoTick({ auto: true, autoTime: '23:30', busy: false, autoLastOkAt: AT('2026-09-28T23:30:21+08:00') },
     AT('2026-10-01T14:00:00+08:00'))).fires);
 // 从没跑过 ⇒ 立刻跑（首次启用）
 record('H34_never_ran_fires_immediately', 1,
   (await autoTick({ auto: true, autoTime: '23:30', busy: false }, AT('2026-10-01T09:00:00+08:00'))).fires);
 // A108（2026-11-21 用户："闪退刚启动聊天摘要就启动了"）：**刚挂载的 15 分钟内不补欠账**。
 //   实测：2026-11-21 20:55:48 宿主启动、20:56:40 就发了一整轮。挂载时间用 Date.now() 的"刚才"来模拟。
 record('H65_startup_grace_blocks_missed_round_catchup', 0,
   (await autoTick({ auto: true, autoTime: '23:30', busy: false, autoLastOkAt: 0, mountedAt: Date.now() - 60 * 1000 },
     Date.now())).fires);
 // 过了宽限期，欠账照跑（不能因为加了宽限就永远不补）
 record('H66_missed_round_fires_after_grace', 1,
   (await autoTick({ auto: true, autoTime: '23:30', busy: false, autoLastOkAt: 0, mountedAt: Date.now() - 20 * 60 * 1000 },
     Date.now())).fires);
 record('H69_first_state_write_denial_stops_auto', 0,
   (await autoTick({auto: true, autoTime: '23:30'}, AT('2026-11-23T23:30:00+08:00'),
     {persist: 'save-fail'})).fires);
 // A111（2026-11-23）：**落盘被拒时，已挂着的 pendingCollect 也不许补跑**。
 //   旧顺序先判 pending 再判 saveBlocked，于是"写不进去"的那一晚照样把一整轮排上去。
 record('H67_save_blocked_stops_pending_resume', 0,
   (await autoTick({ auto: false, busy: false, saveBlocked: true, sessionId: 'session-x', mountedAt: Date.now() - 20 * 60 * 1000,
              pendingCollect: { day: '2026-11-21', at: Date.now() - 11 * 60 * 1000, resumes: 0, sessionId: 'session-x' } },
     Date.now())).fires);
}
{
 // A112（2026-11-23）：借会话策略的三条硬边界 —— 只借"cwd 就是私人根"的真实 Session；
 //   cwd 不匹配或会话不存在时用部署默认；会话只读策略原样下传。
 const src = (() => {
   const a = body.indexOf('const privatePolicy = () => {');
   return body.slice(a, body.indexOf('const saveState = async () => {', a));
 })();
 const mk = (S, sessions, resolved) => new Function('S', 'ctx', 'STATE_DIR', src + 'return privatePolicy;')(
   S, { get: (n) => (n === 'sessions' ? sessions : (n === 'sandboxPolicy' ? { resolve: () => resolved } : undefined)) },
   'R:\\fixture-private');
 const okSession = { header: { cwd: 'R:\\fixture-private' } };
 const wrongCwd = { header: { cwd: 'Z:/unrelated-digest-test-fixture' } };
 const pol = { mode: 'workspace-write', writableRoots: ['R:\\fixture-private'] };
 record('H68_policy_bound_only_to_the_matching_session',
   { matched: true, wrongCwd: false, missing: false, readOnly: true },
   { matched: !!mk({ sessionId: 's1' }, { get: () => okSession }, pol)(),
     wrongCwd: !!mk({ sessionId: 's1' }, { get: () => wrongCwd }, pol)(),
     missing: !!mk({ sessionId: 's1' }, { get: () => undefined }, pol)(),
     readOnly: !!mk({ sessionId: 's1' }, { get: () => okSession }, { mode: 'read-only' })() });
}
{
 // A21（2026-09-22）：**未交付的轮要能自动补跑**。实测 2026-09-21 23:30 那轮请求过但没交付
 //   （提问没人回答 → turn 被 interrupted），`pendingCollect` 一直挂着却**没有任何东西把它接上**。
 //   `auto:false` 也要补 —— 它是"把已请求的那一轮做完"，不是"新起一轮"。
 const S = { auto: false, autoTime: '23:30', busy: false, autoFiredDay: '2026-09-21', resumeCount: 0, sessionId: 'session-x',
             pendingCollect: { day: '2026-09-21', at: Date.now() - 11 * 60 * 1000, resumes: 0, sessionId: 'session-x' } };
 const t12 = await autoTick(S, AT('2026-09-22T10:30:00+08:00'), { awaitTick: true, turnState: { open: false, ends: 1, lastReason: 'interrupted', ask: null } });
 record('H12_undelivered_round_resumes', 1, t12.fires);
 // A105（2026-11-16 用户报「一天发两次同样的提示词」）：**会话还有没结束的回合时绝不补跑**。
 //   实测 2026-11-15：第一轮 23:30:02 发车、回合 23:45:04 才结束，可 23:40:32 补跑就发出去了。
 {
   const S2 = { auto: false, autoTime: '23:30', busy: false, autoFiredDay: '2026-09-21', resumeCount: 0, sessionId: 'session-x',
                pendingCollect: { day: '2026-09-21', at: Date.now() - 11 * 60 * 1000, resumes: 0, sessionId: 'session-x' } };
   const t = await autoTick(S2, AT('2026-09-22T10:30:00+08:00'), { awaitTick: true, turnState: { open: true, ends: 0, lastReason: '', ask: null } });
   record('H63_resume_skipped_while_turn_still_open', 0, t.fires);
 }
 // 读不到会话（控制器缺失）⇒ 也不补跑：宁可晚一轮，也不凭空再发一份提示词
 {
   const S3 = { auto: false, autoTime: '23:30', busy: false, autoFiredDay: '2026-09-21', resumeCount: 0,
                pendingCollect: { day: '2026-09-21', at: Date.now() - 11 * 60 * 1000, resumes: 0 } };
   const t = await autoTick(S3, AT('2026-09-22T10:30:00+08:00'), { awaitTick: true, noSessionController: true });
   record('H64_resume_skipped_without_session_controller', 0, t.fires);
 }
 // 同一轮只补一次（补过就不再补，避免一天两次同样的东西）
 record('H13_resume_capped_at_one_per_round', 0, (await autoTick({ auto: false, busy: false, resumeCount: 3, autoFiredDay: '2026-09-21',
             pendingCollect: { day: '2026-09-21', at: Date.now() - 11 * 60 * 1000, resumes: 1 } }, AT('2026-09-22T10:30:00+08:00'))).fires);
 // 刚触发不到 10 分钟 ⇒ 不补（否则会和正常那一轮打架）
 record('H14_resume_waits_10min', 0, (await autoTick({ auto: false, busy: false, resumeCount: 0, autoFiredDay: '2026-09-21',
             pendingCollect: { day: '2026-09-22', at: Date.now() - 60 * 1000 } }, AT('2026-09-22T10:30:00+08:00'))).fires);
}
{
 // A22（2026-09-22）：**读出"主 agent 正在等你回答的提问"**。
 //   输入用 2026-09-21 那轮的真实形状：turn/start → tool/call ask_user_question（之后没有 tool/result）。
 const askEv = { type: 'tool/call', time: 1790004959158, data: { turn: 4, step: 6, callId: 'call_ask_1',
   name: 'ask_user_question', arguments: JSON.stringify({ questions: [{ header: '清理①已勾选', id: 'cleanup_done',
     question: '上一轮后你勾了 15 条，按惯例要删掉，确认吗？', options: [{ label: '全部删掉' }, { label: '先都留着' }] }] }) } };
 const mk = (evs) => {
   const ts = new Function('S', 'FAKE_SIGNAL',
     chunk('const turnState = async (sc, sid) => {', '// ---- 双会话') + 'return turnState;')({}, {});
   return ts({ inspect: async () => ({ events: evs }) }, 'sid');
 };
 const st1 = await mk([{ type: 'turn/start', data: { turn: 4 } }, askEv]);
 const q0 = (st1.ask && st1.ask.questions && st1.ask.questions[0]) || {};
 record('H15_pending_ask_detected', { pending: true, header: '清理①已勾选', options: 2 },
        { pending: !!st1.ask, header: q0.header || '', options: q0.options ? q0.options.length : 0 });
 const st2 = await mk([{ type: 'turn/start', data: { turn: 4 } }, askEv, { type: 'tool/result', data: { callId: 'call_ask_1' } }]);
 record('H16_answered_ask_not_pending', false, !!st2.ask);
 // 提问所属的 turn **已经结束** ⇒ 也不算"在等你"（2026-09-21 turn 4 的提问永远不会有人回答，
 //   只看"有没有 tool/result"会把它永远当成待回答）
 const st3 = await mk([{ type: 'turn/start', data: { turn: 4 } }, askEv, { type: 'turn/end', data: { turn: 4, reason: { kind: 'interrupted' } } }]);
 record('H17_ask_of_ended_turn_not_pending', false, !!st3.ask);
}
// A18（2026-09-22 补）：`loadState` 的**损坏隔离 / 备份恢复 / 旧路径迁移**三条路径。
//   审计 A18 的验收原文就要求"状态 schema/version、损坏隔离、备份与恢复步骤"，
//   而 H02 只验了"空列表能恢复"。这里把另外三条也变成能红能绿的探针。
function loadStateWith(S, files, stateFile, stateOld, saveCalls) {
  const wrote = {};
  const fsSvc = {
    resolve: async (x) => x,
    readText: async (p) => { if (p in files) return files[p]; throw Object.assign(new Error('Missing synthetic file'), { code: 'FS_NOT_FOUND' }) },
    writeText: async (p, c) => { wrote[p] = c; files[p] = c },
  };
  const args = ['S', 'fsSvc', 'STATE_FILE', 'STATE_OLD', 'saveState'];
  const src = chunk('const loadState = async () => {', 'const readArchived =') + 'return loadState;';
  const load = new Function(...args, src)(S, fsSvc, stateFile, stateOld,
    async () => { saveCalls.push(1); return 'saved' });
  return { load, wrote };
}
{
 // 损坏件 + 可用 .bak ⇒ 从 .bak 恢复，且坏件被**另存**为 .corrupt-<ts>（不是删掉）
 const files = { memory: '{"items":[{"id":"demo"}]', 'memory.bak': '{"items":[{"id":"from-bak"}],"sessionId":"s1"}' };
 const saveCalls = [];
 const { load, wrote } = loadStateWith({ items: [] }, files, 'memory', 'C:\\old\\state.json', saveCalls);
 const S = { items: [] };
 const h = loadStateWith(S, files, 'memory', 'C:\\old\\state.json', saveCalls);
 const rc = await h.load();
 record('H18_corrupt_state_restores_from_bak',
        { rc: 'restored', id: 'from-bak', quarantined: true, quarantinedKeepsRaw: true },
        { rc: rc, id: (S.items[0] || {}).id || '',
          quarantined: Object.keys(h.wrote).some((k) => k.indexOf('memory.corrupt-') === 0),
          quarantinedKeepsRaw: Object.keys(h.wrote).some((k) => k.indexOf('memory.corrupt-') === 0 && h.wrote[k] === files.memory) });
}
{
 // 损坏件 + 没有 .bak ⇒ 阻止无状态采集，"不存在"与"损坏"必须分得开
 const files = { memory: '{broken' };
 const saveCalls = [];
 const S = { items: [] };
 const h = loadStateWith(S, files, 'memory', 'C:\\old\\state.json', saveCalls);
 record('H19_corrupt_without_bak_blocks_reads', 'read-fail', await h.load());
}
{
 // 新位置没有、旧 Temp 路径有 ⇒ 迁移读取 + **立刻调 saveState 落盘到新位置**
 const files = { 'C:\\old\\state.json': '{"items":[{"id":"legacy"}],"sessionId":"s9"}' };
 const saveCalls = [];
 const S = { items: [] };
 const h = loadStateWith(S, files, 'C:\\new\\state.json', 'C:\\old\\state.json', saveCalls);
 const rc = await h.load();
 record('H20_legacy_state_migrated_and_persisted',
        { rc: 'restored', id: 'legacy', saveCalls: 1 },
        { rc: rc, id: (S.items[0] || {}).id || '', saveCalls: saveCalls.length });
}
// A23（2026-09-25 用户问"为什么多了一堆主agent"）：两条实质修复的探针。
{
 // H21：**轮换时把指向旧会话的槽一起 rebase**。旧版只 rebase 了 sessionId/mainSessionId，
 //   于是 sessParatera 会一直指着刚被归档的会话（实测 09-24 23:35：sessParatera=5899239b 已归档，
 //   当前主会话却是新建的 6c03167e）⇒ 下一轮判槽死 → 又造一个带后缀标题的新会话。
 const S = { sessionId: 'session-OLDOLDOLD', mainSessionId: 'session-OLDOLDOLD',
             sessParatera: 'session-OLDOLDOLD', sessThu: 'session-OTHER' };
 const archived = [];
 const ctxStub = { get: (n) => n === 'sessionController'
   ? { create: async () => ({ sessionId: 'session-NEWNEWNEW' }), rename: async () => {}, prompt: async () => {}, resolveAgent: async () => {} }
   : { create: async () => ({ workspace: { workspaceId: 'w1' } }), archiveSession: async (r) => { archived.push(r.sessionId); return { archivedSessionIds: archived } } } };
 const fn = new Function('ctx', 'S', 'loadState', 'createSession', 'retargetQuote', 'saveState', 'noteError',
   'FAKE_SIGNAL', 'SESSION_TITLE', 'AGENT_CWD',
   chunk('const rotateSession = async (reason, explicitOldId) => {', '// 「按需切换用哪个会话」') + 'return rotateSession;');
 const rot = fn(ctxStub, S, async () => 'restored', async () => ({ sessionId: 'session-NEWNEWNEW' }),
                () => {}, async () => 'saved', () => {}, {}, 'T', 'C:\\x');
 const r = await rot('probe');
 record('H21_rotate_rebases_route_slots',
        { archivedOld: true, paratera: 'session-NEWNEWNEW', thu: 'session-OTHER', ok: true },
        { archivedOld: archived.indexOf('session-OLDOLDOLD') >= 0, paratera: String(S.sessParatera),
          thu: String(S.sessThu), ok: !!(r && r.ok) });
}
{
 // H22：**扫出"多出来的同标题主 agent"**（排除当前会话与两个槽）。用户问这事时插件自己都不知道有这回事。
 const S = { sessionId: 'session-CUR', sessThu: '', sessParatera: 'session-PAR', extraMains: [], extraMainsAt: 0 };
 const ids = ['session-CUR', 'session-PAR', 'session-X1', 'session-X2', 'notasession', 'session-X3'];
 const ctxStub = { get: (n) => n === 'workspaceController'
   ? { create: async () => ({ workspace: { workspaceId: 'w1', sessionIds: ids } }) } : {} };
 const titles = { 'session-CUR': 'M', 'session-PAR': 'M', 'session-X1': 'M', 'session-X2': '别的', 'session-X3': 'M' };
 const fn = new Function('ctx', 'S', 'race', 'AGENT_CWD', 'readArchived', 'sessionMeta', 'isMainTitle', 'saveState',
   chunk('const scanExtraMains = async () => {', 'const adoptExistingMain =') + 'return scanExtraMains;');
 const scan = fn(ctxStub, S, (p) => p, 'C:\\x', async () => [], async (fs, id) => ({ title: titles[id] || '', createdAt: 1 }),
                 (t) => t === 'M', async () => 'saved');
 await scan();
 record('H22_extra_mains_found_excluding_current_and_slots',
        ['session-X1', 'session-X3'],
        (S.extraMains || []).map((x) => x.id));
}
// A27（2026-09-25）：`routeWhy` 必须报**实际探的那条线**。
//   旧版把"可达/不通"那句话写死成 `'probe:线路1 可达'`，探的却是 `probeRes.route`；
//   于是探 paratera 成功时 `/state` 会同时给出 `routePick=paratera` 与 `routeWhy="probe:线路1 可达"`
//   —— 自证字段当场自相矛盾（2026-09-25 实测就是这个值）。
{
  const S = { busy: false, routePick: 'paratera' };
  let gotWhy = '';
  const trigger = new Function('S', 'ctx', 'pluginProbe', 'pickRoute', 'fireRound', 'saveState', 'cstHM', 'cstDay',
    chunk('const triggerRound = async (reason, opts) => {', '// 真正把提示词发出去') + 'return triggerRound;')(
    S, { get: () => ({}) },
    async () => ({ ok: true, route: 'paratera' }),                          // 探的是 paratera，且可达
    async (route, why) => { gotWhy = String(why || ''); return { ok: true }; },
    async () => ({ ok: true }), async () => {}, () => '', () => '2026-09-20');
  await trigger('manual', {});
  record('H23_route_why_names_probed_route', { namesProbed: true, namesThu: false },
         { namesProbed: gotWhy.indexOf('paratera') >= 0, namesThu: gotWhy.indexOf('线路1') >= 0 });
}
// A61（2026-09-27 用户定案 A）：**会话 cwd 必须是它的工作区根**，否则判死、另建、把旧的退掉。
//   为什么：DSH 的可写根＝canonical(会话 cwd)（`dsh-sandbox-policy` 的 resolveWorkspaceRoot），
//   而写放行看**目标的 realpath**（`dsh-fs-sandbox` 的 checkedTarget）；插件目录里 `agent/output`、
//   `agent/docs/{knowledge,archive}` 是**联接**，realpath 落在私人 profile 里 ⇒ 会话 cwd 不是私人
//   profile（对外＝`<包>/local`）时主 agent 写产物必被拒。实测 2026-09-27 12:02:59（cwd＝包内 agent/）：
//   `SAVE-FAILED(PermissionError: [Errno 13] … \agent\output\logs\_last_http.json)`。
//   而 DSH **不许改**会话 cwd（`ensureSession` 末端无条件比对 header.cwd ⇒ ApiSessionCwdConflict）
//   ⇒ 唯一出路是不复用它。拿不到 cwd 时必须**放行**（fail-open）—— 存疑判死会重演 A29 那两个主 agent。
{
  const PKG='C:\\pkg', PRIV='C:\\priv\\profile', LOCAL=PKG+'\\local';
  const fsSvc={resolve:async(p)=>({targetKey: p===LOCAL ? PRIV : String(p)})};
  const S={sessionId:'session-NEW',mainSessionId:'session-NEW',sessThu:'',sessParatera:''};
  const archived=[];
  const ctxStub={get:(n)=> n==='workspaceController'
    ? {archiveSession:async(r)=>{archived.push(r.sessionId);return {}}} : undefined};
  const src=chunk('const cwdCanon = async (p) => {','//: DSH 家的位置')
    +'return {checkUsable,noteCwdStale,retireCwdStale};';
  const build=(metaOf,sumOf)=>new Function('fsSvc','ctx','S','AGENT_CWD','sessionMeta','sessionSummary','saveState',src)(
    fsSvc,ctxStub,S,PRIV,async(f,id)=>metaOf[id],async(sc,id)=>sumOf[id],async()=> 'saved');
  // ① 成员表里"活着"，但 cwd 还是旧的那棵树（包内 agent/）⇒ 判 stale
  const A=build({'session-A':{title:'M',cwd:PKG+'\\agent'}},{});
  const r1=await A.checkUsable({},'session-A',[],['session-A'],[]);
  // ② cwd 直接指向物理私人目录 ⇒ alive
  const B=build({'session-B':{title:'M',cwd:PRIV}},{});
  const r2=await B.checkUsable({},'session-B',[],['session-B'],[]);
  // ③ 旧联接 cwd 的 canonical 虽相同，但沙箱写入仍可能失败 ⇒ stale
  const E=build({'session-E':{title:'M',cwd:LOCAL}},{});
  const r5=await E.checkUsable({},'session-E',[],['session-E'],[]);
  // ④ 拿不到 cwd（投影缓存读不到）⇒ 放行（不能因为"看不见"就判死）
  const C=build({},{});
  const r3=await C.checkUsable({},'session-C',[],[],[]);
  // ⑤ 走 sc.list() 那条路（成员表拿不到）时同样判
  const D=build({},{'session-D':{sessionId:'session-D',cwd:'D:\\old\\ws'}});
  const r4=await D.checkUsable({},'session-D',[],[],[]);
  record('H24_session_cwd_must_be_workspace_root',
         {mismatch:false,match:true,alias:false,unknown:true,listMismatch:false},
         {mismatch:!!r1.alive,match:!!r2.alive,alias:!!r5.alive,unknown:!!r3.alive,listMismatch:!!r4.alive});
  // ⑥ 有了可用的新会话之后，因 cwd 被弃用的那些**归档掉**，并清掉还指着它的槽/锚点
  S.sessParatera='session-A';
  const A2=build({'session-A':{title:'M',cwd:PKG+'\\agent'}},{});
  await A2.checkUsable({},'session-A',[],['session-A'],[]);
  const steps=[];
  const n=await A2.retireCwdStale(steps,['session-NEW']);
  record('H25_cwd_stale_session_retired',
         {archived:['session-A'],paratera:'',retired:1},
         {archived:archived,paratera:String(S.sessParatera),retired:n});
}
// A63（2026-09-27 实测事故）：**派发一轮前必须正向断言目标会话可信**。
//   事故：16:13:39 用户点「获取」，那一轮被发进 `session-24ffb007`（cwd＝包内 `agent/` 的老会话，
//   `busyFor` 就是它）—— 它的可写边界是包目录 ⇒ 管线产物一个字写不出来、整轮白跑，还把写权限
//   探针文件写进了包里。判据取舍：判死可以 fail-open（A29 的教训），**派发必须 fail-closed**，
//   而且**不许依赖元数据**（元数据读不到就放行 —— 那正是这次的洞）⇒ 只认"亲手建过的会话"。
{
  const src = chunk('const pickRoute = async (route, why, switchModel = false) => {', '// 插件侧连通性探测') + 'return pickRoute;';
  const mk = async (trusted, options = {}) => {
    const S = { sessionId: 'session-OLD', sessParatera: 'session-OLD', sessThu: '', busy: !!options.busy };
    let switches = 0;
    const keepExisting = chunk('const ensureRouteSession = async (route, steps) => {', 'const pickRoute = async')
      + 'return ensureRouteSession;';
    const lookup = new Function('S','ctx','routeSlotKey','liveOk','noteRouteModel',keepExisting)(
      S, { get: () => ({}) }, () => 'sessParatera', async () => true,
      async () => { switches++; return {ok:true, selected:{provider:'p',model:'m'}}; });

    const fn = new Function('S', 'ensureRouteSession', 'createRouteSession', 'retireCwdStale',
      'cwdTrust', 'routeSlotKey', 'saveState', 'ROUTE_MODELS', 'noteRouteModel', 'ctx', src);
    const pick = fn(S, lookup,
      async (r, s) => { s.push('created:session-NEW'); return 'session-NEW' },
      async () => 0, () => trusted, () => 'sessParatera', async () => 'saved',
      { paratera: { provider: 'p', model: 'm', effort: 'high' }, thu: { provider: 'p', model: 'm', effort: 'high' } },
      async () => {
        switches++;
        return options.rejectSwitch ? {ok:false} : {ok:true, selected:{provider:'p', model:'m'}};
      },
      { get: () => ({}) });
    const r = await pick('paratera', 'fixture', !!options.explicit);
    return { r, S, switches };
  };
  const bad = await mk(false);
  const good = await mk(true);
  const explicit = await mk(true, { explicit:true });
  const busy = await mk(true, { explicit:true, busy:true });
  const rejected = await mk(true, { explicit:true, rejectSwitch:true });
  record('H70_model_changes_only_for_an_explicit_successful_route_request',
    { usual:0, explicit:1, busy:0, refused:false },
    { usual:good.switches, explicit:explicit.switches, busy:busy.switches, refused:rejected.r.ok });
  record('H26_untrusted_dispatch_retargeted',
         { retargeted: true, ok: true, sid: 'session-NEW', slot: 'session-NEW', step: true,
           trustedNoRetarget: false, trustedKeepsId: 'session-OLD' },
         { retargeted: !!bad.r.retargeted, ok: !!bad.r.ok, sid: bad.S.sessionId,
           slot: bad.S.sessParatera,
           step: (bad.r.steps || []).some((s) => String(s).indexOf('dispatch-retarget:') === 0),
           trustedNoRetarget: !!good.r.retargeted, trustedKeepsId: good.r.sessionId });
}
// A98（2026-10-01 用户问"凭什么 9-29 没跑"）：**打空不许烧掉一整天，而且必须留痕。**
//   实测 09-29 23:30：`autoFiredDay` 落盘成 09-29，而派发在"提示词入队"前就失败
//   （`pendingCollect`/`busy`/`note` 全是旧值、目标会话从未被唤醒），错只进了内存里的 `lastError`。
//   修法：入队成功（triggerRound 回 ok）才写 `autoFiredDay`；失败退避重试（10 分钟、同日最多 3 次）
//   并把原文写进 `lastTriggerError`。下面四条把这三件事钉住。
async function autoTickState(S, nowMs, triggerImpl) {
  let captured = null;
  const timerSvc = { interval: (cb) => { captured = cb; return null; } };
  const fn = new Function('timerSvc', 'S', 'checkBusy', 'checkCtx', 'cstDay', 'cstHM', 'prevDayOf', 'saveState', 'triggerRound', 'noteError', 'ctx', 'turnState',
    chunk('const offTick = timerSvc.interval(async () => {', '}, 30000);') + '}, 30000); return offTick;');
  fn(timerSvc, S, async () => {}, async () => {}, (ms) => CST_AT(nowMs)(ms).toISOString().slice(0, 10),
    (ms) => CST_AT(nowMs)(ms).toISOString().slice(11, 16), prevDayOf, async () => 'saved', triggerImpl, () => {},
    { get: () => ({}) }, async () => ({ open: false, ends: 0, lastReason: '', ask: null }));
  await captured();
  await new Promise((r) => setTimeout(r, 0));    // 让 then/catch 跑完
  return S;
}
{
  // ① 派发失败 ⇒ **不记账**（否则之后每次 tick 都认为"已经跑过"，这一笔欠账永久作废）
  let n1 = 0;
  const failed = await autoTickState({ auto: true, autoTime: '23:30', busy: false },
    AT('2026-09-29T23:30:00+08:00'), () => { n1 += 1; return { ok: false, error: 'collect-prompt: 会话不可用' } });
  record('H28_failed_fire_does_not_count_as_run',
    { fired: 1, autoLastOkAt: 0, tries: 1, retryScheduled: true, errorKept: true, noteSaysFailed: true },
    { fired: n1, autoLastOkAt: failed.autoLastOkAt || 0, tries: failed.autoFireRetryTries,
      retryScheduled: failed.autoFireRetryAt > Date.now(),
      errorKept: String(failed.lastTriggerError || '').indexOf('会话不可用') >= 0,
      noteSaysFailed: String(failed.note || '').indexOf('自动触发失败') >= 0 });
  // ② 入队成功才记账（autoLastOkAt），并把退避计数清零
  let n2 = 0;
  const okd = await autoTickState({ auto: true, autoTime: '23:30', busy: false, autoFireDueKey: '2026-09-29 23:30',
    autoFireRetryAt: Date.now() - 1, autoFireRetryTries: 2 }, AT('2026-09-29T23:30:00+08:00'),
    () => { n2 += 1; return { ok: true } });
  record('H29_successful_fire_is_recorded',
    { fired: 1, ran: true, autoFiredDay: '2026-09-29', tries: 0, retryAt: 0 },
    { fired: n2, ran: okd.autoLastOkAt > 0, autoFiredDay: okd.autoFiredDay, tries: okd.autoFireRetryTries, retryAt: okd.autoFireRetryAt });
  // ③ 退避窗口内不再扣扳机（10 分钟内最多一次）
  let n3 = 0;
  await autoTickState({ auto: true, autoTime: '23:30', busy: false, autoFireDueKey: '2026-09-29 23:30',
    autoFireRetryAt: Date.now() + 5 * 60 * 1000, autoFireRetryTries: 1 }, AT('2026-09-29T23:35:00+08:00'),
    () => { n3 += 1; return { ok: true } });
  record('H30_retry_backoff_blocks_refire', 0, n3);
  // ④ 同一笔欠账试满 3 次就停（不再每 30 秒撞一次）
  let n4 = 0;
  const capped = await autoTickState({ auto: true, autoTime: '23:30', busy: false, autoFireDueKey: '2026-09-29 23:30',
    autoFireRetryAt: 0, autoFireRetryTries: 3, lastTriggerError: 'collect-prompt: 会话不可用' }, AT('2026-09-29T23:59:00+08:00'),
    () => { n4 += 1; return { ok: true } });
  record('H31_auto_gives_up_after_3_failures', { fired: 0, whyMentions: true },
    { fired: n4, whyMentions: String(capped.autoWhy || '').indexOf('已失败 3 次') >= 0 });
  // ⑤ 跨过下一个 23:30 ⇒ 换了"应跑时刻"，退避计数归零、重新扣扳机
  let n5 = 0;
  await autoTickState({ auto: true, autoTime: '23:30', busy: false, autoFireDueKey: '2026-09-29 23:30',
    autoFireRetryAt: 0, autoFireRetryTries: 3 }, AT('2026-09-30T23:30:00+08:00'),
    () => { n5 += 1; return { ok: true } });
  record('H32_retry_counter_resets_on_next_boundary', 1, n5);
}

// Exercise the production opener without launching an application or using host services.
{
  const openerSource = body.slice(body.indexOf('const spawnOpen = async (abs) => {'), body.indexOf("routeOk.open = route("));
  const makeOpen = new Function('ctx', 'ENV', openerSource + 'return spawnOpen;');
  const cases = [
    { id: 'H41_open_host_resolver', resolver: async () => 'R:/system/cmd.exe', env: { ComSpec: 'S:/system/cmd.exe' }, file: 'R:/folder with space/中文/file.txt', exe: 'R:/system/cmd.exe', cwd: 'R:/folder with space/中文' },
    { id: 'H42_open_comspec', env: { ComSpec: 'S:/system/cmd.exe' }, file: 'R:/folder/file.txt', exe: 'S:/system/cmd.exe', cwd: 'R:/folder' },
    { id: 'H43_open_resolver_failure_fallback', resolver: async () => { throw new Error('synthetic'); }, env: { ComSpec: 'S:/system/cmd.exe' }, file: 'R:/folder/file.txt', exe: 'S:/system/cmd.exe', cwd: 'R:/folder' },
    { id: 'H44_open_root_file_has_absolute_cwd', env: { ComSpec: 'S:/system/cmd.exe' }, file: 'R:/file.txt', exe: 'S:/system/cmd.exe', cwd: path.win32.normalize('R:/') },
    { id: 'H45_open_missing_command_fails_closed', env: {}, file: 'R:/file.txt', fails: true },
    { id: 'H46_open_non_string_resolver_falls_back', resolver: async () => ({ unexpected: true }), env: { ComSpec: 'S:/system/cmd.exe' }, file: 'R:/folder/file.txt', exe: 'S:/system/cmd.exe', cwd: 'R:/folder' },
  ];
  for (const c of cases) {
    const calls = [];
    const sp = { spawn: (request) => { calls.push(request); return { done: Promise.resolve() }; } };
    if (c.resolver) sp.resolveExecutable = c.resolver;
    const open = makeOpen({ get: () => sp }, c.env);
    const response = await open(c.file);
    const ok = c.fails ? response.ok === false && calls.length === 0 : response.ok === true && calls.length === 1 && calls[0].argv[0] === c.exe && calls[0].argv[4] === c.file && calls[0].cwd === c.cwd;
    record(c.id, true, ok);
  }
}

// A114/A115（2026-11-26 冷启动恢复）：三条最小覆盖 + 两个边界。
//   切出 `let privRestoreInFlight … let stateWriteTail` 这段（含 privateIdentityCheck 与 ensurePrivateSession），
//   用假 ctx 喂真实的身份核验与恢复流程。
{
  const src = (() => {
    const a = body.indexOf('let privRestoreInFlight');
    const b = body.indexOf('let stateWriteTail');
    if (a < 0 || b < 0) throw Error('A114 slice missing');
    return body.slice(a, b);
  })();
  const PRIV = 'R:\\fixture-private';
  const normPath = (p) => String(p || '').replace(/[\\/]+$/, '').replace(/\//g, '\\').toLowerCase();
  const mk = (opts) => {
    const o = opts || {};
    const calls = { list: 0, resolve: 0, prompt: 0, selectModel: 0 };
    const S = { sessionId: o.sid === undefined ? 'session-aaaa' : o.sid };
    const store = new Map();
    const sc = {
      list: async () => { calls.list += 1; return { items: o.items || [] } },
      resolveAgent: async () => {
        calls.resolve += 1;
        if (o.resolveThrows) throw new Error('resume failed');
        if (o.resolveError) return { error: { code: 'session/not-found' } };
        if (o.liveAfter !== false) store.set(S.sessionId, { header: { id: S.sessionId, cwd: o.liveCwd || PRIV } });
        return { agent: {} };
      },
      prompt: async () => { calls.prompt += 1; return {} },
      selectModel: async () => { calls.selectModel += 1; return { selected: {} } },
    };
    const reg = o.arch === undefined ? { archivedSessionIds: [] } : (o.arch === null ? {} : { archivedSessionIds: o.arch });
    const ctx = {
      get: (n) => (n === 'sessionController' ? sc
        : n === 'sessions' ? { get: (id) => store.get(id) }
          : n === 'sandboxPolicy' ? { resolve: () => (o.pol === undefined ? { mode: 'workspace-write' } : o.pol) }
            : n === 'workspaceRegistry' ? reg
              : n === 'workspaceController' ? {}
                : n === 'fs' ? {} : undefined),
    };
    const fn = new Function('S', 'ctx', 'STATE_DIR', 'sessionMeta', 'FAKE_SIGNAL', 'race', 'privatePolicy',
      src + '; return { ensurePrivateSession, privateIdentityCheck };');
    const api = fn(S, ctx, PRIV,
      async () => ({ cwd: o.metaCwd === undefined ? PRIV : o.metaCwd }),
      {}, async (p) => p,
      () => (calls.resolve > 0 ? (o.polAfter === undefined ? { mode: 'workspace-write' } : o.polAfter) : null));
    return { api: api, calls: calls, S: S };
  };
  const goodItems = [{ sessionId: 'session-aaaa', cwd: PRIV }];

  // ① 冷启动：没有 live Session ⇒ 恢复一次，且恢复后拿到策略
  const a = mk({ items: goodItems });
  const ra = await a.api.ensurePrivateSession();
  record('H71_cold_start_restores_once_with_policy',
    { ok: true, restored: true, resolve: 1, prompt: 0, selectModel: 0 },
    { ok: !!(ra && ra.ok), restored: !!(ra && ra.restored), resolve: a.calls.resolve,
      prompt: a.calls.prompt, selectModel: a.calls.selectModel });

  // ② 身份不符（cwd 不是私人根）⇒ 绝不恢复
  const b = mk({ items: [{ sessionId: 'session-aaaa', cwd: 'X:\\ExampleWorkspace\\other' }] });
  const rb = await b.api.ensurePrivateSession();
  record('H72_wrong_identity_never_restores', { ok: false, resolve: 0 },
    { ok: !!(rb && rb.ok), resolve: b.calls.resolve });

  // ③ 归档表读不到（不是数组）⇒ 不恢复（旧版"读不到就放行"是洞）
  const c = mk({ items: goodItems, arch: null });
  const rc = await c.api.ensurePrivateSession();
  record('H73_unreadable_archive_blocks_restore', { ok: false, resolve: 0 },
    { ok: !!(rc && rc.ok), resolve: c.calls.resolve });

  // ④ 已归档 / 子 agent 会话 / 冲突的持久投影 ⇒ 都不恢复
  const d1 = mk({ items: goodItems, arch: ['session-aaaa'] });
  const d2 = mk({ items: [{ sessionId: 'session-aaaa', cwd: PRIV, origin: 'subagent' }] });
  const d3 = mk({ items: goodItems, metaCwd:'R:\\different' });
  record('H74_archived_subagent_or_conflicting_projection_blocks_restore',
    { archived: false, subagent: false, brokenProj: false },
    { archived: !!(await d1.api.ensurePrivateSession()).ok,
      subagent: !!(await d2.api.ensurePrivateSession()).ok,
      brokenProj: !!(await d3.api.ensurePrivateSession()).ok });

  // ⑤ 单飞：并发两次只恢复一次；空 sid 不消耗那一次机会
  const e = mk({ items: goodItems });
  const both = await Promise.all([e.api.ensurePrivateSession(), e.api.ensurePrivateSession()]);
  const f = mk({ sid: '', items: goodItems });
  const r1 = await f.api.ensurePrivateSession();
  f.S.sessionId = 'session-aaaa';
  const r2 = await f.api.ensurePrivateSession();
  record('H75_single_flight_and_unverified_sid_keeps_the_chance',
    { resolve: 1, bothOk:true, firstOk: false, secondResolve: 1 },
    { resolve: e.calls.resolve, bothOk:both.every(r=>r.ok), firstOk: !!(r1 && r1.ok), secondResolve: f.calls.resolve });
}

// A115（2026-11-26 复审缺口 3）：**先按现有策略写**，只有真的被沙箱拒绝、且没有 live 策略时，
//   才恢复一次并重试同一份快照。绝不能一拿不到策略就抛（那会打断"部署默认本来能写"的首次安装）。
{
  const src = (() => {
    const a = body.indexOf('let pol = privatePolicy();');
    const b = body.indexOf('lastSavedText = text;', a);
    if (a < 0 || b < 0) throw Error('A115 write slice missing');
    return body.slice(a, b);
  })();
  const run = async (opts) => {
    const o = opts || {};
    const writes = [];
    let restores = 0;
    const denied = () => {
      const e = new Error('cannot write "x": file access denied under workspace-write mode');
      e.code = 'FS_SANDBOX_DENIED';
      return e;
    };
    const fsSvc = {
      resolve: async (p) => ({ displayPath: p }),
      writeText: async (target, content, a, b, pol) => {
        const isBak = /\.bak$/.test(String(target && target.displayPath));
        if (!isBak) writes.push(pol === undefined ? null : pol);   // 只数主文件写入
        if (o.denyFirst && writes.length === 1) throw denied();
        if (o.denyAlways) throw denied();
        return undefined;
      },
    };
    const S = {};
    const privatePolicy = () => (o.livePolicy || null);
    const ensurePrivateSession = async () => {
      restores += 1;
      if (o.restoreOk) o.livePolicy = { mode: 'workspace-write' };
      return o.restoreOk ? { ok: true, restored: true } : { ok: false, why: 'identity unknown' };
    };
    const fn = new Function('S', 'privatePolicy', 'ensurePrivateSession', 'fsSvc', 'STATE_FILE', 'text', 'prev', 'Date',
      'return (async () => {' + src + '; return "ok"; })();');
    let err = '';
    try { await fn(S, privatePolicy, ensurePrivateSession, fsSvc, 'R:\\state.json', 'BODY', 'PREV', Date) }
    catch (e) { err = String(e && e.message) }
    return { writes: writes, restores: restores, err: err };
  };

  // ① 部署默认能写 ⇒ 一次写成，不恢复
  const a = await run({});
  // ② 被拒 + 恢复成功 ⇒ 第二次带策略重试同一份快照
  const b = await run({ denyFirst: true, restoreOk: true });
  // ③ 被拒 + 身份不可验 ⇒ 不重试，明确失败（保持停派发）
  const c = await run({ denyFirst: true, restoreOk: false });

  record('H76_default_policy_written_first_then_restore_on_denial',
    { plain: 1, plainRestore: 0, denied: 2, deniedRestore: 1, failedRestore: 1, failedErr: true },
    { plain: a.writes.length, plainRestore: a.restores,
      denied: b.writes.length, deniedRestore: b.restores,
      failedRestore: c.restores, failedErr: /未能恢复可用策略/.test(c.err) });
}

const failures = results.filter((r) => !r.pass)
console.log(JSON.stringify({ total: results.length, passed: results.length - failures.length, failures }, null, 2))
if (failures.length) process.exitCode = 1
