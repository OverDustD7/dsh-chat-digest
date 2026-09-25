# -*- coding: utf-8 -*-
"""wx_decrypt_more.py — 解密「其余」微信库（biz_message / favorite / sns / media / bizchat …）。

用法: python wx_decrypt_more.py <key_hex>
输出: output/wx/<name>_plain.db
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
import importlib
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WX_TOOL = os.path.join(os.path.dirname(ROOT), "WeChatDataAnalysis")
PKG_DIR = os.path.join(WX_TOOL, "src", "wechat_decrypt_tool")
pkg = types.ModuleType("wechat_decrypt_tool")
pkg.__path__ = [PKG_DIR]
pkg.__version__ = "0.0.0"
sys.modules["wechat_decrypt_tool"] = pkg
wd = importlib.import_module("wechat_decrypt_tool.wechat_decrypt")
WeChatDatabaseDecryptor = wd.WeChatDatabaseDecryptor

DBROOT = r"WX_ACCOUNT_DIR\db_storage"
OUT = os.path.join(ROOT, "output", "wx")

EXTRA = [
    r"message\biz_message_0.db",          # 公众号文章消息
    r"message\media_0.db",                # 媒体
    r"message\message_resource.db",
    r"message\message_fts.db",
    r"message\weclaw.db",
    r"favorite\favorite.db",              # 收藏
    r"favorite\favorite_fts.db",
    r"sns\sns.db",                        # 朋友圈
    r"bizchat\bizchat.db",
    r"emoticon\emoticon.db",
    r"solitaire\solitaire.db",
    r"chatbot\chatbot_message.db",
    r"head_image\head_image.db",
    r"hardlink\hardlink.db",
    r"contact\contact_fts.db",
    r"migrate\unspportmsg.db",
    r"third_app_icon\third_app_icon.db",
]


def main():
    if len(sys.argv) < 2:
        print("usage: wx_decrypt_more.py <key_hex>")
        sys.exit(2)
    key = sys.argv[1]
    only = sys.argv[2] if len(sys.argv) > 2 else None
    os.makedirs(OUT, exist_ok=True)
    dec = WeChatDatabaseDecryptor(key)
    ok = 0
    targets = [r for r in EXTRA if (only in r)] if only else EXTRA
    for rel in targets:
        src = os.path.join(DBROOT, rel)
        if not os.path.exists(src):
            print("  SKIP (missing) %s" % rel)
            continue
        dst = os.path.join(OUT, os.path.basename(rel).replace(".db", "_plain.db"))
        try:
            good = dec.decrypt_database(src, dst)
            r = dec.last_result or {}
            print("  %s %-26s pages=%s ok=%s err=%s"
                  % ("OK  " if good else "FAIL", os.path.basename(rel),
                     r.get("total_pages"), r.get("successful_pages"), str(r.get("error"))[:60]))
            ok += 1 if good else 0
        except Exception as e:  # noqa: BLE001
            print("  ERROR %s: %s: %s" % (os.path.basename(rel), type(e).__name__, e))
    print("decrypted %d/%d" % (ok, len(EXTRA)))


if __name__ == "__main__":
    main()