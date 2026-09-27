# -*- coding: utf-8 -*-
"""sync-install.py — 把本仓库的**随包内容**逐字节同步进本机安装目录，并复核两边一致。

为什么需要它：宿主加载的是 `~/.dsh/profiles/web/node_modules/dsh-chat-digest/`（`dsh plugin add`
会**整体重建**那个目录），而开发在仓库里。两边一直靠手工拷贝同步 —— 手工拷贝漏过文件
（`prompt/` 整目录），也多拷过不该进包的目录（`tools/` 58.6 MB 含 26 MB 老抓取、`test/`）。
这个脚本把"该同步什么"写成**白名单**，把"两边是否一致"变成一条可跑的判据。

判据（三条都是实测踩过的）：
  · 只同步白名单：`lib pipeline prompt agent\\docs agent\\tools examples` + 根文件
  · **绝不进入 junction**：Python 的 `os.path.islink()` 对 junction 返回 **False**，必须看
    `st_reparse_tag == 2684354563` —— 那几个位置（`local`、`profile`、`agent\\output`、
    `agent\\docs\\{knowledge,archive}`）是私人 profile 的入口，走进去等于把私人数据当成包内容
    （此前扫出 22 万处"包内有私人值"的假阳性就是这么来的）
  · 跳过 `__pycache__` / `*.pyc` / `node_modules` / `.git`

用法：
  python tools/sync-install.py            # 干跑：只报差异，不动文件（rc=1 表示有差异）
  python tools/sync-install.py --apply    # 真同步（含删除安装侧多出的文件）
"""
import hashlib
import io
import os
import shutil
import stat
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOOLS = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(TOOLS)
DSH_HOME = os.environ.get("DSH_HOME") or os.path.join(os.environ.get("USERPROFILE", "C:"), ".dsh")
DST = os.environ.get("DSH_CHAT_DIGEST_INSTALL") or os.path.join(
    DSH_HOME, "profiles", "web", "node_modules", "dsh-chat-digest")

#: 随包内容白名单（与 package.json 的 files 对齐；`local`/`profile`/`agent/output` 永不进）
DIRS = ["lib", "pipeline", "prompt", os.path.join("agent", "docs"),
        os.path.join("agent", "tools"), "examples"]
FILES = ["package.json", "cordis.patch.yml", "LICENSE", "README.md", "README.zh.md",
         "README.i18n.yaml", "CHANGELOG.md"]
SKIP_DIR = {"__pycache__", "node_modules", ".git", ".vscode", ".idea"}
JUNCTION = 2684354563


def is_junction(path):
    """junction 在 Windows 上不是 symlink（`os.path.islink` 返回 False），只能看 reparse tag。"""
    try:
        return getattr(os.lstat(path), "st_reparse_tag", 0) == JUNCTION
    except OSError:
        return False


def walk(root):
    """白名单下的真实文件清单（相对 root）。junction 与跳过目录一律不进去。"""
    out = []
    for rel in DIRS:
        base = os.path.join(root, rel)
        if not os.path.isdir(base) or is_junction(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            if is_junction(dirpath):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIR and not is_junction(os.path.join(dirpath, d))]
            for name in filenames:
                if name.endswith(".pyc"):
                    continue
                full = os.path.join(dirpath, name)
                if is_junction(full) or not os.path.isfile(full):
                    continue
                out.append(os.path.relpath(full, root))
    for rel in FILES:
        full = os.path.join(root, rel)
        if os.path.isfile(full) and not is_junction(full):
            out.append(rel)
    return sorted(out)


def digest(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    apply_ = "--apply" in sys.argv[1:]
    print("仓库  %s" % PKG)
    print("安装  %s" % DST)
    if not os.path.isdir(DST):
        print("安装目录不存在 —— 先 dsh plugin add 装一次，或用 DSH_CHAT_DIGEST_INSTALL 指定")
        return 1
    src, dst = walk(PKG), walk(DST)
    src_set, dst_set = set(src), set(dst)
    missing = sorted(src_set - dst_set)          # 仓库有、安装没有
    extra = sorted(dst_set - src_set)            # 安装有、仓库没有（安装侧多出来的）
    diff = []
    for rel in sorted(src_set & dst_set):
        try:
            if digest(os.path.join(PKG, rel)) != digest(os.path.join(DST, rel)):
                diff.append(rel)
        except OSError as e:
            diff.append("%s (读失败 %s)" % (rel, e))
    print("文件数 仓库 %d ｜ 安装 %d" % (len(src), len(dst)))
    print("缺 %d ｜ 多 %d ｜ 内容不同 %d" % (len(missing), len(extra), len(diff)))
    for tag, items in (("缺", missing), ("多", extra), ("不同", diff)):
        for rel in items[:20]:
            print("  %s  %s" % (tag, rel))
        if len(items) > 20:
            print("  %s  … 另 %d 条" % (tag, len(items) - 20))
    if not (missing or extra or diff):
        print("两边一致（白名单范围内逐字节相同）")
        return 0
    if not apply_:
        print("\n干跑结束：加 --apply 才动文件")
        return 1
    for rel in missing + diff:
        s, d = os.path.join(PKG, rel), os.path.join(DST, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
    for rel in extra:
        d = os.path.join(DST, rel)
        # 再上一道保险：只删普通文件，且它得在白名单目录里
        if os.path.isfile(d) and not is_junction(d):
            os.remove(d)
    print("\n已同步 %d 个文件，删除 %d 个多余文件" % (len(missing) + len(diff), len(extra)))
    left = []
    src2, dst2 = set(walk(PKG)), set(walk(DST))
    for rel in sorted(src2 & dst2):
        if digest(os.path.join(PKG, rel)) != digest(os.path.join(DST, rel)):
            left.append(rel)
    if (src2 - dst2) or (dst2 - src2) or left:
        print("同步后仍不一致：缺 %d 多 %d 不同 %d" % (len(src2 - dst2), len(dst2 - src2), len(left)))
        return 1
    print("同步后：仓库 %d ｜ 安装 %d ｜ 0 处不一致" % (len(src2), len(dst2)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
