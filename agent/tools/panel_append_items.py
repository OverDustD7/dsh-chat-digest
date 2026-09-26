# -*- coding: utf-8 -*-
"""把本轮新增条目缀到面板列表上（GET live state → 清旧 isNew → 追加 → POST /items 整表回写 → 回读自证）。

为什么单独成脚本：这是**每天那轮**第 3 步的固定动作，历史上每次都临时手写脚本（易漏 `done`、易忘清 isNew）。
本脚本把三条硬要求写死：① 原样保留用户勾选的 `done`；② 上一轮的 `isNew` 一律清掉，只有本轮新增置 true；
③ 数组顺序＝显示顺序（待办在前按紧迫性，再 official → peer → resource → life），**不自己造 T*/I* 编号**。

用法（在本工具目录下）：
    python tools\\panel_append_items.py output\\daily\\2026-09-13\\items.json
    python tools\\panel_append_items.py <json文件> --dry-run
    python tools\\panel_append_items.py <json文件> --allow-dup   # 跳过 id 查重（默认重名即中止）

json 文件格式：`[{...}]` 或 `{"items":[{...}]}`；每条字段 id/text/kind/urgency/done/src/date/isNew。
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
sys.path.insert(0, os.path.join(HERE, 'tools'))
import cf_api  # noqa: E402
from panel_fmt import normalize_text  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=8))
FIELDS = ('id', 'text', 'kind', 'urgency', 'done', 'src', 'date', 'isNew')
# 2026-09-13 用户要求：「机会与招募」独立成节（面板第二节）→ kind='chance'，排在待办之后、信息之前
KIND_RANK = {'todo': 0, 'chance': 1, 'official': 2, 'peer': 3, 'resource': 4, 'life': 5}
URG_RANK = {'today': 0, 'week': 1, 'later': 2}

# ── 「一轮只清一次【新】」的轮次戳（2026-09-26 事故的直接产物）────────────────────
# 事故：那一轮因为「先删旧、再换新 id 重写」分了**两次** append，两次都带了 `--clear-new`
#   ⇒ 第 2 次把第 1 次刚置上的 4 条【新】一起清掉，最终 5 条新增只有 1 条带【新】。
#   两批的自检都"通过"，因为各自只对自己那批算预期 —— **没有任何一步对本轮【新】总数对账**。
# 现在：同一轮内的第 2 次 `--clear-new` **不再清本轮已置【新】的条目**（只清更早那些）。
#   "同一轮"的判据＝距上次 `--clear-new` 不超过 SAME_ROUND_HOURS。一轮实测 10 分钟内跑完，
#   手动轮与 23:30 自动轮相隔十几小时 —— 这个窗口不会把两轮误判成一轮。
#   要拿回"全清"语义（真的换了新的一天/新的一轮）用 `--force-clear-new`。
STAMP = os.path.join(HERE, 'output', 'window', '.clear_new_stamp.json')
SAME_ROUND_HOURS = 3


def load_stamp():
    # 用 utf-8-sig 读：PowerShell 的 `Out-File -Encoding utf8` 会写 BOM，带 BOM 的戳用 utf-8 解不开
    # （2026-09-27 实测：戳被写成 b'\xef\xbb\xbf{...}' ⇒ json.load 抛错 ⇒ 静默当成"没有戳"，
    #  于是闸门失效。凡"读别人写的 json"一律 utf-8-sig。）
    try:
        return json.load(io.open(STAMP, encoding='utf-8-sig'))
    except Exception:  # noqa: BLE001
        return None


def save_stamp(ids, at=None):
    """记下"这一轮由 --clear-new 置上【新】的 id"，供同一轮的第 2 批识别。"""
    try:
        os.makedirs(os.path.dirname(STAMP), exist_ok=True)
        io.open(STAMP, 'w', encoding='utf-8', newline='\n').write(json.dumps(
            {'at': (at or dt.datetime.now(TZ)).isoformat(timespec='seconds'),
             'roundIds': sorted(ids)}, ensure_ascii=False, indent=1))
        return True
    except Exception as e:  # noqa: BLE001
        print('提醒：轮次戳写失败（%s）—— 同一轮再跑 --clear-new 仍会清掉本轮已置的【新】' % e)
        return False


def get_items():
    st, body = cf_api.call('GET', '/chat-feed/api/state')
    if st != 200:
        raise SystemExit('GET /state HTTP %s: %s' % (st, body[:200]))
    return json.loads(body).get('items') or []


def normalize(x):
    out = {k: x.get(k) for k in FIELDS}
    # text 一律过 panel_fmt：正文内部多空行会**真的渲染成空行**（pre-wrap），必须压成单换行
    out['text'] = normalize_text(out.get('text') or '')
    out['kind'] = out.get('kind') or 'official'
    out['urgency'] = out.get('urgency') or 'later'
    out['done'] = bool(out.get('done'))
    out['src'] = out.get('src') or ''
    out['date'] = out.get('date') or dt.datetime.now(TZ).strftime('%m-%d')
    out['isNew'] = bool(out.get('isNew'))
    if not out['id']:
        raise SystemExit('条目缺 id：%r' % (out.get('text') or '')[:60])
    if out['kind'] not in KIND_RANK:
        raise SystemExit('非法 kind=%r（id=%s）' % (out['kind'], out['id']))
    if out['urgency'] not in URG_RANK:
        raise SystemExit('非法 urgency=%r（id=%s）' % (out['urgency'], out['id']))
    return out


def order_key(x):
    return (KIND_RANK[x['kind']], URG_RANK[x['urgency']] if x['kind'] in ('todo', 'chance') else 9)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('new_items', help='本轮新增条目的 json 文件')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--allow-dup', action='store_true')
    ap.add_argument('--clear-new', action='store_true',
                    help='**只给"每天那一轮"用**：把上一轮的【新】清掉。默认**不动**现有条目的 isNew '
                         '（轻量通道追加一条时绝不要清别人的【新】——2026-09-13 踩过：一次追加把当天 5 条【新】全清了）')
    ap.add_argument('--keep-new', action='store_true', help='（旧参数，现在是默认行为，保留兼容）')
    ap.add_argument('--force-clear-new', action='store_true',
                    help='连**本轮**已经置上的【新】也一起清。默认同一轮的第 2 次 --clear-new 不清本轮'
                         '（只清更早那些）——2026-09-26 实测：那一轮两次 append 都带 --clear-new，'
                         '第 2 次把第 1 次的 4 条【新】全清了')
    args = ap.parse_args(argv)

    path = args.new_items if os.path.isabs(args.new_items) else os.path.join(HERE, args.new_items)
    with io.open(path, encoding='utf-8') as fh:
        raw = json.load(fh)
    if isinstance(raw, dict):
        raw = raw.get('items') or []
    new = [normalize(x) for x in raw]
    for x in new:
        x['isNew'] = True
    if not new:
        raise SystemExit('新增条目为空：%s' % path)

    live = [normalize(x) for x in get_items()]
    keep_ids = set()                # 同一轮里"上一批刚置上、这次不许清"的 id
    if args.clear_new:
        st = load_stamp()
        same_round = False
        if st and not args.force_clear_new:
            try:
                last = dt.datetime.fromisoformat(str(st.get('at')))
                same_round = (dt.datetime.now(TZ) - last) <= dt.timedelta(hours=SAME_ROUND_HOURS)
            except Exception:  # noqa: BLE001
                same_round = False
        if same_round:
            keep_ids = set(st.get('roundIds') or []) & {x['id'] for x in live}
            print('注意：%d 小时内已跑过一次 --clear-new ⇒ 判为**同一轮的第 2 批**：'
                  '本轮已置【新】的 %d 条保留不清（真要全清请加 --force-clear-new）'
                  % (SAME_ROUND_HOURS, len(keep_ids)))
        for x in live:
            if x['id'] in keep_ids:
                continue
            x['isNew'] = False                  # 只有"每天那一轮"才清上一轮的【新】
    kept_new = sum(1 for x in live if x['isNew'])   # 清完之后还剩几条【新】（同轮第 2 批时非 0）
    dup = {x['id'] for x in live} & {x['id'] for x in new}
    if dup and not args.allow_dup:
        raise SystemExit('id 与现有条目重复：%s（确要重复请加 --allow-dup）' % ', '.join(sorted(dup)))

    merged = live + new
    merged.sort(key=order_key)                  # 稳定排序 → 组内保持"现有在前、新增在后"
    print('现有 %d 条 + 新增 %d 条 = %d 条；其中 done=True 保留 %d 条'
          % (len(live), len(new), len(merged), sum(1 for x in merged if x['done'])))
    for x in new:
        print('  + [%s/%s] %s | %s' % (x['kind'], x['urgency'], x['id'],
                                       (x['text'] or '').splitlines()[0][:50]))
    if args.dry_run:
        print('--dry-run：未回写')
        return 0

    st, body = cf_api.call('POST', '/chat-feed/api/items', {'items': merged})
    print('POST /items HTTP %s -> %s' % (st, body[:300]))
    if st != 200 or '"ok":true' not in body.replace(' ', ''):
        raise SystemExit('回写失败：面板未改，请看上面的响应')

    after = get_items()
    ids_after = [x.get('id') for x in after]
    expect_new = len(new) + kept_new   # kept_new 是"清完之后剩下的"，两种情形统一用这一条
    ok = (len(after) == len(merged)
          and not ({x['id'] for x in new} - set(ids_after))
          and sum(1 for x in after if x.get('done')) == sum(1 for x in merged if x['done'])
          and sum(1 for x in after if x.get('isNew')) == expect_new)
    print('回读：%d 条；isNew=%d（预期 %d）；done=True=%d'
          % (len(after), sum(1 for x in after if x.get('isNew')), expect_new,
             sum(1 for x in after if x.get('done'))))
    print('自检：%s' % ('通过（条数/新增/勾选/【新】标识四项一致）' if ok else '失败（与预期不符）'))
    # 只有写成功且自检通过才落轮次戳：失败还落的话，下一批会被误判成"同一轮"而不清旧【新】
    if ok and args.clear_new:
        save_stamp(keep_ids | {x['id'] for x in new})
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
