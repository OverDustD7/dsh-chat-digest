# -*- coding: utf-8 -*-
r"""panel_set_text.py —— 把面板**某一条的正文整条替换**（带回读自证与留档）。

为什么需要它（2026-09-14）：用户的引用反馈经常是"这条只留 X"——`panel_patch_text.py` 要求写出精确的 old 片段
（长正文很难逐字复现），`panel_append_items.py` 只能追加。这类"整条改写"两天里出现两次 → 固化成一个小工具。

用法（在本工具目录下）：
    python tools\panel_set_text.py <id> <新正文文件.md> [--reason "…"] [--dry-run]
    （新正文文件里就是该条的完整 text：一句话总结 + 空行 + 正文）
"""
import argparse
import datetime as dt
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'docs', 'agent'))
sys.path.insert(0, os.path.join(HERE, 'tools'))
import cf_api  # noqa: E402
from panel_fmt import normalize_text, stats  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=8))


def get_items():
    st, body = cf_api.call('GET', '/chat-feed/api/state')
    if st != 200:
        raise SystemExit('GET /state HTTP %s: %s' % (st, body[:200]))
    return json.loads(body).get('items') or []


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('item_id')
    ap.add_argument('text_file')
    ap.add_argument('--reason', default='（未填原因）')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)

    path = a.text_file if os.path.isabs(a.text_file) else os.path.join(HERE, a.text_file)
    new = normalize_text(io.open(path, encoding='utf-8').read())
    if not new:
        raise SystemExit('新正文为空：%s' % path)

    items = get_items()
    hit = [x for x in items if x.get('id') == a.item_id]
    if not hit:
        raise SystemExit('面板上没有 %s' % a.item_id)
    old = str(hit[0].get('text') or '')
    so, sn = stats(old), stats(new)
    print('%s：旧 %d 字（双换行 %d）→ 新 %d 字（双换行 %d）' % (a.item_id, so['len'], so['dbl'], sn['len'], sn['dbl']))
    print('--- 新正文前 120 字 ---\n%s' % new[:120])
    if a.dry_run:
        print('--dry-run：未回写')
        return 0

    hit[0]['text'] = new
    st, body = cf_api.call('POST', '/chat-feed/api/items', {'items': items})
    print('POST /items HTTP %s -> %s' % (st, body[:200]))
    if st != 200 or '"ok":true' not in body.replace(' ', ''):
        raise SystemExit('回写失败，面板未改')

    now = dt.datetime.now(TZ)
    arch = os.path.join(HERE, 'docs', 'archive', '%s_edits.md' % now.strftime('%Y-%m-%d'))
    with io.open(arch, 'a', encoding='utf-8', newline='\n') as fh:
        fh.write('\n## %s ｜ %s 整条改写 —— %s\n\n**改前**\n\n```\n%s\n```\n\n**改后**\n\n```\n%s\n```\n'
                 % (now.strftime('%Y-%m-%d %H:%M'), a.item_id, a.reason, old, new))

    after = get_items()
    got = [x for x in after if x.get('id') == a.item_id]
    ok = len(after) == len(items) and got and got[0]['text'] == new
    print('回读 %d 条；留档 %s；自检：%s' % (len(after), os.path.basename(arch), '通过' if ok else '失败'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
