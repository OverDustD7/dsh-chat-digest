# -*- coding: utf-8 -*-
r"""export_day_items.py —— 落"本轮验收后最终采纳的条目"到 `output\daily\<DATE>\items.json`。

为什么要有它（2026-09-15 用户指出）：规范要求每轮交付**只有一个** `output\daily\<DATE>\items.json`，
但 09-14 那一轮只落了 `items_append_redo.json` / `items_accepted.json` / `patch_*.json` / `sliceNN_items.json`，
**没有 items.json** —— 这条欠账挂了两轮。于是把"从面板读回本轮动过的条目、写成 items.json"固化成命令。

判据：**面板是主副本**，所以 items.json 里存的是这些 id **当前的真实正文**（含之后的口径更正），
字段就是面板那 8 个（id/text/kind/urgency/done/src/date/isNew）——即"我实际回写进面板的那些"。

用法:
    python tools\export_day_items.py 2026-09-14 id1 id2 id3 …
    python tools\export_day_items.py 2026-09-14 --ids-file output\daily\2026-09-14\_redo_ids.txt
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

FIELDS = ('id', 'text', 'kind', 'urgency', 'done', 'src', 'date', 'isNew')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('date')
    ap.add_argument('ids', nargs='*')
    ap.add_argument('--ids-file')
    a = ap.parse_args(argv)
    ids = list(a.ids)
    if a.ids_file:
        p = a.ids_file if os.path.isabs(a.ids_file) else os.path.join(HERE, a.ids_file)
        raw = [ln.strip() for ln in io.open(p, encoding='utf-8') if ln.strip() and not ln.startswith('#')]
        # A09：校验 id 文件格式 —— 一行一个 id；出现空白分隔（误把整份 items.json 传进来）
        # 或明显不像 id 的行，先报出来再继续，别静默拼出几百个假 id。
        odd = [ln for ln in raw if any(c.isspace() for c in ln) or len(ln) > 120]
        if odd:
            print('警告：--ids-file 里有 %d 行不像"一行一个 id"（前 3 行：%s）'
                  % (len(odd), ' / '.join(x[:60] for x in odd[:3])))
        ids += raw
    if not ids:
        print('错误：没有给 id（拒绝写空交付物）')
        return 2

    st, body = cf_api.call('GET', '/chat-feed/api/state')
    if st != 200:
        print('GET /state HTTP %s: %s' % (st, body[:200]))
        return 3
    live = {x.get('id'): x for x in (json.loads(body).get('items') or [])}
    out, missing = [], []
    for i in ids:
        x = live.get(i)
        if not x:
            missing.append(i)
            continue
        out.append({k: x.get(k) for k in FIELDS})

    # A09：**所有 id 必须命中**，且结果不得为空 —— 否则拒绝覆盖已有交付物。
    # 起因：传一个不存在的 id 时旧版只"警告"，随后把已有 items.json 直接覆盖成 []（台账 #136 同型事故）。
    if missing or not out:
        if not out:
            print('拒绝写入：%d 个 id 一个都没命中面板，结果为空会覆盖已有交付物' % len(missing))
        else:
            print('拒绝写入：这些 id 不在面板上：%s' % ', '.join(missing))
        print('  未命中：%s' % ', '.join(missing))
        print('  已有交付物保持原样：%s' % os.path.join(HERE, 'output', 'daily', a.date, 'items.json'))
        return 4

    p = os.path.join(HERE, 'output', 'daily', a.date, 'items.json')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if os.path.exists(p):
        with io.open(p, encoding='utf-8') as fh:
            prev = fh.read()
        bak = p + '.bak'
        with io.open(bak, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(prev)
        print('旧交付物已另存（可恢复）：%s（%d 字节）' % (bak, len(prev.encode('utf-8'))))
    tmp = p + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    os.replace(tmp, p)                      # 原子替换：中途失败不会留下半个文件
    print('写出 %s ｜ %d 条（原样保留 done / isNew 状态）' % (p, len(out)))
    for x in out:
        print('  %-26s %-8s %-5s done=%-5s isNew=%-5s %s' % (x['id'], x['kind'], x['urgency'],
                                                             x['done'], x['isNew'], (x['text'] or '').split('\n')[0][:42]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
