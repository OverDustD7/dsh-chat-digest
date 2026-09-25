// Isolated regression probes: evaluate current source with in-memory services only.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const dir=path.dirname(fileURLToPath(import.meta.url));
// 这个文件在 test/ 下（2026-09-25 从 docs/audit-2026-09-20/ 迁来）：它是**验收探针**，不是文档。
const body=fs.readFileSync(path.resolve(dir,'../lib/host-body.txt'),'utf8');
const results=[];
// 路由层通用化（A29）后，切出来的片段会引用这些**外部常量**，而探针作用域里没有它们。
// 按项目既有约定「定义在片段内」：给每个片段前置一段线路常量。
// 故意**不**声明 DEFAULT_ROUTE / PROBE_URL —— 那两个本来就是按参数注入的，重名会撞。
const ROUTE_SHIM = "const ROUTES=[{id:'thu',label:'THU·免费',ctxRatio:0.75},{id:'paratera',label:'paratera',ctxRatio:0.5}];"
  + "const R0='thu',R1='paratera';const routeIds=()=>ROUTES.map(r=>r.id);"
  + "const routeDef=(id)=>ROUTES.find(r=>String(r.id)===String(id))||ROUTES[0];const ctxRatioOf=()=>0.75;\n";
function chunk(a,b){const start=body.indexOf(a), end=body.indexOf(b,start+a.length);if(start<0||end<0)throw Error(a);return ROUTE_SHIM + body.slice(start,end);}
function record(id, expected, actual){results.push({id,expected,actual,pass:JSON.stringify(expected)===JSON.stringify(actual)});}
{
 const S={busy:true,busyFor:'test-session',busySawOpen:true,busyBase:0,autoRetry:true,retryCount:0};let prompts=0;
 const check=new Function('S','ctx','turnState','turnEnds','saveState','checkCtx','cstHM','noteError','FAKE_SIGNAL',chunk('const checkBusy = async () => {','// 自动：')+'return checkBusy;')(S,{get:()=>({prompt:async()=>prompts++})},async()=>({open:false,ends:1,lastReason:'error'}),async()=>1,async()=>{},async()=>{},()=>'',()=>{},{});
 await check();record('H01_error_auto_retry',1,prompts);
}
{
 const S={items:[{id:'demo'}]},fsSvc={resolve:async x=>x,readText:async()=>JSON.stringify({items:[]})};
 const load=new Function('S','fsSvc','STATE_FILE',chunk('const loadState = async () => {','const readArchived =')+'return loadState;')(S,fsSvc,'memory');
 await load();record('H02_empty_items_restore',[],S.items);
}
{
 const handlers={},S={items:[{id:'a',text:'old',done:true}]};
 new Function('route','routeOk','S','saveState',chunk("routeOk.items = route('POST', 'items'",'routeOk.item = route'))((method,name,fn)=>(handlers[name]=fn),{},S,async()=> 'save-fail');
 const response=await handlers['items-patch']({upsert:[{id:'a',text:'new'}]});
 record('H03_patch_persist_failure','save-fail',response.persist);
 record('H04_patch_preserve_done',true,S.items[0].done);
 const many=Array.from({length:301},(_,i)=>({id:'i'+i,text:'test'}));
 const r=await handlers.items({items:many});record('H05_301_items_preserved_or_rejected',true,r.ok===false||S.items.length===301);
}
{
 const S={busy:false,sessionId:'test',routePick:'paratera',lastCollectAt:1};let prompts=0;
 const fire=new Function('S','cstDay','turnEnds','roundPrompt','FAKE_SIGNAL','noteError','saveState',chunk('const fireRound = async (sc, reason, pick, mode, probeRes) => {','// ---- 上下文用量探测')+'return fireRound;')(S,()=> '2026-09-20',async()=>0,()=>'',{},()=>{},async()=>{});
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
// A19（2026-09-21 追加，用户报「启用了自动今天却没有自动」）：把自动 tick 抽出来单跑。
//   实测根因＝判据里有 `S.collectDay === day`，而 collectDay 是**游标**（"上次采到哪天"），
//   09-20 凌晨那一轮把它写成 2026-09-20 ⇒ 当晚 23:30 的 tick 认为"今天已采"直接跳过。
function autoTick(S, day, hm) {
  let fires = 0, captured = null;
  const timerSvc = { interval: (cb) => { captured = cb; return null; } };
  const fn = new Function('timerSvc', 'S', 'checkBusy', 'checkCtx', 'cstDay', 'cstHM', 'saveState', 'triggerRound', 'noteError',
    chunk('const offTick = timerSvc.interval(() => {', '}, 30000);') + '}, 30000); return offTick;');
  fn(timerSvc, S, async () => {}, async () => {}, () => day, () => hm, async () => {}, () => { fires += 1; return { ok: true }; }, () => {});
  captured();
  return fires;
}
{
 // 09-20 真实字段值：auto=true / autoTime=23:30 / collectDay=2026-09-20 / autoFiredDay=''
 //   旧代码在这里回 0 次（被 collectDay 拦掉），修好后必须触发 1 次。
 const S = { auto: true, autoTime: '23:30', busy: false, collectDay: '2026-09-20', autoFiredDay: '' };
 record('H09_auto_not_cancelled_by_manual_round', 1, autoTick(S, '2026-09-20', '23:30'));
 record('H10_auto_dedup_by_autoFiredDay', 0, autoTick({ auto: true, autoTime: '23:30', busy: false, collectDay: '2026-09-19', autoFiredDay: '2026-09-20' }, '2026-09-20', '23:31'));
 record('H11_auto_waits_until_autoTime', 0, autoTick({ auto: true, autoTime: '23:30', busy: false, collectDay: '2026-09-20', autoFiredDay: '' }, '2026-09-21', '00:50'));
}
{
 // A21（2026-09-22）：**未交付的轮要能自动补跑**。实测 2026-09-21 23:30 那轮请求过但没交付
 //   （提问没人回答 → turn 被 interrupted），`pendingCollect` 一直挂着却**没有任何东西把它接上**。
 //   `auto:false` 也要补 —— 它是"把已请求的那一轮做完"，不是"新起一轮"。
 const S = { auto: false, autoTime: '23:30', busy: false, autoFiredDay: '2026-09-21', resumeCount: 0,
             pendingCollect: { day: '2026-09-21', at: Date.now() - 11 * 60 * 1000 } };
 record('H12_undelivered_round_resumes', 1, autoTick(S, '2026-09-22', '10:30'));
 // 上限 3 次：已经补过 3 次就不再补（避免无限重试）
 record('H13_resume_capped_at_3', 0, autoTick({ auto: false, busy: false, resumeCount: 3, autoFiredDay: '2026-09-21',
             pendingCollect: { day: '2026-09-21', at: Date.now() - 11 * 60 * 1000 } }, '2026-09-22', '10:30'));
 // 刚触发不到 10 分钟 ⇒ 不补（否则会和正常那一轮打架）
 record('H14_resume_waits_10min', 0, autoTick({ auto: false, busy: false, resumeCount: 0, autoFiredDay: '2026-09-21',
             pendingCollect: { day: '2026-09-22', at: Date.now() - 60 * 1000 } }, '2026-09-22', '10:30'));
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
    readText: async (p) => { if (p in files) return files[p]; throw new Error('ENOENT') },
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
 // 损坏件 + 没有 .bak ⇒ 返回 'none'（**不抛**），"不存在"与"损坏"必须分得开
 const files = { memory: '{broken' };
 const saveCalls = [];
 const S = { items: [] };
 const h = loadStateWith(S, files, 'memory', 'C:\\old\\state.json', saveCalls);
 record('H19_corrupt_without_bak_returns_none', 'none', await h.load());
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
//   旧版把"可达/不通"那句话写死成 `'probe:THU 可达'`，探的却是 `probeRes.route`；
//   于是探 paratera 成功时 `/state` 会同时给出 `routePick=paratera` 与 `routeWhy="probe:THU 可达"`
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
         { namesProbed: gotWhy.indexOf('paratera') >= 0, namesThu: gotWhy.indexOf('THU') >= 0 });
}
fs.writeFileSync(path.join(dir,'host-behavior-results.json'),JSON.stringify(results,null,2));
console.log(JSON.stringify(results,null,2));
