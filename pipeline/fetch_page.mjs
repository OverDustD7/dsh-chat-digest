// fetch_page.mjs — 通用网页抓取（本机 Node 直连，零插件依赖）。
//
// 为什么需要它（用户 2026-09-14："那你得先把抓网页的工具也写出来吧"）：
//   文档里一直引用 `scripts\fetch_page.mjs`（"官网抓取"），但它**根本不存在**；
//   而主 agent 禁用宿主 web 工具（browser_*/web_fetch/read_page）、**能跑本机脚本**，
//   所以"抓到链接里的内容"必须由本机脚本承担。`fetch_article.mjs` 只管微信公众号正文，不通用于网盘/官网。
//
// 关键纪律：**取不到就说取不到，绝不编造内容**。工具会把"为什么取不到"分类写进产出：
//   ok / http-<code> / needs-login（跳登录或登录表单）/ js-only（正文靠 JS 渲染）/ blocked（反爬/验证页）
//
// 用法:  node scripts\fetch_page.mjs <url> [out.md] [--raw]
//   --raw  额外把原始 HTML 落到同目录 <out>.html（便于排障）
// 产出:  默认 output\window\pages\<host>_<slug>.md
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { cfg } from "./pconf.mjs";

const HERE = path.dirname(path.dirname(fileURLToPath(import.meta.url)));   // …\工作区
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

const argv = process.argv.slice(2);
const RAW = argv.includes("--raw");
const pos = argv.filter((a) => !a.startsWith("--"));
const url = pos[0];
if (!url) {
  console.error("usage: node fetch_page.mjs <url> [out.md] [--raw]");
  process.exit(2);
}

// —— Seafile 分享链接（<你的网盘域名>/d/<token>…；域名是部署方的私人配置）——
// 实测（2026-09-14）：该站的分享页 HTML 是 **JS 壳**（正文只有 6 个字符），文件列表**不在 HTML 里**；
// 但它的免登录 API `GET /api/v2.1/share-links/<token>/dirents/?path=…` **返回 200 + JSON 文件清单** ✓
// （同一个 token 的 `/info` 端点返回 403 —— 所以只走 dirents，不要因为 info 403 就判"整条链不可用"）
const SEAFILE_HOST = cfg("seafile_host", "");   // 放 <localDir>/pipeline.json；空则不做 Seafile 处理
const seafile = SEAFILE_HOST
  ? url.match(new RegExp(`^https?://${SEAFILE_HOST.replace(/\./g, "\\.")}/d/([0-9a-f]+)`, "i"))
  : null;
if (seafile) {
  const tok = seafile[1];
  const root = decodeURIComponent(new URL(url).pathname.replace(/^\/d\/[0-9a-f]+\/?/i, "/")) || "/";
  const rows = [];
  const walk = async (p, depth) => {
    const api = `https://${SEAFILE_HOST}/api/v2.1/share-links/${tok}/dirents/?path=${encodeURIComponent(p)}`;
    try {
      const r = await fetch(api, { headers: { "User-Agent": UA, Accept: "application/json" } });
      if (!r.ok) { rows.push(`${"  ".repeat(depth)}- [ERR ${r.status}] ${p}`); return; }
      const j = await r.json();
      for (const d of (j.dirent_list || [])) {
        const nm = d.folder_name || d.file_name || "?";
        rows.push(`${"  ".repeat(depth)}- ${d.is_dir ? "[目录]" : "[文件]"} ${nm}　(${d.size} B, ${d.last_modified || ""})`);
        if (d.is_dir && depth < 2) await walk((p.endsWith("/") ? p : p + "/") + nm, depth + 1);
      }
    } catch (e) { rows.push(`${"  ".repeat(depth)}- [ERR ${e.message}] ${p}`); }
  };
  await walk(root, 0);
  const o = pos[1] || path.join(HERE, "output", "window", "pages", `cloud_${tok}.md`);
  fs.mkdirSync(path.dirname(o), { recursive: true });
  fs.writeFileSync(o, [`# 云盘分享清单（Seafile API，免登录）`, "", `- 分享链接：${url}`, `- token：${tok} ｜ 起点路径：${root} ｜ 条目 ${rows.length}`, "",
    "> 取文件本体用：`GET /api/v2.1/share-links/<token>/files/?p=<path>` 拿下载直链。",
    "> 若这里没出现目标文件：换 `path=` 起点或加大递归层数（本工具默认 3 层）。", "", ...rows, ""].join("\n"), "utf8");
  console.log("seafile token=%s entries=%d -> %s", tok, rows.length, o);
  process.exit(0);
}

function decode(s) {
  return String(s)
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, d) => String.fromCharCode(Number(d)));
}
function textOf(html) {
  return decode(String(html)
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<noscript[\s\S]*?<\/noscript>/gi, " ")
    .replace(/<\/(p|div|li|tr|h[1-6]|section|article)>/gi, "\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<[^>]+>/g, " "))
    .split("\n").map((x) => x.replace(/[ \t\u00a0]+/g, " ").trim())
    .filter((x) => x.length > 0)
    .join("\n");
}
function classify(html, title, text, status) {
  if (status !== 200) return "http-" + status;
  const h = String(html);
  if (/Environment\s*abnormal|环境异常|wappoc_appmsgcaptcha|cf-challenge|Just a moment/i.test(h)) return "blocked";
  if (/(name="?password"?|登录|登陆|sign\s*in|log\s*in)/i.test(h) && /(form|input)/i.test(h) && text.length < 3000) return "needs-login";
  if (text.length < 400 && /<div id="(app|root)"|window\.__|data-reactroot/i.test(h)) return "js-only";
  return "ok";
}

const res = await fetch(url, {
  headers: { "User-Agent": UA, Accept: "text/html,application/xhtml+xml,*/*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9" },
  redirect: "follow",
});
const html = await res.text();
const finalUrl = res.url || url;
const m = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
const title = m ? decode(m[1]).replace(/\s+/g, " ").trim() : "";
const text = textOf(html);
const kind = classify(html, title, text, res.status);

const host = new URL(url).host.replace(/^www\./, "");
const slug = (title || new URL(url).pathname).replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 40) || "page";
let out = pos[1];
if (!out) {
  const dir = path.join(HERE, "output", "window", "pages");
  fs.mkdirSync(dir, { recursive: true });
  out = path.join(dir, `${host}_${slug}.md`);
}
const lines = [
  `# 抓取结果：${title || "(无标题)"}`,
  "",
  `- **URL**：${url}`,
  finalUrl !== url ? `- **最终 URL**：${finalUrl}（发生了跳转）` : null,
  `- **HTTP**：${res.status} ${res.statusText || ""}`,
  `- **Content-Type**：${res.headers.get("content-type") || "?"}`,
  `- **HTML 长度**：${html.length} ｜ 提取正文：${text.length} 字符`,
  `- **判定**：**${kind}**`,
  "",
  kind === "ok" ? "## 正文" : `## 正文（判定为 ${kind}：以下内容可能不含真实数据，**不要据此下结论**）`,
  "",
  text.slice(0, 20000) || "(无可提取文本)",
  "",
].filter((x) => x !== null);
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, lines.join("\n"), "utf8");
if (RAW) fs.writeFileSync(out.replace(/\.md$/, "") + ".html", html, "utf8");
console.log("status=%s kind=%s html=%d text=%d -> %s", res.status, kind, html.length, text.length, out);
