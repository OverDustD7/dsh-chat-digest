// pipeline/pconf.mjs —— JS 侧读同一份「个人信息」（与 pconf.py 同一套解析顺序）。
//
// 取值优先级：<localDir>/pipeline.json[key] > <localDir>/pipeline.yaml 的扁平键 > default。
// 复杂结构（对象数组，如 web_sources）请放 pipeline.json。
// `localDir`：$DSH_CHAT_FEED_LOCAL → $DSH_HOME/dsh-chat-digest。

import fs from 'node:fs';
import path from 'node:path';

function localDir() {
  const env = process.env.DSH_CHAT_FEED_LOCAL || '';
  if (env) {
    if (!path.isAbsolute(env)) throw new Error('DSH_CHAT_FEED_LOCAL 必须是绝对路径');
    return fs.existsSync(env) ? fs.realpathSync(env) : env;
  }
  const appdata = process.env.LOCALAPPDATA
    || (process.env.USERPROFILE ? path.join(process.env.USERPROFILE, 'AppData', 'Local') : '');
  const home = process.env.DSH_HOME || (process.env.USERPROFILE ? path.join(process.env.USERPROFILE, '.dsh') : '');
  const selected = (home && path.join(home, 'dsh-chat-digest'))
    || (appdata && path.join(appdata, 'dsh-chat-digest'));
  if (!selected || !path.isAbsolute(selected)) throw new Error('私人 profile 需要绝对路径：请设置 DSH_HOME');
  return fs.existsSync(selected) ? fs.realpathSync(selected) : selected;
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
