// article_imgs.mjs —— 把微信文章的正文图片抓成本地文件（给 read_image 读）。
// 为什么需要：海报型推文的正文只有 [图片] 占位（fetch_article.mjs 抓不到文字），
// 但信息就在图里 —— 用户 2026-09-13 明确"你可以读图啊"。
// usage: node article_imgs.mjs <url> <outdir>
import fs from "node:fs";
import path from "node:path";

const url = process.argv[2];
const outdir = process.argv[3];
if (!url || !outdir) {
  console.error("usage: node article_imgs.mjs <url> <outdir>");
  process.exit(2);
}

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

const res = await fetch(url, {
  headers: {
    "User-Agent": UA,
    Referer: "https://mp.weixin.qq.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
  },
  redirect: "follow",
});
const html = await res.text();
console.log("[article_imgs] status=%d html=%d", res.status, html.length);

const found = [];
for (const m of html.matchAll(/<img[^>]+?(?:data-src|src)="([^"]+)"/g)) {
  const u = m[1].replace(/&amp;/g, "&");
  if (/^https?:\/\//.test(u) && !found.includes(u)) found.push(u);
}
console.log("[article_imgs] imgs found=%d", found.length);

fs.mkdirSync(outdir, { recursive: true });
let i = 0;
for (const u of found) {
  i += 1;
  const ext = /wx_fmt=png|\.png(\?|$)/i.test(u) ? "png" : "jpg";
  const p = path.join(outdir, "img" + String(i).padStart(2, "0") + "." + ext);
  try {
    const r = await fetch(u, {
      headers: { "User-Agent": UA, Referer: "https://mp.weixin.qq.com/" },
    });
    if (!r.ok) {
      console.log("  FAIL HTTP %d %s", r.status, u.slice(0, 90));
      continue;
    }
    const buf = Buffer.from(await r.arrayBuffer());
    fs.writeFileSync(p, buf);
    console.log("  OK %s (%d B)", p, buf.length);
  } catch (e) {
    console.log("  ERR %s %s", e.message, u.slice(0, 90));
  }
}
