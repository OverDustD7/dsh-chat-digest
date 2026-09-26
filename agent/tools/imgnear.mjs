// imgnear.mjs —— 海报型文章里"关键词附近是哪几张图"。
// 为什么需要（2026-09-13）：`fetch_article.mjs` 把正文图片位置写成 [图片]，正文没有日期/条件，
//   信息全在图里；而一篇文章可能有 39 张图（`article_imgs.mjs` 落成 img01..img39），
//   只能靠"文档顺序"定位——但 [图片] 占位计数（50）和实际落盘图片数（39）不一致，数不出来。
// 本脚本直接在 HTML 上按 `<img` 出现顺序编号（与 `article_imgs.mjs` 的命名完全同一顺序），
//   再给出关键词之后窗口内的图片编号 → 直接 read_image 那几张即可。
// usage: node tools/imgnear.mjs <url> <keyword> [windowChars=4000]
import fs from "node:fs";

const url = process.argv[2];
const kw = process.argv[3];
const win = Number(process.argv[4] || 4000);
if (!url || !kw) {
  console.error("usage: node tools/imgnear.mjs <url> <keyword> [windowChars]");
  process.exit(2);
}
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";
const res = await fetch(url, {
  headers: { "User-Agent": UA, Referer: "https://mp.weixin.qq.com/", "Accept-Language": "zh-CN,zh;q=0.9" },
  redirect: "follow",
});
const html = await res.text();
console.log("[imgnear] status=%d html=%d", res.status, html.length);

// 与 `article_imgs.mjs` 完全同一套编号规则：只收 http(s) 且按 URL 去重（否则编号对不上 imgNN 文件）
const seen = [];
const imgs = [];
for (const m of html.matchAll(/<img[^>]+?(?:data-src|src)="([^"]+)"/g)) {
  const u = m[1].replace(/&amp;/g, "&");
  if (!/^https?:\/\//.test(u) || seen.includes(u)) continue;
  seen.push(u);
  imgs.push({ n: seen.length, at: m.index, src: u });
}
console.log("[imgnear] 图片总数=%d", imgs.length);

let from = 0;
let hits = 0;
while (true) {
  const at = html.indexOf(kw, from);
  if (at < 0) break;
  hits++;
  const until = at + win;
  const near = imgs.filter((i) => i.at >= at && i.at <= until);
  console.log(
    "[imgnear] 命中#%d @%d 之后 %d 字符内的图片: %s",
    hits,
    at,
    win,
    near.map((i) => "img" + String(i.n).padStart(2, "0")).join(",") || "(无)"
  );
  for (const i of near) {
    const tail = i.src.split("/").pop().slice(0, 70);
    console.log("   img%s  %s", String(i.n).padStart(2, "0"), tail);
  }
  from = at + kw.length;
}
if (!hits) console.log("[imgnear] 关键词未命中:", kw);
