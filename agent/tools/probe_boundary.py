"""A 线第一步 · 写边界自证（2026-09-13 迁移后）。

用法：python tools\\probe_boundary.py
行为：
  1) 读回 output\\_probe_after_migration.txt 并打印（预期成功）；
  2) 试写 D:\\Project\\DSH\\chat-feed\\_probe_should_fail.txt（预期被拒，打印原始异常）。
只做这两件事，不删任何文件。
"""
import io
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSIDE = os.path.join(ROOT, "output", "_probe_after_migration.txt")
OUTSIDE = r"D:\Project\DSH\chat-feed\_probe_should_fail.txt"

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
except Exception:  # noqa: BLE001
    pass


def main():
    print("== 1) 树内读回：%s ==" % INSIDE)
    try:
        text = io.open(INSIDE, encoding="utf-8").read()
        print("OK  读到 %d 字符：" % len(text))
        print(text.rstrip())
    except Exception:  # noqa: BLE001
        print("FAIL 读回失败：")
        traceback.print_exc()

    print("\n== 2) 树外试写：%s ==" % OUTSIDE)
    try:
        with io.open(OUTSIDE, "w", encoding="utf-8") as fh:
            fh.write("should not exist\n")
        print("!! 竟然写成功了 —— 与预期相反，立即停止并报告")
        return 1
    except Exception as exc:  # noqa: BLE001
        print("被拒（符合预期）：%s: %s" % (type(exc).__name__, exc))
        print("exists=", os.path.exists(OUTSIDE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
