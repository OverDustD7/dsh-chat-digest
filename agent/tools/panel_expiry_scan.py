# -*- coding: utf-8 -*-
r"""清理候选扫描 —— **只列不删**，给每轮的 0.5 步（清理过期 / 他已勾选）用。

为什么要有它：`COLD-START.md` 的第 0.5 步要求"扫一遍当前列表：① 已过时的 ② 用户已勾选的，各列一张清单，
用 `ask_user_question` 征求同意后才删"，但此前**只有删除工具（`panel_drop_items.py`，要显式给 id）**、
没有"该删哪些"的扫描工具 ⇒ 每轮都得靠人肉记。这个脚本把两类候选自动列出来（**一个字都不删**）。

判据（**只做机械筛选，最终要人看**）：
  · A 类「他已勾选」= `done:true`（待办勾＝已完成 / 机会与信息勾＝已知晓）
  · B 类「动作型已过期」= `kind=todo` 且 `date` 距今 ≥ `--days` 天（默认 2）且 `done:false`
  · C 类「机会/信息日期很久」= `kind in (chance, official, peer, resource, life)` 且 `date` 距今 ≥ `--old` 天（默认 7）
    —— 这三类**不是自动删**，只是"值得看一眼"（规则/资源型信息只要仍有效就该留）。

用法：
    python tools\panel_expiry_scan.py                # 列三类候选（不比日期更"智能"）
    python tools\panel_expiry_scan.py --days 3 --old 10
    python tools\panel_expiry_scan.py --ids-only     # 只输出 id（喂给 panel_drop_items.py）
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
import cf_api  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=8))


def age_days(date_str, today):
    """面板里的 date 是 'MM-DD'（个别是 'YYYY-MM-DD'）。返回天数，解不出返回 None。"""
    s = str(date_str or '').strip()
    try:
        if len(s) == 5:
            d = dt.datetime.strptime('%d-%s' % (today.year, s), '%Y-%m-%d').date()
        else:
            d = dt.datetime.strptime(s[:10], '%Y-%m-%d').date()
    except ValueError:
        return None
    if d > today:                      # 跨年（12 月看 01 月）兜一下
        d = d.replace(year=d.year - 1)
    return (today - d).days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=2, help='动作型：距今≥N 天算"该看一眼"')
    ap.add_argument('--old', type=int, default=7, help='机会/信息型：距今≥N 天算"该看一眼"')
    ap.add_argument('--ids-only', action='store_true')
    a = ap.parse_args()
    st, body = cf_api.call('GET', '/chat-feed/api/state')
    if st != 200:
        raise SystemExit('GET /state HTTP %s: %s' % (st, body[:200]))
    items = json.loads(body).get('items') or []
    today = dt.datetime.now(TZ).date()
    A = [x for x in items if x.get('done')]
    B, C = [], []
    for x in items:
        if x.get('done'):
            continue
        n = age_days(x.get('date'), today)
        if n is None:
            continue
        if x.get('kind') == 'todo' and n >= a.days:
            B.append((n, x))
        elif x.get('kind') != 'todo' and n >= a.old:
            C.append((n, x))
    B.sort(key=lambda t: -t[0])
    C.sort(key=lambda t: -t[0])
    if a.ids_only:
        for x in A + [x for _, x in B] + [x for _, x in C]:
            print(x.get('id'))
        return 0

    def dump(title, rows, with_age=True):
        print('\n== %s（%d 条）==' % (title, len(rows)))
        for r in rows:
            n, x = r if with_age else (None, r)
            head = str(x.get('text') or '').split('\n')[0]
            print('  %-28s %-8s %-5s %-5s %s%s' % (x.get('id'), x.get('kind'), x.get('urgency'),
                                                   x.get('date'), ('%2d 天 ｜ ' % n) if n is not None else '', head[:46]))

    print('面板 %d 条 ｜ 今天 %s ｜ 判据：动作型≥%d 天 / 其他≥%d 天' % (len(items), today, a.days, a.old))
    dump('A 类 · 他已勾选（done=true）', A, with_age=False)
    dump('B 类 · 动作型可能已过期（todo 且未勾选）', B)
    dump('C 类 · 机会/信息型日期较久（**仍有效就该留，只看一眼**）', C)
    print('\n**这三张表只是候选，一个字都没删。** 要删走：'
          '\n  python tools\\panel_drop_items.py --reason "…" <id> <id> …（--dry-run 先看一遍；被删原文会留档到 docs\\archive\\<日期>_expired.md）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())