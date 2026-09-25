// verify_links.mjs — 本机直连验证链接可访问性（零插件）
// usage: node verify_links.mjs
import fs from "node:fs";
import path from "node:path";

const HERE = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..");
const SRC = path.join(HERE, "output", "window", "all_urls.jsonl");
const OUT = path.join(HERE, "output", "window", "url_check.md");

const SKIP_HOST = /(qlogo\.cn|wxapp\.tc\.qq\.com|vweixinf\.tc\.qq\.com|ugcimg\.cn|tianquan\.gtimg\.cn|zb\.vip\.qq\.com|mmbiz\.qpic\.cn|support\.weixin\.qq\.com|open\.weixin\.qq\.com|open\.gtimg\.cn|cwxlive\.qlogo\.cn|qun\.qq\.com)/i;

const rows = fs.readFileSync(SRC, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const byUrl = new Map();
for (const r of rows) {
  const u = r.url;
  if (SKIP_HOST.test(u)) continue;
  if (!byUrl.has(u)) byUrl.set(u, r);
}
const list = [...byUrl.entries()].map(([url, r]) => ({ url, ...r }));
console.log("[check] candidate urls:", list.length);

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

async function probe(item) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 12000);
  const LOGIN_RE = /(account\.|accounts\.|login|passport|sso|auth\/|signin|wps\.cn\/p\/|user\.)/i;
  try {
    const res = await fetch(item.url, {
      headers: { "User-Agent": UA, Accept: "text/html,*/*" },
      redirect: "follow",
      signal: ctl.signal,
    });
    const ct = res.headers.get("content-type") || "";
    let title = "";
    let needLogin = LOGIN_RE.test(res.url) && res.url !== item.url;
    if (ct.includes("text/html")) {
      const html = (await res.text()).slice(0, 200000);
      const m = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
      title = m ? m[1].replace(/\s+/g, " ").trim().slice(0, 80) : "";
      // #20（2026-09-15 修）：**登录页也会回 200**（如 kdocs 跳到账号页、页面里塞整张 i18n 文案表）
      //   → 除了看最终 URL，再看正文里有没有"请登录/密码"这类登录页特征词。
      if (!needLogin && /请登录|登录后|扫码登录|Sign in|Log in|password/i.test(html.slice(0, 40000))) {
        needLogin = true;
      }
    } else {
      await res.body?.cancel?.();
    }
    return { ...item, status: res.status, finalUrl: res.url, title, needLogin };
  } catch (e) {
    const err = String(e.name || e).slice(0, 40);
    // #19（2026-09-15 修）：**github.com 网页本机不可达**（TypeError: fetch failed），
    //   但 `api.github.com` 通 → 对 github 链接回退到 REST API 判"仓库在不在"。
    const m = /^https?:\/\/github\.com\/([^/]+)\/([^/?#]+)/i.exec(item.url);
    if (m) {
      try {
        const r2 = await fetch(`https://api.github.com/repos/${m[1]}/${m[2].replace(/\.git$/, "")}`, {
          headers: { "User-Agent": UA, Accept: "application/vnd.github+json" },
          signal: ctl.signal,
        });
        const j = r2.ok ? await r2.json() : null;
        return { ...item, status: r2.status, finalUrl: `https://api.github.com/repos/${m[1]}/${m[2]}`,
                 title: j ? `${j.full_name}（★${j.stargazers_count}）` : "", needLogin: false,
                 note: `github→api（网页 ${err}）` };
      } catch (e2) {
        return { ...item, status: 0, error: `github 网页/API 都失败：${err}/${String(e2.name || e2).slice(0, 20)}`, title: "" };
      }
    }
    return { ...item, status: 0, error: err, title: "" };
  } finally {
    clearTimeout(timer);
  }
}

const results = [];
const CONC = 5;
for (let i = 0; i < list.length; i += CONC) {
  const batch = list.slice(i, i + CONC);
  results.push(...(await Promise.all(batch.map(probe))));
}

const ok = results.filter((r) => r.status >= 200 && r.status < 400);
const bad = results.filter((r) => !(r.status >= 200 && r.status < 400));

const fmt = (r) => `- [${r.status || r.error}${r.needLogin ? " · 需登录" : ""}${r.note ? " · " + r.note : ""}] ${r.title ? `**${r.title}** — ` : ""}${r.url}\n    - 来源：${r.src} · ${r.group} · 上下文：${(r.ctx || "").slice(0, 70)}`;

fs.writeFileSync(
  OUT,
  `# 链接可访问性验证（${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC）\n\n` +
    `## 可访问（${ok.length}）\n\n${ok.map(fmt).join("\n")}\n\n## 失败/需登录（${bad.length}）\n\n${bad.map(fmt).join("\n")}\n`,
  "utf8",
);
console.log("[check] ok:", ok.length, "bad:", bad.length, "->", OUT);
for (const r of ok) console.log("  OK ", r.status, r.title || "", r.url.slice(0, 90));
for (const r of bad) console.log("  BAD", r.status || r.error, r.url.slice(0, 90));
