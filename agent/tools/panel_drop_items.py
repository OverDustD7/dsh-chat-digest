# -*- coding: utf-8 -*-
"""从面板列表移除指定条目（GET /state → 过滤 → POST /items 整表回写），并留档。

为什么单独成脚本：删条目是**唯一会丢东西**的动作（硬约束③：不自行删除文件/内容），
所以要走固定路径：① 读 live state（保留用户勾选的 done 等字段）② 把被删条目原文写进
`docs\\archive\\<date>_expired.md` ③ 再整表回写 ④ 回读自证。

用法（在本工具目录下）：
    python tools\\panel_drop_items.py --reason "用户 09-13 说已选完课" calc-cjl
    python tools\\panel_drop_items.py --dry-run calc-cjl        # 只看会删什么，不写
归档默认写到 `docs\\archive\\<今天>_expired.md`（--archive 可指定）。
"""
import argparse
import datetime as dt
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # agent 根（＝包内 agent/ 或 <个人目录>）
sys.path.insert(0, os.path.join(HERE, 'docs', 'agent'))
import cf_api  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=8))


def get_items():
    st, body = cf_api.call('GET', '/chat-feed/api/state')
    if st != 200:
        raise SystemExit('GET /state HTTP %s: %s' % (st, body[:200]))
    return json.loads(body).get('items') or []


def archive_block(dropped, reason, now):
    out = []
    out.append('## %s 移除 %d 条' % (now, len(dropped)))
    out.append('')
    out.append('- 原因：%s' % reason)
    out.append('- 途径：用户同意后，由 `tools\\panel_drop_items.py` 从面板整表回写时移除；本文件只留档。')
    out.append('')
    for x in dropped:
        out.append('### %s ｜ kind=%s ｜ urgency=%s ｜ src=%s ｜ date=%s ｜ done=%s'
                   % (x.get('id'), x.get('kind'), x.get('urgency'), x.get('src'),
                      x.get('date'), x.get('done')))
        out.append('')
        for line in str(x.get('text') or '').split('\n'):
            out.append(('    ' + line) if line.strip() else '')
        out.append('')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('ids', nargs='+', help='要移除的条目 id')
    ap.add_argument('--reason', default='（未填原因）')
    ap.add_argument('--archive', default=None)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    now = dt.datetime.now(TZ).strftime('%Y-%m-%d %H:%M')
    today = dt.datetime.now(TZ).strftime('%Y-%m-%d')
    arch = args.archive or os.path.join(HERE, 'docs', 'archive', '%s_expired.md' % today)

    items = get_items()
    want = set(args.ids)
    dropped = [x for x in items if x.get('id') in want]
    kept = [x for x in items if x.get('id') not in want]
    missing = want - {x.get('id') for x in items}
    if not dropped:
        raise SystemExit('没有匹配的条目：%s（面板现有 %d 条）' % (', '.join(args.ids), len(items)))
    if missing:
        print('注意：这些 id 不在面板上，已跳过 -> %s' % ', '.join(sorted(missing)))

    print('将移除 %d 条：%s' % (len(dropped), ', '.join(x.get('id') for x in dropped)))
    print('移除后 %d 条（原 %d 条）；其中 done=True 的 %d 条原样保留'
          % (len(kept), len(items), sum(1 for x in kept if x.get('done'))))
    if args.dry_run:
        print('--dry-run：未写归档、未回写')
        return 0

    head = ''
    if not os.path.exists(arch):
        head = ('# %s 从面板列表移除的条目（留档）\n\n'
                '> 面板（`/chat-feed/api/items`）是主副本；这里只防丢，用户看不到。\n\n' % today)
    block = archive_block(dropped, args.reason, now)
    io.open(arch, 'a', encoding='utf-8', newline='\n').write(head + '\n'.join(block) + '\n')
    print('归档写入 %s（%d 字节）' % (arch, os.path.getsize(arch)))

    st, body = cf_api.call('POST', '/chat-feed/api/items', {'items': kept})
    print('POST /items HTTP %s -> %s' % (st, body[:300]))
    if st != 200 or '"ok":true' not in body.replace(' ', ''):
        raise SystemExit('回写失败，归档已写、面板未动：请看上面的响应')

    after = get_items()
    ids_after = [x.get('id') for x in after]
    ok = len(after) == len(kept) and not (want & set(ids_after))
    print('回读：%d 条，剩余 id = %s' % (len(after), ', '.join(ids_after)))
    print('自检：%s' % ('通过（条数一致、目标条目已消失）' if ok else '失败（与预期不符）'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
