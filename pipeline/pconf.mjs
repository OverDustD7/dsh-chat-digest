// pipeline/pconf.mjs —— JS 侧读同一份「个人信息」（与 pconf.py 同一套解析顺序）。
//
// 取值优先级：<localDir>/pipeline.json[key] > <localDir>/pipeline.yaml 的扁平键 > default。
// 复杂结构（对象数组，如 web_sources）请放 pipeline.json。
// `localDir`：$DSH_CHAT_FEED_LOCAL → 包旁的 local/ → 包内 local/。

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

function localDir() {
  const env = process.env.DSH_CHAT_FEED_LOCAL || '';
  if (env && fs.existsSync(env)) return env;
  for (const c of [path.join(HERE, '..', 'local'), path.join(HERE, 'local')]) {
    if (fs.existsSync(c)) return c;
  }
  return env || path.join(HERE, '..', 'local');
}

const DIR = localDir();

function readJson() {
  try {
    return JSON.parse(fs.readFileSync(path.join(DIR, 'pipeline.json'), 'utf8'));
  } catch (e) {
    return {};
  }
}

function readFlat() {
  const out = {};
  let text = '';
  try {
    text = fs.readFileSync(path.join(DIR, 'pipeline.yaml'), 'utf8');
  } catch (e) {
    return out;
  }
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || line.startsWith('- ')) continue;
    const i = line.indexOf(':');
    if (i < 0) continue;
    const k = line.slice(0, i).trim();
    let v = line.slice(i + 1).split('#')[0].trim();
    if (v.length >= 2 && (v[0] === "'" || v[0] === '"') && v[v.length - 1] === v[0]) v = v.slice(1, -1);
    out[k] = v;
  }
  return out;
}

const JSON_CFG = readJson();
const FLAT_CFG = readFlat();

export function cfg(key, def = '') {
  if (Object.prototype.hasOwnProperty.call(JSON_CFG, key)) return JSON_CFG[key];
  if (Object.prototype.hasOwnProperty.call(FLAT_CFG, key)) return FLAT_CFG[key];
  return def;
}

export function cfgList(key) {
  const v = cfg(key, []);
  if (Array.isArray(v)) return v;
  return v ? [v] : [];
}

export { DIR as configDir };
