// day_web_articles.mjs — 每天查「官网 / 公众号」的当日新文章（本机 Node 直连，零插件）
//
// 为什么需要它（2026-09-13 用户指出我漏了这一步）：
//   ① 主 agent **禁用宿主 web 工具**（browser_* / web_fetch / read_page）——但**能跑本机脚本**；
//   ② `wx_biz.py` 只读本地微信库 → 只覆盖"你关注的号"，没关注但该看的号（你配置的信息源…）漏在外面；
//   ③ 信息源官网的「通知公告 / 活动预告」才是对他**最有行动价值**的源，之前根本没纳入。
//   所以这一步应该由**主 agent 每天自己跑**（接进 daily_prep 即可），不需要 coder 侧代劳。
//
// 用法:  node scripts\day_web_articles.mjs [YYYY-MM-DD] [--body] [--days 14]
//   --body   顺带把"当日"的微信文章正文抓进 output\window\articles\（调 fetch_article.mjs）
//   --days   自证区间的天数（默认 14）
// 产出:  output\window\web_articles_<date>.md
//        —— 当日条目 + **近 N 天每日条数**（沿用既有纪律："0 篇"必须有据，不能只说"没抓到"）
import { cfgList } from "./pconf.mjs";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(path.dirname(fileURLToPath(import.meta.url)));   // …\工作区
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

// ⚠ 2026-09-13 修正：信息源官网必须带 **www.**（文档里少了它 → 一直 DNS 解析失败，这就是"源失效"的根因）
const SOURCES = [
  // 信息源是**部署方的私人配置**：放 <localDir>/pipeline.json 的 web_sources（[{name,url,prio}]）
  ...cfgList("web_sources"),
];

const dateArg = process.argv.slice(2).find((a) => /^\d{4}-\d{2}-\d{2}$/.test(a));   // 只认完整日期，
// 否则 `--days 14` 里的 "14" 会被当成日期（实测踩过：TODAY=14、筛出 0 条）
const WITH_BODY = process.argv.includes("--body");
const daysArg = process.argv.indexOf("--days");
const DAYS = daysArg >= 0 ? Number(process.argv[daysArg + 1]) || 14 : 14;
const cst = (ms) => new Date((ms === undefined ? Date.now() : ms) + 8 * 3600 * 1000);
const TODAY = dateArg || cst().toISOString().slice(0, 10);

const p2 = (s) => String(Number(s)).padStart(2, "0");
function strip(html) {
  return String(html)
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}
// 站点上的日期写法有两种实测形态：`2026-08-18` 与 `18_/ 2026-08`（日/年-月）
function findDate(s) {
  let m = s.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m) return `${m[1]}-${p2(m[2])}-${p2(m[3])}`;
  m = s.match(/(\d{1,2})\s*[_\s]*\/\s*(\d{4})-(\d{1,2})/);
  if (m) return `${m[2]}-${p2(m[3])}-${p2(m[1])}`;
  m = s.match(/(\d{1,2})\s*月\s*(\d{1,2})\s*日/);
  if (m) return `${TODAY.slice(0, 4)}-${p2(m[1])}-${p2(m[2])}`;
  return "";
}

function extract(html, base) {
  const out = [];
  const seen = new Set();
  const push = (href0, inner, ctx) => {
    let href = href0;
    if (/^(javascript:|#|mailto:)/i.test(href)) return;
    if (/\.(jpg|jpeg|png|gif|css|js)$/i.test(href)) return;
    if (/^\.\.\//.test(href) || href.startsWith("/")) href = new URL(href, base).href;
    const text = strip(inner).replace(/\s+/g, " ").trim();
    if (text.length < 6 || text.length > 400) return;
    const date = findDate(ctx);
    // 解析不出日期：**只要是微信文章链接就留着**（进"未标日期"兜底段，不静默丢）；导航/页脚才丢
    if (!date && !/mp\.weixin\.qq\.com/.test(href)) return;
    const key = date + "|" + text.slice(0, 40);
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ date, text, href });
  };
  // **优先按 <li> 逐条解析**：标题与日期通常同在一个 li 里 → 比"锚点±窗口"可靠得多
  // （2026-09-14 实测：书院「综合新闻」栏用 ±窗口 解析是 0 条，就是日期离锚点太远的缘故）
  for (const li of html.split(/<li\b/i).slice(1)) {
    const seg = li.slice(0, 4000);
    const a = seg.match(/<a\b[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/i);
    if (a) push(a[1], a[2], strip(seg));
  }
  if (out.length < 3) {                       // 没有 li 结构 → 退回锚点±窗口
    out.length = 0;
    seen.clear();
    const re = /<a\b[^>]*href="([^"]+)"[^>]*>([\s\S]{0,700}?)<\/a>/gi;
    let m;
    while ((m = re.exec(html))) push(m[1], m[2], strip(html.slice(Math.max(0, m.index - 400), m.index + 2500)));
  }
  return out;
}

const results = [];
for (const s of SOURCES) {
  try {
    const res = await fetch(s.url, {
      headers: { "User-Agent": UA, Accept: "text/html,*/*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9" },
      redirect: "follow",
      signal: AbortSignal.timeout(25000),
    });
    const html = await res.text();
    const items = extract(html, s.url);
    results.push({ ...s, status: res.status, len: html.length, items });
    console.log("[%s] status=%s html=%d items=%d today=%d", s.name, res.status, html.length,
      items.length, items.filter((i) => i.date === TODAY).length);
  } catch (e) {
    results.push({ ...s, status: 0, len: 0, items: [], err: String(e && e.message || e) });
    console.log("[%s] ERR %s", s.name, String(e && e.message || e));
  }
}

// 近 N 天计数（自证"0 篇"用）
const byDay = new Map();
for (const r of results) for (const it of r.items) if (it.date) byDay.set(it.date, (byDay.get(it.date) || 0) + 1);
const todayItems = results.flatMap((r) => r.items.filter((i) => i.date === TODAY).map((i) => ({ ...i, src: r.name, prio: r.prio })))
  .sort((a, b) => a.prio - b.prio);

if (WITH_BODY) {
  const dir = path.join(HERE, "output", "window", "articles");
  fs.mkdirSync(dir, { recursive: true });
  for (const it of todayItems) {
    if (!/mp\.weixin\.qq\.com/.test(it.href)) continue;
    const name = "web_" + it.date + "_" + it.text.replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 40) + ".md";
    try {
      execFileSync(process.execPath, [path.join(HERE, "scripts", "fetch_article.mjs"), it.href, path.join(dir, name)],
        { stdio: "ignore", timeout: 60000 });
      it.body = fs.existsSync(path.join(dir, name)) ? name : "";
    } catch (e) { it.body = ""; }
  }
}

const L = [];
L.push(`# ${TODAY} 官网/公众号新文章（本机直连抓取，非云端）`);
L.push("");
L.push(`> 抓取源：${SOURCES.map((s) => s.name).join(" · ")}`);
L.push(`> 产出脚本：\`node scripts\\day_web_articles.mjs ${TODAY}\`　（主 agent 每天跑管线时自动带出）`);
L.push("");
L.push(`## 一、当日（${TODAY}）：**${todayItems.length} 篇**`);
L.push("");
if (todayItems.length === 0) {
  L.push(`当天没有新条目 —— **依据**见下面「近 ${DAYS} 天每日条数」（不是抓取失败：失败会写 ERR/status）。`);
} else {
  for (const it of todayItems) {
    L.push(`- **${it.text}**　｜ ${it.src} ｜ <${it.href}>${it.body ? ` ｜ 正文：\`output\\window\\articles\\${it.body}\`` : ""}`);
  }
}
L.push("");
L.push(`## 二、近 ${DAYS} 天每日条数（"0 篇"的自证依据）`);
L.push("");
L.push("| 日期 | 条数 |");
L.push("|---|---|");
const days = [...byDay.keys()].sort().reverse().slice(0, DAYS);
for (const d of days) L.push(`| ${d} | ${byDay.get(d)} |`);
L.push("");
L.push("## 三、各源状态");
L.push("");
L.push("| 源 | HTTP | HTML | 解析条目 | 备注 |");
L.push("|---|---|---|---|---|");
for (const r of results) L.push(`| ${r.name} | ${r.status} | ${r.len} | ${r.items.length} | ${r.err ? "ERR: " + r.err : ""} |`);
L.push("");
const undated = results.flatMap((r) => r.items.filter((i) => !i.date).map((i) => ({ ...i, src: r.name }))).slice(0, 30);
L.push(`## 四、未标注日期的文章链接（${undated.length} 条，兜底段）`);
L.push("");
L.push("> 这些是页面上的微信文章链接，但脚本没从页面里解析出日期（不同栏目的日期标记形态不一致）。");
L.push("> **不静默丢**：人工/主 agent 扫一眼，判断是否与今天有关。");
L.push("");
for (const it of undated) L.push(`- ${it.text.slice(0, 90)}　｜ ${it.src} ｜ <${it.href}>`);

const out = path.join(HERE, "output", "window", `web_articles_${TODAY}.md`);
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, L.join("\n") + "\n", "utf8");
console.log("TODAY=%s items=%d -> %s", TODAY, todayItems.length, out);
