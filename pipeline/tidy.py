# -*- coding: utf-8 -*-
"""tidy.py — 整理工作区：正式脚本留根，一次性/诊断脚本归档；中间产物归入 archive。

规则：**只移动，不删除**。白名单＝日常要用的脚本与数据。
用法：python tidy.py            # 预演（只打印计划）
      python tidy.py --apply    # 实际执行
"""
# ── 个人信息一律来自 pconf（<localDir>/pipeline.yaml）────────────────────────
# 这个文件里**不许写死任何路径 / 群名 / 账号**；缺键时 pconf 会打印缺哪个键、
# 去哪个文件填，并以退出码 2 结束。
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from pconf import C  # noqa: E402

WX_ACCOUNT_DIR = C.get("wx_account_dir")
WX_MSG_GLOB = C.get("wx_msg_glob")
WX_KEY_DIR = C.get("wx_key_dir")
QQ_DATA_DIR = C.get("qq_data_dir")
WORK_DIR = C.get("work_dir")
SELF_WXID = C.get("self_wxid")
MAIN_GROUP = C.get("main_group")

OUT_DIR = C.get("output_dir")
GROUPS = C.groups
# ────────────────────────────────────────────────────────────────────────────
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPLY = "--apply" in sys.argv

# 保留在 scripts\ 的正式脚本（其余 .py/.mjs 归入 scripts\archive\）
KEEP_SCRIPTS = {
    "wx_decrypt3.py", "qq_decrypt_hex.py", "extract_window.py", "extract_day.py",
    "day_brief.py", "day_images.py", "wx_images.py", "wxgf_decode.py", "wxgf_batch.py",
    "wx_session_meta.py", "dig_urls.py", "qq_filter.py", "qq_files.py", "scan_storage.py",
    "daily_prep.py", "find_attachments.py", "tidy.py",
    "fetch_article.mjs", "verify_links.mjs", "verify_extra.mjs", "verify_retry.mjs",
    # 有复用价值的诊断工具（DEV_NOTES / lessons 里引用，勿归档）
    "diag_keymap_decrypt.py", "diag_pb.py", "diag_anchor_diff.py",
    "diag_daily_counts.py", "diag_file_assistant.py", "diag_qq_earliest.py",
}
# 正在被其它子代理使用的脚本：暂不移动
SKIP_PREFIX = ("day0901_",)
# 保留在 output\window\ 的流程产物（其余临时/中间文件归入 output\window\archive\）
KEEP_WINDOW = {
    "wx_raw.jsonl", "wx_chats.txt", "qq_groups.txt", "qq_c2c.txt",
    "all_urls.jsonl", "all_urls.txt", "url_check.md", "session_meta.json",
    "storage_scan.md", "resource_dig.md", "articles", "images", "archive", "wx_chunks",
}

# 明确不动的数据目录
SKIP_DIRS = {"images", "articles", "archive", "wx", "qq", "days", "daily", "backup_20260911"}


def plan_scripts():
    src = os.path.join(HERE, "scripts")
    dst = os.path.join(src, "archive")
    moves = []
    for f in sorted(os.listdir(src)):
        p = os.path.join(src, f)
        if os.path.isdir(p):
            continue
        if f in KEEP_SCRIPTS:
            continue
        if f.startswith(SKIP_PREFIX):
            continue
        if f.endswith((".py", ".mjs", ".js", ".txt", ".out.txt")):
            moves.append((p, os.path.join(dst, f)))
    return moves


def plan_window():
    src = os.path.join(HERE, "output", "window")
    dst = os.path.join(src, "archive")
    moves = []
    for f in sorted(os.listdir(src)):
        p = os.path.join(src, f)
        if f in KEEP_WINDOW or f in SKIP_DIRS:
            continue
        if os.path.isdir(p):
            continue
        moves.append((p, os.path.join(dst, f)))
    return moves


def do(moves, label):
    print("\n=== %s：计划移动 %d 个 ===" % (label, len(moves)))
    for a, b in moves[:200]:
        print("   %-46s -> %s" % (os.path.basename(a), os.path.relpath(b, HERE)))
    if len(moves) > 200:
        print("   ...（其余 %d 个）" % (len(moves) - 200))
    if APPLY:
        for a, b in moves:
            os.makedirs(os.path.dirname(b), exist_ok=True)
            try:
                if os.path.exists(b):
                    # 归档区已有同名 → **改名保留，绝不删除**
                    # （本文件 :3 与 变更记录.md 的硬约束都是"只移动，不删除"；
                    #   这里原来是 os.remove(a)，2026-09-14 审计发现并改掉）
                    shutil.move(a, b + ".dup")
                else:
                    shutil.move(a, b)
            except Exception as e:  # noqa: BLE001
                print("   ERR %s: %s" % (os.path.basename(a), e))
        print("   -> 已执行")
    else:
        print("   （未加 --apply，仅预演）")


do(plan_scripts(), "scripts\\ 一次性/诊断脚本")
do(plan_window(), "output\\window\\ 中间产物")
print("\n完成。" if APPLY else "\n预演结束；加 --apply 才会真正移动。")