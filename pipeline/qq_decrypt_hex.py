# -*- coding: utf-8 -*-
# 出处：改自 QQBackup/nt_msg_db_util 的 1.decrypt.py（x'hex' 原始密钥模式）。
#   使用本项目前请确认其许可与当地法律。
"""
Decrypt NTQQ nt_msg.db (1024B custom header + SQLCipher4) with a raw hex key,
tolerating damaged pages (rowid-cursor paging, shrink batch, skip single bad rows).
Adapted from QQBackup/nt_msg_db_util 1.decrypt.py for x'hex' raw-key mode.

Usage: python qq_decrypt_hex.py <key_hex> [src.db] [out_plain.db]
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
import re
import sqlite3
import pathlib
import sys
import json
import datetime as dt

import sqlcipher3.dbapi2 as sc

KEY_HEX = sys.argv[1]
SRC = sys.argv[2] if len(sys.argv) > 2 else os.path.join(QQ_DATA_DIR, SELF_QQ, "nt_qq", "nt_db", "nt_msg.db")
OUT = sys.argv[3] if len(sys.argv) > 3 else r"工作区的上级\out\qq\nt_msg_plain.db"
HEADER_SIZE = 1024


def clear_candidates(src: pathlib.Path, dst: pathlib.Path):
    """中间产物 `*_clear.db` 的候选位置，按优先级排。

    历史行为是 `src.with_name(src.stem + "_clear.db")`，即写在**源库旁边**。
    2026-09-13 主 Agent 的沙箱边界变成 workspace-write（只有 工作区 可写）后，
    源库目录（`C:\\Users\\...\\Tencent Files\\...\\nt_db`）只读 → `open(dst,'wb')` 抛
    `PermissionError: [Errno 13] Permission denied`，整步 FAILED。
    所以：**优先放输出目录旁边**（一定在工作区内），源库旁边只作回退。
    注意：源码里那个旧的 `nt_msg_clear.db` 现在已经**写不动**，所以判据必须是"能写"，
    不能只看"存在"。
    """
    return [
        dst.with_name(dst.stem + "_clear.db"),   # 工作区内：output/qq/nt_msg_clear.db
        src.with_name(src.stem + "_clear.db"),   # 旧行为：源库旁边（通常只读）
    ]


def pick_writable(cands, expected: int):
    """选出可写（或已有且大小正好）的候选；都没有就返回 None。"""
    for cand in cands:
        if cand.exists() and cand.stat().st_size == expected:
            return cand                          # 已完整，无需再写
    for cand in cands:
        try:
            cand.parent.mkdir(parents=True, exist_ok=True)
            probe = cand.with_suffix(cand.suffix + ".wtest")
            with open(probe, "wb") as fh:
                fh.write(b"")
            os.remove(probe)
            return cand
        except OSError:
            continue
    return None


def strip_header(src: pathlib.Path, dst: pathlib.Path) -> None:
    """去掉 1024 字节自定义头，把 payload 写到 dst。

    **A03 修复（2026-09-20 审计 P06）**：旧版只比 `st_size` 就 `[skip]`。
    SQLite 原地更新（VACUUM、页内改写、WAL 落盘）**不保证文件变大**，
    于是"源库已变、缓存大小恰好相同"时永远读旧内容 —— 实测用同长度不同内容的
    源/缓存复现。现在**同尺寸也要逐块比内容**：一样才跳过（并把 dst 的 mtime
    顶新，供 daily_prep 的新鲜度自检），不一样就重写。
    只用内建与 pathlib：本函数被审计探针单独 exec，作用域里没有 os/hashlib。
    """
    expected = src.stat().st_size - HEADER_SIZE
    if dst.exists() and dst.stat().st_size == expected:
        same = True
        with open(src, "rb") as f, open(dst, "rb") as g:
            f.seek(HEADER_SIZE)
            while True:
                a = f.read(8 << 20)
                b = g.read(8 << 20)
                if a != b:
                    same = False
                    break
                if not a:
                    break
        if same:
            print("[skip] clear file exists, content identical")
            try:
                dst.touch()
            except OSError:
                pass
            return
        print("[refresh] clear file size matches but content differs -> rewrite")
    with open(src, "rb") as f:
        f.seek(HEADER_SIZE)
        with open(dst, "wb") as out:
            while chunk := f.read(64 << 20):
                out.write(chunk)
    print("[1] stripped header ->", dst, dst.stat().st_size, "bytes")


def open_enc(path: pathlib.Path):
    conn = sc.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA cipher_page_size = 4096;")
    conn.execute("PRAGMA key = \"x'%s'\";" % KEY_HEX)
    conn.execute("PRAGMA kdf_iter = 4000;")
    conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
    conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;")
    conn.execute("SELECT count(*) FROM sqlite_master;").fetchone()  # triggers real decrypt
    return conn


def export_table(enc_path: pathlib.Path, plain: sqlite3.Connection, table: str):
    enc = open_enc(enc_path)
    try:
        ddl = enc.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()[0]
    except Exception as e:
        print("  !! cannot read DDL for", table, e)
        return 0, 0
    ddl_safe = re.sub(
        r"^CREATE\s+TABLE\s+", "CREATE TABLE IF NOT EXISTS ", ddl, flags=re.I
    )
    plain.execute(ddl_safe)
    plain.commit()
    ncols = len(enc.execute('PRAGMA table_info("%s")' % table).fetchall())
    ph = ",".join("?" * ncols)
    last = plain.execute('SELECT max(rowid) FROM "%s"' % table).fetchone()[0] or 0
    batch = 5000
    total = 0
    skipped = 0
    guard = 0
    while True:
        guard += 1
        if guard > 10_000_000:
            print("  !! guard hit, abort table", table)
            break
        try:
            rows = enc.execute(
                'SELECT rowid,* FROM "%s" WHERE rowid > ? ORDER BY rowid LIMIT ?' % table,
                (last, batch),
            ).fetchall()
        except Exception:
            try:
                enc.close()
            except Exception:
                pass
            if batch > 1:
                batch //= 2
                enc = open_enc(enc_path)
                continue
            enc = open_enc(enc_path)
            last += 1
            skipped += 1
            continue
        if not rows:
            break
        for r in rows:
            rid = r[0]
            try:
                plain.execute('INSERT OR IGNORE INTO "%s" VALUES (%s)' % (table, ph), r[1:])
                total += 1
            except Exception:
                skipped += 1
            last = rid
        plain.commit()
        if len(rows) < batch:
            break
    try:
        enc.close()
    except Exception:
        pass
    return total, skipped


def main():
    if len(sys.argv) < 2:
        print("usage: qq_decrypt_hex.py <key_hex> [src] [out]")
        sys.exit(2)
    src = pathlib.Path(SRC)
    if not src.exists():
        print("src not found:", src)
        sys.exit(3)
    cands = clear_candidates(src, pathlib.Path(OUT))
    expected = src.stat().st_size - HEADER_SIZE
    clear = pick_writable(cands, expected)
    if clear is None:
        print("[x] 没有可写位置放中间产物 *_clear.db，候选：")
        for c in cands:
            print("      -", c)
        print("    （源库旁边只读；工作区 %s 应可写，请检查路径）" % OUT)
        sys.exit(4)
    print("[0] clear file ->", clear)
    strip_header(src, clear)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    plain = sqlite3.connect(OUT)
    ver = {}
    try:
        probe = open_enc(clear)
        tables = [r[0] for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        probe.close()
        print("[2] key OK, tables:", tables)
        for t in tables:
            if t.startswith("sqlite_"):
                continue
            n, s = export_table(clear, plain, t)
            print("  %-24s %8d rows  %d skipped" % (t, n, s))
        # A03 验收：记录采集源版本（源库大小/mtime + 各表最大 rowid），
        # 让"这次快照到底取自哪个源版本"可核对 —— 同尺寸改写也能看出源已变。
        ver = {"src": str(src), "src_size": src.stat().st_size,
               "src_mtime": src.stat().st_mtime, "clear_size": clear.stat().st_size,
               "clear_mtime": clear.stat().st_mtime,
               "tables": {t: (plain.execute('SELECT max(rowid) FROM "%s"' % t).fetchone()[0] or 0)
                          for t in tables if not t.startswith("sqlite_")},
               "at": dt.datetime.now().isoformat(timespec="seconds")}
    finally:
        plain.commit()
        plain.close()
    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(os.path.join(os.path.dirname(OUT), "_source_version.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(ver, fh, ensure_ascii=False, indent=1)
    except OSError as e:
        print("  !! 源版本台账写失败:", e)
    print("[3] done ->", OUT)


if __name__ == "__main__":
    main()