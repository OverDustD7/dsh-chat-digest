# -*- coding: utf-8 -*-
"""把面板列表导出成项目内的 Markdown 镜像 `docs\\信息列表.md`。

为什么需要：新规范下面板列表是**唯一主产出**，而它落在插件运行态
`%TEMP%\\chat-feed\\state.json`（在工作区之外）——留一份项目内镜像防丢，也方便用编辑器看。

谁跑它：主 agent 每次改完列表后跑一次（它对自己的工作区有写权限；插件侧写不进来，
实测插件导出会报 `cannot write ... file access denied under workspace-write mode`）。

用法（在本工具目录下）：python tools\\export_list_mirror.py
"""
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
OUT = os.path.join(HERE, 'docs', '信息列表.md')
TGROUPS = [('today', '🔴 今天 / 24 小时内'), ('week', '🟡 本周'), ('later', '⚪ 更远')]
# 2026-09-13 用户要求：可报名/可申请的机会单独立一节「二、机会与招募」（原「二、有用信息」顺延为「三」）
CGROUPS = [('today', '2.1 ⏳ 24 小时内截止'), ('week', '2.2 🟡 本周内截止'),
           ('later', '2.3 ⚪ 更远的截止 / 长期开放')]
# 只按 output_format.md「产出形态」承认的 kind 分组；「待确认」**不是**列表的一类
# （2026-09-13 用户纠正：那是主 agent 自己跟的清单），故这里不再设该分组。
KGROUPS = [('official', '3.1 官方信息'), ('peer', '3.2 同学与群里的经验（听说 / 个例）'),
           ('resource', '3.3 资源与工具'), ('life', '3.4 生活与办事')]


def main():
    st, body = cf_api.call('GET', '/chat-feed/api/state')
    if st != 200:
        print('HTTP', st, body[:200])
        return 1
    items = json.loads(body).get('items') or []
    todo = [x for x in items if x.get('kind') == 'todo']
    chance = [x for x in items if x.get('kind') == 'chance']
    info = [x for x in items if x.get('kind') not in ('todo', 'chance')]
    kT = [g[0] for g in TGROUPS]
    kK = [g[0] for g in KGROUPS]
    orderT, orderC, orderI = [], [], []
    for g in TGROUPS:
        for x in todo:
            if x.get('urgency') == g[0]:
                orderT.append((g[1], x))
    for x in todo:
        if x.get('urgency') not in kT:
            orderT.append(('其他待办', x))
    for g in CGROUPS:
        for x in chance:
            if x.get('urgency') == g[0]:
                orderC.append((g[1], x))
    for x in chance:
        if x.get('urgency') not in kT:
            orderC.append(('其他机会', x))
    for g in KGROUPS:
        for x in info:
            if x.get('kind') == g[0]:
                orderI.append((g[1], x))
    for x in info:
        if x.get('kind') not in kK:
            orderI.append(('其他信息', x))

    now = dt.datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')
    out = ['# 聊天情报 · 信息列表（由面板自动导出，勿手改）', '',
           '> 主副本是面板（`/chat-feed/api/items`）；本文件是**镜像**，勾选＝待办已完成 / 信息已知晓。',
           '> 导出：%s CST ｜ 共 %d 条（待办 %d / 机会 %d / 信息 %d；已勾选 %d）'
           % (now, len(items), len(todo), len(chance), len(info),
              sum(1 for x in items if x.get('done'))), '']

    def emit(title, arr, prefix):
        if not arr:
            return
        out.append('## ' + title)
        out.append('')
        last, n = '', 0
        for g, x in arr:
            if g != last:
                out.append('### ' + g)
                out.append('')
                last = g
            n += 1
            body_lines = str(x.get('text') or '').split('\n')
            out.append('- [%s] **%s%d**%s %s' % ('x' if x.get('done') else ' ', prefix, n,
                                                 ' **【新】**' if x.get('isNew') else '',
                                                 body_lines[0] if body_lines else ''))
            for extra in body_lines[1:]:
                out.append('  ' + extra)
            meta = [v for v in (x.get('src'), x.get('date')) if v]
            if meta:
                out.append('  > ' + ' ｜ '.join(meta))
        out.append('')

    emit('一、待办', orderT, 'T')
    emit('二、机会与招募', orderC, 'C')
    emit('三、有用信息', orderI, 'I')
    io.open(OUT, 'w', encoding='utf-8', newline='\n').write('\n'.join(out) + '\n')
    print('写出 %s（%d 字节）：待办 %d / 机会 %d / 信息 %d，已勾选 %d'
          % (OUT, os.path.getsize(OUT), len(todo), len(chance), len(info),
             sum(1 for x in items if x.get('done'))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
