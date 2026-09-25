// fetch_article.mjs — 本机直连抓取微信公众号文章正文（零插件依赖，可后台批量）
// usage: node fetch_article.mjs <url> [out.md]
import fs from "node:fs";
import path from "node:path";

const url = process.argv[2];
const out = process.argv[3];
if (!url) {
  console.error("usage: node fetch_article.mjs <url> [out.md]");
  process.exit(2);
}

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

const res = await fetch(url, {
  headers: {
    "User-Agent": UA,
    Referer: "https://mp.weixin.qq.com/",
    Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
  },
  redirect: "follow",
});
const html = await res.text();
console.log("[fetch] status=%s len=%s", res.status, html.length);

if (/wappoc_appmsgcaptcha|环境异常/.test(html) || html.length < 5000) {
  console.error("[fetch] BLOCKED: verify/captcha page (len=%s)", html.length);
  process.exit(3);
}

function decode(s) {
  return String(s)
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(parseInt(d, 10)));
}
const strip = (s) => decode(String(s).replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();
const pick = (re) => {
  const m = html.match(re);
  return m ? strip(m[1]) : "";
};
const varOf = (name) => {
  const m = html.match(new RegExp("var\\s+" + name + "\\s*=\\s*[\"']([^\"']*)[\"']"));
  return m ? m[1] : "";
};

// ---- metadata (multiple fallbacks) ----
let title =
  pick(/<h1[^>]*id="activity-name"[^>]*>([\s\S]*?)<\/h1>/i) ||
  pick(/<h1[^>]*class="rich_media_title[^"]*"[^>]*>([\s\S]*?)<\/h1>/i) ||
  decode(varOf("msg_title")) ||
  (html.match(/property="og:title"\s+content="([^"]*)"/i) || [])[1] ||
  "";
title = strip(title);

let author =
  pick(/id="js_name"[^>]*>([\s\S]*?)<\/a>/i) ||
  decode(varOf("nickname")) ||
  strip((html.match(/property="og:article:author"\s+content="([^"]*)"/i) || [])[1] || "");

let dateStr = pick(/id="publish_time"[^>]*>([\s\S]*?)<\/em>/i);
if (!dateStr) {
  const ct = varOf("ct") || varOf("create_time");
  if (/^\d{9,11}$/.test(ct)) {
    const d = new Date(parseInt(ct, 10) * 1000);
    const p = (n) => String(n).padStart(2, "0");
    dateStr = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())} (UTC+8)`;
  }
}

// ---- body ----
const clean = html
  .replace(/<script[\s\S]*?<\/script>/gi, "")
  .replace(/<style[\s\S]*?<\/style>/gi, "")
  .replace(/<!--[\s\S]*?-->/g, "");

let body = "";
const m = clean.match(/<div[^>]*id="js_content"[^>]*>/i);
if (m) {
  const start = m.index + m[0].length;
  let seg = clean.slice(start, start + 300000);
  const endIdx = seg.search(/id="js_tags"|class="rich_media_tool"|class="rich_media_area_extra"|预览时标签不可点/i);
  if (endIdx > 0) seg = seg.slice(0, endIdx);
  body = seg
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|section|li|h\d|blockquote|tr)>/gi, "\n")
    .replace(/<img[^>]*>/gi, "\n[图片]\n")
    .replace(/<[^>]+>/g, "");
}
body = decode(body)
  .replace(/[ \t\u00a0]+/g, " ")
  .replace(/\n[ \t]+/g, "\n")
  .replace(/\n{3,}/g, "\n\n")
  .trim();

const text = `# ${title || "(无标题)"}\n\n- 公众号：${author}\n- 发布：${dateStr}\n- 来源：${res.url}\n\n${body}\n`;

if (out) {
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, text, "utf8");
  console.log("[fetch] wrote %s chars=%s title=%s date=%s", out, text.length, title, dateStr);
} else {
  console.log(text.slice(0, 4000));
}
