# -*- coding: utf-8 -*-
# 出处：解密器来自 WeChatDataAnalysis 项目（本脚本只是绕过它的 __init__，
#   以免引入 starlette/fastapi 那套 GUI 依赖）。使用本项目前请确认其许可与当地法律。
"""
Decrypt WeChat 4.x WCDB databases with WeChatDataAnalysis's own decryptor,
bypassing the package __init__ (which pulls in starlette/fastapi GUI deps).

Usage: python wx_decrypt3.py <key_hex>
Outputs -> <out_dir>/wx/*_plain.db
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
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))          # <工作区>\pipeline
ROOT = os.path.dirname(HERE)                                # <工作区>
WX_TOOL = os.path.join(os.path.dirname(ROOT), "WeChatDataAnalysis")   # <上级目录>\WeChatDataAnalysis
SRC = os.path.join(WX_TOOL, "src")
PKG_DIR = os.path.join(SRC, "wechat_decrypt_tool")

# fake package so relative imports work without executing __init__.py
pkg = types.ModuleType("wechat_decrypt_tool")
pkg.__path__ = [PKG_DIR]
pkg.__version__ = "0.0.0"
sys.modules["wechat_decrypt_tool"] = pkg

import importlib  # noqa: E402

wd = importlib.import_module("wechat_decrypt_tool.wechat_decrypt")
WeChatDatabaseDecryptor = wd.WeChatDatabaseDecryptor

DBROOT = r"WX_ACCOUNT_DIR\db_storage"
OUT = os.path.join(ROOT, "output", "wx")

DBS = [
    r"message\message_0.db",
    r"message\message_1.db",
    r"message\message_2.db",
    r"message\message_3.db",
    r"message\message_4.db",
    r"contact\contact.db",
    r"session\session.db",
    r"general\general.db",
]


def main():
    """返回退出码：**0 只在"确实解开了"时给**（A08，2026-09-20 审计 P01）。

    旧版的问题：源库一个都不存在时只打印 SKIP，`main()` 返回 None → 退出码 0 →
    上游（daily_prep 只看退出码/文件存在/行数）把"什么都没解"当成功，
    于是下游继续消费**上一轮的旧 `_plain.db`**，链路看起来正常。
    现在：源库命中 0 个、或命中了但一个都没解开 → 退出码 1。
    另外落一份 `output/wx/_decrypt_run.json` 记录本轮来源与结果（run 记录）。
    """
    if len(sys.argv) < 2:
        print("usage: wx_decrypt3.py <key_hex>")
        raise SystemExit(2)
    key = sys.argv[1]
    os.makedirs(OUT, exist_ok=True)
    dec = WeChatDatabaseDecryptor(key)
    ok = 0
    found = 0
    detail = {}
    for rel in DBS:
        src = os.path.join(DBROOT, rel)
        if not os.path.exists(src):
            print("  SKIP (missing) %s" % src)
            detail[rel] = "missing"
            continue
        found += 1
        dst = os.path.join(OUT, os.path.basename(rel).replace(".db", "_plain.db"))
        try:
            good = dec.decrypt_database(src, dst)
            r = dec.last_result or {}
            print("  %s %-22s mode=%s pages=%s ok_pages=%s warn=%s err=%s"
                  % ("OK  " if good else "FAIL", os.path.basename(rel),
                     r.get("key_mode"), r.get("total_pages"),
                     r.get("successful_pages"), r.get("hmac_warning_pages"),
                     str(r.get("error"))[:80]))
            ok += 1 if good else 0
            if good:
                # 保证"本轮产物"可判：解密器内部可能因内容一致而跳过重写，
                # 那样 mtime 会停在上一轮，daily_prep 的新鲜度自检会误报 STALE。
                try:
                    os.utime(dst, None)
                except OSError:
                    pass
            detail[rel] = {"ok": bool(good), "mode": r.get("key_mode"),
                           "pages": r.get("total_pages"), "ok_pages": r.get("successful_pages")}
        except Exception as e:
            print("  ERROR %s: %s: %s" % (os.path.basename(rel), type(e).__name__, e))
            detail[rel] = "error: %s: %s" % (type(e).__name__, e)
    print("decrypted %d/%d（源库命中 %d/%d）" % (ok, len(DBS), found, len(DBS)))
    try:                                  # run 记录：这次到底从哪个源、解开了几个
        import json
        import time
        with open(os.path.join(OUT, "_decrypt_run.json"), "w", encoding="utf-8") as fh:
            json.dump({"at": int(time.time()), "dbroot": DBROOT, "found": found,
                       "ok": ok, "total": len(DBS), "detail": detail}, fh,
                      ensure_ascii=False, indent=1)
    except Exception as e:                # noqa: BLE001
        print("  !! run 记录写失败:", e)
    if found == 0:
        print("[x] 源库一个都没找到（DBROOT=%s）—— 解密没有发生，不能当成功（A08）" % DBROOT)
        return 1
    if ok == 0:
        print("[x] 命中 %d 个源库但一个都没解开（key/登录态问题）—— 不能当成功（A08）" % found)
        return 1
    if ok < found:
        print("[!] 部分失败：%d/%d 解开 → degraded（产物新鲜度由 daily_prep 校验）" % (ok, found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())