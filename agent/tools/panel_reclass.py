# -*- coding: utf-8 -*-
r"""panel_reclass.py —— 批量改面板条目的 `kind`（整表回写 + 回读自证）。

为什么需要（2026-09-13）：用户要求新增一节「二、机会与招募」→ 需要把「可报名 / 可申请的机会」
从 `todo` / `official` 移到新的 `chance`。`panel_patch_text.py` 只改 `text`，`panel_append_items.py` 只追加，
所以这里补一个**只改 kind** 的通道：其余字段（含用户勾选的 `done`）原样保留。

用法（在本工具目录下）：
    python tools\panel_reclass.py chance creative-cup taiyc-2026 dance-2026 g3-qingongzhuxue
    python tools\panel_reclass.py chance <id...> --dry-run
"""
import argparse
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'docs', 'agent'))
import cf_api  # noqa: E402
from panel_append_items import KIND_RANK  # noqa: E402  同一套合法 kind


def get_items():
    st, body = cf_api.call('GET', '/chat-feed/api/state')
    if st != 200:
        raise SystemExit('GET /state HTTP %s: %s' % (st, body[:200]))
    return json.loads(body).get('items') or []


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('kind')
    ap.add_argument('ids', nargs='+')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)
    if args.kind not in KIND_RANK:
        raise SystemExit('非法 kind=%r（合法：%s）' % (args.kind, '/'.join(KIND_RANK)))

    items = get_items()
    by_id = {x.get('id'): x for x in items}
    missing = [i for i in args.ids if i not in by_id]
    if missing:
        raise SystemExit('面板上没有：%s' % ', '.join(missing))
    before = {i: by_id[i].get('kind') for i in args.ids}
    for i in args.ids:
        print('  %-20s %s -> %s' % (i, before[i], args.kind))
    if args.dry_run:
        print('--dry-run：未回写')
        return 0

    for i in args.ids:
        by_id[i]['kind'] = args.kind
    st, body = cf_api.call('POST', '/chat-feed/api/items', {'items': items})
    print('POST /items HTTP %s -> %s' % (st, body[:300]))
    if st != 200 or '"ok":true' not in body.replace(' ', ''):
        raise SystemExit('回写失败，面板未改')

    after = get_items()
    ab = {x.get('id'): x for x in after}
    ok = (len(after) == len(items)
          and all(ab[i].get('kind') == args.kind for i in args.ids)
          and sum(1 for x in after if x.get('done')) == sum(1 for x in items if x.get('done')))
    print('回读 %d 条；%s 已改为 %s；自检：%s'
          % (len(after), len(args.ids), args.kind, '通过' if ok else '失败'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
