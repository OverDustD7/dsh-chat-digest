// probe-info-srt.mjs —— 用已保存的 SSO 会话（~/.thu-lib-space/storage-state.json）试取 info 详情页。
// 只打印状态码与命中关键词，绝不打印 cookie 值。
// usage: node <个人目录>\tools\probe-info-srt.mjs <url>
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const url = process.argv[2] || ""   // 站内链接是某个人的：必须由命令行给，不写死在代码里
const stPath = path.join(os.homedir(), ".thu-lib-space", "storage-state.json");
if (!fs.existsSync(stPath)) {
  console.log("[probe] no storage-state.json");
  process.exit(2);
}
const st = JSON.parse(fs.readFileSync(stPath, "utf8"));
const cookies = (st.cookies || []).filter((c) => /tsinghua\.edu\.cn$/.test((c.domain || "").replace(/^\./, "")));
const names = cookies.map((c) => c.domain + ":" + c.name);
console.log("[probe] cookies(域名:名，不含值):", names.join(", ") || "(无 tsinghua 域 cookie)");
const header = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";
const res = await fetch(url, { headers: { "User-Agent": UA, Cookie: header, Accept: "text/html,*/*" }, redirect: "follow" });
const html = await res.text();
console.log("[probe] status=%d len=%d final=%s", res.status, html.length, res.url);
for (const kw of ["SRT", "管理办法", "信息门户", "统一身份认证", "login", "sso"]) {
  console.log("   %s: %s", kw, html.includes(kw) ? "命中" : "-");
}
const m = html.match(/<title>([^<]{0,80})<\/title>/i);
console.log("[probe] title:", m ? m[1] : "(无)");
fs.writeFileSync(path.join("output", "window", "pages", "srt_probe_raw.html"), html);
console.log("[probe] raw -> output/window/pages/srt_probe_raw.html");
