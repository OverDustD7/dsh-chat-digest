# -*- coding: utf-8 -*-
"""Invoke a locally supplied QQ raw-key adapter with the existing pipeline CLI."""
import os
import runpy
import sys

sys.dont_write_bytecode = True
from pconf import C, ensure_utf8_stdio, external_tool, out_dir


def main():
    if not 2 <= len(sys.argv) <= 4:
        raise SystemExit("usage: qq_decrypt_hex.py <key_hex> [src] [out]")
    ensure_utf8_stdio()
    adapter = external_tool("nt_msg_db_util", "qq_decrypt_hex.py", required_file=True)
    if len(sys.argv) < 3:
        source = os.path.join(C.req("qq_data_dir"), C.req("self_qq"), "nt_qq", "nt_db", "nt_msg.db")
        sys.argv.append(source)
    if len(sys.argv) < 4:
        sys.argv.append(os.path.join(out_dir(), "qq", "nt_msg_plain.db"))
    runpy.run_path(adapter, run_name="__main__")


if __name__ == "__main__":
    main()
