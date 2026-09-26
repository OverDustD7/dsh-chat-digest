# -*- coding: utf-8 -*-
"""按 id 对面板条目正文做**字面替换**（改条目的唯一通道），带 dry-run、留档与回读自证。

为什么需要：§六「用户的反馈怎么进来」里，多数反馈是"这条报得不对/不全/格式不对"——要改的是**正文**。
手写整表 POST 容易丢字段（done/isNew/src/date），也不便自证。这个脚本把规矩固化下来：
  ① 只改点名的 id；② 每处 `old` 必须在该条正文里**恰好出现一次**（0 次或多次一律中止，防误伤）；
  ③ 改前先把 before/after 追加到 `docs\\archive\\<日期>_edits.md`；④ 整表回写后回读自证。

用法（在本工具目录下）：
    python tools\\panel_patch_text.py spec.json [--dry-run]
spec.json 形如：
    {"reason": "清掉指向已删条目的悬空引用",
     "patches": [{"id": "thubook", "old": "旧句子", "new": "新句子"}]}
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
from panel_fmt import normalize_text  # noqa: E402   # 改完的正文也要过统一换行口径

TZ = dt.timezone(dt.timedelta(hours=8))


def _show(text, needle):
    """取 needle 在 text 里的片段用于打印。needle 可能跨行（插入/删除整段），原先按行筛会 IndexError。"""
    if needle not in text:
        return '(未找到)'
    head = needle.split('\n')[0]
    if len(head) > 120:
        head = head[:117] + '...'
    return head + ('  …（共 %d 行）' % (needle.count('\n') + 1) if '\n' in needle else '')


def get_items():
    st, body = cf_api.call('GET', '/chat-feed/api/state')
    if st != 200:
        raise SystemExit('GET /state HTTP %s: %s' % (st, body[:200]))
    return json.loads(body).get('items') or []


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('spec')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    now = dt.datetime.now(TZ)
    spec = json.load(io.open(args.spec, encoding='utf-8'))
    patches = spec.get('patches') or []
    reason = spec.get('reason') or '（未填原因）'
    if not patches:
        raise SystemExit('spec 里没有 patches')

    items = get_items()
    by_id = {x.get('id'): x for x in items}
    orig = {}          # 每个 id 的**原始**正文（留档用）
    work = {}          # 每个 id 的**累积后**正文（同一 id 的多条 patch 依次叠加）
    order = []
    shown = []
    for p in patches:
        item = by_id.get(p['id'])
        if item is None:
            raise SystemExit('面板上没有 %s' % p['id'])
        iid = p['id']
        if iid not in work:
            orig[iid] = str(item.get('text') or '')
            work[iid] = orig[iid]
            order.append(iid)
        n = work[iid].count(p['old'])
        if n != 1:
            raise SystemExit('中止：%s 里 old 出现 %d 次（要求恰好 1 次）\n  old=%r' % (iid, n, p['old']))
        pre = work[iid]
        work[iid] = normalize_text(work[iid].replace(p['old'], p['new']))
        shown.append((iid, pre, work[iid], p['old'], p['new']))
    # 留档按 id 一条（before = 原始、after = 累积结果），避免同一 id 多条 patch 时互相覆盖
    log = [(iid, orig[iid], work[iid]) for iid in order]

    for iid, pre, after, old, new in shown:
        print('--- %s ---' % iid)
        print('  旧：%s' % _show(pre, old))
        print('  新：%s' % _show(after, new))
    if args.dry_run:
        print('--dry-run：未写留档、未回写')
        return 0

    arch = os.path.join(HERE, 'docs', 'archive', '%s_edits.md' % now.strftime('%Y-%m-%d'))
    head = ''
    if not os.path.exists(arch):
        head = ('# %s 面板条目正文修改留档\n\n'
                '> 面板（`/chat-feed/api/items`）是主副本；这里留 before/after 便于回溯。\n\n'
                % now.strftime('%Y-%m-%d'))
    chunk = ['## %s —— %s' % (now.strftime('%Y-%m-%d %H:%M'), reason), '']
    for iid, before, after in log:
        chunk += ['### %s' % iid, '', '**改前**', '', '```', before, '```', '', '**改后**', '', '```', after,
                  '```', '']
    io.open(arch, 'a', encoding='utf-8', newline='\n').write(head + '\n'.join(chunk) + '\n')
    print('留档写入 %s（%d 字节）' % (arch, os.path.getsize(arch)))

    for (iid, before, after) in log:
        by_id[iid]['text'] = after
    st, body = cf_api.call('POST', '/chat-feed/api/items', {'items': items})
    print('POST /items HTTP %s -> %s' % (st, body[:300]))
    if st != 200 or '"ok":true' not in body.replace(' ', ''):
        raise SystemExit('回写失败，留档已写、面板未动')

    after_items = get_items()
    after_by_id = {x.get('id'): x for x in after_items}
    ok = len(after_items) == len(items)
    for iid, before, after in log:
        if after_by_id.get(iid, {}).get('text') != after:
            ok = False
            print('自检失败：%s 回读正文与预期不一致' % iid)
    print('回读 %d 条；自检：%s' % (len(after_items), '通过' if ok else '失败'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
