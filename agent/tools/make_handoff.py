# -*- coding: utf-8 -*-
"""make_handoff.py — 生成自包含交接文档（运行态数值现读，不靠回忆）。

**2026-09-15 晚：本脚本已降级为「历史模板」，默认拒绝覆盖。**
原因：`HANDOFF-2026-09-15-CHATFEED.md` 后来是**手写维护**的（§1 一分钟看懂 / §2 运行态实测值 /
§7 待办 / §10 待用户动作 / §9bis 可粘贴提示词），而这里的 `DOC` 模板还停在 09-14 那一轮 ——
直接跑会用旧文案把更好的交接稿覆盖掉（且模板里还写死着过时的步数）。
所以：**目标文件比本脚本新时，默认拒绝写入**；确实要用请显式 `--force`，并先把模板里的
数字/章节更新到最新（步数一律用 `{steps}` 占位，别写死）。
"""
import io
import json
import os
import re
import sys
import datetime as dt

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # agent 根
CI = ROOT
CF = os.path.join(ROOT, "chat-feed")
TZ = dt.timezone(dt.timedelta(hours=8))
FORCE = "--force" in sys.argv
OUT = os.path.join(ROOT, "HANDOFF-2026-09-15-CHATFEED.md")

# --- 护栏：**默认拒绝覆盖**（不要用"目标比脚本旧"这类启发式）---
# 2026-09-15 实测事故：第一版护栏比较 mtime，而我刚编辑过本脚本 → 判定"目标更旧" → 直接写入，
# 把 271 行手写交接稿覆盖成 6KB 旧模板（靠上下文里读过的原文才恢复）。
# 教训：破坏性写入一律"默认拒绝 + 必须显式 --force"，并在覆盖前备份。
if os.path.exists(OUT) and not FORCE:
    print("拒绝覆盖：%s 已存在，且它是**手写维护**的（比本模板新得多）。" % OUT)
    print("  · 想生成新交接稿：先把本文件 DOC 模板更新到最新，再跑 `--force`")
    print("  · 或者直接改那个 md（当前推荐做法）")
    raise SystemExit(2)
if os.path.exists(OUT) and FORCE:
    bak = OUT + ".before-make_handoff.bak"
    io.open(bak, "w", encoding="utf-8", newline="\n").write(io.open(OUT, encoding="utf-8").read())
    print("已备份原文件 -> %s" % bak)

F = {}
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("cf_api", os.path.join(CI, "docs", "agent", "cf_api.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    st, b = m.call("GET", "/chat-feed/api/state")
    j = json.loads(b)
    its = j.get("items") or []
    F["http"] = st
    F["items"] = len(its)
    F["done"] = sum(1 for i in its if i.get("done"))
    F["isNew"] = sum(1 for i in its if i.get("isNew"))
    F["busy"] = j.get("busy")
    F["sessionId"] = j.get("sessionId")
    F["collectDay"] = j.get("collectDay")
    F["auto"] = "%s/%s" % (j.get("auto"), j.get("autoTime"))
    F["wakeLen"] = len(j.get("wakeText") or "")
    F["kinds"] = {k: sum(1 for i in its if i.get("kind") == k) for k in sorted({i.get("kind") for i in its})}
    st2, p = m.call("GET", "/chat-feed/api/panel")
    pj = json.loads(p)
    F["panel"] = "%s sections=%s fallback=%s err=%r" % (pj.get("source"), len(pj.get("sections") or []), pj.get("fallback"), pj.get("err"))
except Exception as e:
    F["err"] = str(e)[:120]

dp = os.path.join(CI, "scripts", "daily_prep.py")
t = io.open(dp, encoding="utf-8").read()
F["steps"] = len(re.findall(r'run\("', t))
F["stepNames"] = re.findall(r'run\("([^"]+)"', t)
prods = []
for n in ("jsonl", "brief.md", "timeline.md", "articles.md", "threads.md", "units.md", "units_filtered.md",
          "vision.md", "slices.md", "images.json"):
    p = os.path.join(CI, "output", "days", "2026-09-14_" + n) if n != "jsonl" else os.path.join(CI, "output", "days", "2026-09-14.jsonl")
    prods.append("%s:%s" % (n, ("%.0fKB" % (os.path.getsize(p) / 1024)) if os.path.exists(p) else "缺"))
F["prods"] = " ".join(prods)
def mt(p):
    return dt.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m-%d %H:%M") if os.path.exists(p) else "缺"
F["debug914"] = mt(os.path.join(CI, "docs", "debug_2026-09-14.md"))
F["itemsJson"] = "存在" if os.path.exists(os.path.join(CI, "output", "daily", "2026-09-14", "items.json")) else "**缺**"
F["now"] = dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")

DOC = """# 交接：chat-feed / 聊天情报（{now} CST）

> 本文自包含：新会话只读这一份 + 按 §9 的提示词开口即可接手。
> 相关权威文档： `agent\\docs\\MAIN_AGENT_SPEC.md`（主 agent 规格）·
> `agent\\docs\\agent\\WORKING.md`（主 agent 手册）· 扩展规格）。

## 1. 现在是什么状态（一句话）

chat-feed 已从动态插件**迁到常驻 profile bundle**（重启自带，不再需要重建）；每日管线 **{steps} 步**在跑；
面板扩展已改成**数据驱动 + 零重启热更新 + 接口自证**（主 agent 加节只写数据）。
本轮（09-14）修完 3 个 UI bug + 3 个面板 API bug，并把「水群降噪」（3g/3i）与「本地视觉读图分诊」（3j）接进管线。

## 2. 运行态实测值（现在读的）

| 项 | 值 |
|---|---|
| `/chat-feed/api/state` | **HTTP {http}**（插件活着） |
| 面板条目 | **{items} 条**（已勾选 {done} / 【新】{isNew}）｜ kind 分布 {kinds} |
| busy / collectDay | **{busy}** / {collectDay} |
| 主 agent 会话 | `{sessionId}` |
| 自动采集 | {auto}（关/23:30） |
| wakeText | {wakeLen} 字符 |
| `/api/panel` | {panel} |
| daily_prep | **{steps} 步**：{stepNames} |
| 09-14 产物 | {prods} |
| debug_2026-09-14.md | {debug914} ｜ output\\daily\\2026-09-14\\items.json：{itemsJson} |

**判活命令（别再用 cfhttp.ps1，它依赖已消失的动态调试加载器）**：
```
cd <个人目录>
.\\..\\venv\\Scripts\\python.exe docs\\agent\\cf_api.py state
```
旁证：裸请求 `http://127.0.0.1:3080/chat-feed/api/state` 返回 **401**＝路由在；**404**＝没有这个路由。

## 3. 数据流（触发 → 交付）

```
用户点面板「获取」/ 到点自动(23:30)
  → Host POST /chat-feed/api/collect → 注入「当日一轮」指令（roundPrompt：17 步文本 + 分片全覆盖 + 水群口径 + 上次采集窗口）
  → 主 agent 自己跑 scripts\\daily_prep.py <date>（19 步：解密/取数/三视图/3g 单元化/3h 官网文章/3i 本地筛/3j 读图分诊/3k 收藏…）
  → 派子代理提炼（读 _timeline/_articles/_threads/_units_filtered/_vision）
  → 回写面板 /chat-feed/api/items（整表）+ 刷新镜像 docs\\信息列表.md
  → 呈给用户（present）；busy 由轮询 turn/end 计数收尾
```

## 4. 文件地图（改代码找这些）

| 角色 | 路径 |
|---|---|
| Host 权威源码（函数体） | `chat-feed\\tools\\host-v34.body.txt`（**改它=要重启**；自检 `tools\\check_host_body.py` 必须 FAILS: 0） |
| 常驻入口 | `chat-feed\\lib\\plugin.js`（读上面那份函数体并 apply） |
| 前端 | `chat-feed\\lib\\ui.js`（侧栏入口/面板外壳）· `chat-feed\\lib\\right.js`（右栏列表/条目/菜单/引用框） |
| 面板结构数据 | `chat-feed\\panel.json`（种子）→ 活数据在 `%TEMP%\\chat-feed\\panel.json` |
| 插件文档 | `chat-feed\\STATUS.md` · `RESTART.md`（§0d 静态化五要素）· `docs\\PANEL_EXTENSION.md` |
| 管线 | `agent\\pipeline\daily_prep.py` + `pipeline\*.py|mjs` + `agent\tools\*.py` |
| 主 agent 手册 | `agent\\docs\\agent\\WORKING.md` · `docs\\MAIN_AGENT_SPEC.md` |
| 规范单一事实来源 | `docs\\guidelines.md`（原则）· `docs\\output_format.md`（产出与硬性纪律）· `docs\\EVOLUTION.md`（演进+规程） |

## 5. 本轮新增/变更的规范（三条）

1. **`guidelines.md` 原则 24**：自进化**只产出"你能验证"的改进项**；UI/浏览器/宿主插件类**不许进面板**，
   只能写进证据层当"给调试侧的线索"（格式：现象/期望/我为什么做不了/调试侧用什么工具确认）。
2. **`output_format.md` 硬性纪律 11**：行动项的**可验证性门槛** —— 判据一句话「这条我能自己验证吗？」
3. **面板结构数据驱动**（`PANEL_EXTENSION.md`）：加节/改名**只改 `panel.json` 或 POST `/api/panel/set`**，
   `GET /api/panel` 自证（`sections/count/unknownKinds/err`），**不碰 JS、不重启、不看 UI**。

## 6. 本轮（09-14）实测数字

- **管线**：19 步（新增 3g 单元化 / 3h 官网·公众号新文章 / 3i 本地小模型过筛 / 3j 图片分诊 / 3k 收藏刷新）
- **水群降噪**：3g 清垃圾让大群 146,800→49,990 字符（-66%）；3i 本地 qwen3.5:9b 逐条筛再 -70%（丢 73%、漏率约 5%、白名单兜底救 7 条、fail-open 0、2.9 秒/200 条）
- **本地视觉**：09-13 全量 75 张 → 需回看 38 ｜ **判无信息 37（49% 不进强模型）** ｜ 失败 0 ｜ 69 秒（PIL 归一化治掉 11 张 HTTP 400）
- **面板 API**：读盘 `source=panel.json(NB)` ✓ ｜ 坏数据被拒 ✓ ｜ 加节立刻生效（热更新）✓
- **右栏 3 个 UI 修复**：点条目丢滚动位置 / 来源灰字挤窄正文 / ⋯ 菜单定位（我改坏两次才对，见 DEV_NOTES）

## 7. 待办（★＝需要用户动作）

```
★1 让主 agent 补做三件（我上一条已问、还没做）：
     ① 那条选课消息只报了一半 —— 缺 `30880023 数据分析引论`、`20050031 新生导引`、
        以及「收藏里的教学云盘 → 新培养方案/教学计划」这条链（工具已备：node scripts\\fetch_page.mjs <云盘链接> 免登录能列目录）
     ② `ai-dasai-final` 未按用户"其他所有删了"删除（实测仍在）
     ③ 交付文件 output\\daily\\2026-09-14\\items.json 不存在（按规范该在）
 2 面板扩展 spec 第 4 条未做：`/items` 未知字段透传（仍是白名单；body 改动，下次重启带上）
 3 host body 里还写着"17 步"（现 19 步）—— 文案陈旧，改它要一次重启
 4 UI 数值验证欠一次（内置浏览器被遮挡时渲染冻结、取不到数；可用 ShowWindow(hwnd,4) 显示但不激活，量完即收）
★5 09-04~09-11 断档是否补做，仍待用户定
```

## 8. 坑点（本轮踩的，别再踩）

```
· 动态 Cordis 插件在 approval prompts disabled 下 fs/webServer 被**静默拒绝** → 必须静态化（五要素见 RESTART.md §0d）
· profile bundle 缺 `package.json` 的 `dsh.bundle.patch` → **dsh web 直接启动失败**；且别混用"手改 package.json"与 `dsh plugin add`（会抹掉 bundles）
· 改 `host-v34.body.txt` 必须过 `check_host_body.py`（它三次拦下我的语法错）；**改完必须重启**（静态入口只在加载时读一次）
· `DIR` 是 `…\\chat-feed\\lib\\`（结尾带反斜杠），**不是** %TEMP%；Host 的 fs **写不进项目树**（台账 #31）→ 活数据放 %TEMP%
· **`fsSvc.stat` 不存在**（只有 readText/writeText/resolve）→ 用它必然落 fallback；新接口一律**回显 err**
· 同一路径注册 GET 与 POST 会撞（405/401）→ 换路径 `/api/panel/set`
· 整表 `innerHTML=''` 重建会**丢滚动位置** → 渲染前后自己保存/恢复
· `position:fixed` 会被**最近的 transform 祖先**当包含块（面板里有）→ 菜单锚在按钮本体，别算坐标
· 内置浏览器窗口被遮挡时**渲染时间线不推进** → UI 改动拿不到数值验证（别假装量过）
· Python 里中文引号**不能套在双引号字符串内**（我今天踩了 5 次；`py_compile` 每次都拦下，所以没带病上线）
```

## 9. 可粘贴开场提示词（给下一会话）

```
接手 chat-feed / 聊天情报（D:\\Project\\DSH）。先读，按此顺序：
1) D:\\Project\\DSH\\HANDOFF-2026-09-15-CHATFEED.md（本文，自包含：现状/运行态/文件地图/待办/坑）
2) D:\\Project\\DSH\\chat-feed\\RESTART.md §0d（静态插件的五要素与判活，**别再用 cfhttp.ps1**）
3) <个人目录>\\docs\\agent\\WORKING.md（主 agent 手册）
4) D:\\Project\\DSH\\chat-feed\\docs\\PANEL_EXTENSION.md（面板扩展：数据驱动/热更新/接口自证）

判活（第一件事，确认插件活着）：
  cd <个人目录>
  .\\..\\venv\\Scripts\\python.exe docs\\agent\\cf_api.py state
  期望 HTTP 200 且带 items/wakeText；再 GET /chat-feed/api/panel 看 sections 与 err

当前未生效/未验证项（别当成已完成）：
  · `/items` 未知字段透传未做；body 里仍写"17 步"（现 19 步）—— 这两条都要一次 `dsh web` 重启才带上
  · UI 三处修复（滚动位置/来源布局/⋯菜单）**没有数值验证过**（内置浏览器被遮挡时渲染冻结）；
    要验证先问用户能否用 ShowWindow(hwnd,4) 显示但不激活，或让他 F5 后描述现象
  · 上一轮「获取」（09-14）只报了一半：缺 30880023/20050031 两门课与「教学云盘→培养方案」链；
    ai-dasai-final 未按用户"其他所有删了"删除；output\\daily\\2026-09-14\\items.json 不存在

硬纪律：主 agent 禁用 browser_*/web_fetch/read_page（能跑本机脚本）；调试侧可用浏览器/抓取但只用于验证与修工具；
经验双写（docs + mnemon_remember）；不自行删除文件；改 host body 必须过 tools\\check_host_body.py 且改完要重启；
改 lib/*.js 只需 F5。先读文档再动手，别急着下结论（我今天因为"看个计数就下结论"被纠正过）。
```
"""

out = OUT
io.open(out, "w", encoding="utf-8", newline="\n").write(DOC.format(**F))
print("写: %s（%d 字符）" % (out, len(DOC.format(**F))))
print("facts:", json.dumps({k: v for k, v in F.items() if k != "stepNames"}, ensure_ascii=False))
