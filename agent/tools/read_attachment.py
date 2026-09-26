# -*- coding: utf-8 -*-
r"""read_attachment.py <YYYY-MM-DD> — 按当天附件索引**提取正文**（全量审计 A01 验收）。

用途
  把 output\days\<date>_files.json（由 scripts\find_attachments.py 产出）里判定为
  readable=="text" 的附件**真正读出来**，让 A01「PDF/Office/文本可读正文」这一条
  从"索引里写了能读"变成"确实读到了"。图片/音视频/压缩包/未知扩展名**明确不读**，
  并打印原因，保持 read_status=unread（A01 要求「音视频明确读取范围」）。

用法
  ..\venv\Scripts\python.exe tools\read_attachment.py 2026-09-17 --list
  ..\venv\Scripts\python.exe tools\read_attachment.py 2026-09-17 --index 3
  ..\venv\Scripts\python.exe tools\read_attachment.py 2026-09-17 --name 提问环节
  ..\venv\Scripts\python.exe tools\read_attachment.py 2026-09-17 --all-readable --max-chars 3000

  序号是 files 数组的 0 基下标（与 --list 打印的一致）。

  --list          每条一行：序号、found、ext、readable、read_status、标题、字节数
  --index N       选 0 基下标为 N 的那条
  --name S        按标题子串选；命中多条会全部列出来，请改用 --index
  --all-readable  把所有 readable=="text" 的条目都提取一遍（每条之间一行 =====）
  --max-chars N   每条**打印**的字符上限（默认 3000），超出打 "…[+N字被截断…]"

读取范围（与 scripts\find_attachments.py 的 readable_of 对齐）
  pdf                     → pypdf：PdfReader 逐页 extract_text()
  docx / pptx             → zipfile 解包读 word/document.xml、ppt/slides/slide*.xml，
                            正则去 XML 标签，</w:p>、</a:p> 等段落结束换行，再 html.unescape
  xlsx                    → openpyxl(read_only=True, data_only=True) 逐 sheet 逐行，
                            每格 \t 连接，每 sheet 最多 200 行，超出显式写 "…（还有 N 行）"
  txt/md/csv/json/xml/html → 直接读文本（先 utf-8，失败退 gbk，再失败 replace）
  image / av-unread / archive / unknown → **不读**，只打印"本线不读这个范围，原因是…"，
                            read_status 保持原值（绝不改成 read）

为什么不做音视频转写
  本线只负责"正文可读"这一段。音视频要出文字必须引入 ffmpeg + 语音模型（新依赖、新算力、
  新的出错面），而转写结果**没有聊天锚点**（时间轴对不回原文消息），进了条目也无法按
  tools\anchor_read.py 回原文核 —— 与"每条都要能回原文核"的线规冲突。所以这里对音视频/
  图片/压缩包**只明确标注范围**：readable 已由 find_attachments.py 标成 av-unread/image/
  archive/unknown，本工具保持 read_status=unread，绝不假装读过。

回写规则
  成功提取（且字符数 > 0）后：read_status="read"、read_chars=字符数、read_at=epoch 秒，
  然后**原地重写** output\days\<date>_files.json（ensure_ascii=False, indent=1, newline='\n'）。
  写之前先备份同名 .bak；若 .bak 已存在则**保留首次备份不动**（本工具不删除、不覆盖任何已有文件）。
  提取到 0 字符（多为扫描件/纯图 PDF）**不算读成功**，不改 read_status —— 不假装读到。

退出码
  0 成功（含"明确不读"的条目：范围已如实说明，不是失败）
  2 用法错 / 选条失败（--index 越界、--name 无命中或命中多条）
  3 索引文件不存在
  4 索引项 found=false 或路径已不存在
  5 提取到 0 字符
  6 扩展名不在本工具读取范围内（如 doc/xls/ppt 旧版二进制）
  7 提取抛异常（打印异常类型与消息）
  --all-readable 逐条不受单条失败影响，跑完打汇总行；只要有一条抛异常，整体退出码 7。
"""
import argparse
import html
import json
import os
import re
import shutil
import sys
import time
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # agent 根（＝包内 agent/ 或 <个人目录>）
DAYS = os.path.join(HERE, "output", "days")

#: 直接按文本读的扩展名（其余文本类走专门解析）
PLAIN_EXT = {"txt", "md", "csv", "json", "xml", "html", "htm"}

#: "本线不读"的原因（A01：音视频必须明确读取范围，不能含糊）
REFUSE_REASON = {
    "image": "图片正文走图片线（scripts\\day_images.py / vision_triage.py）读，本工具不读像素",
    "av-unread": "音视频本线不做转写（无 ffmpeg/语音模型依赖，且转写结果没有聊天锚点，无法回原文核）",
    "archive": "压缩包需先解包再按内部文件判，本工具不解包（解包会写出新文件）",
    "unknown": "扩展名不在可读范围内（exe/dll 等二进制），当不了正文读",
}

TAG_RE = re.compile(r"<[^>]+>")
SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")


class UnsupportedExt(Exception):
    """扩展名不在本工具的读取范围内。"""


# ---------------------------------------------------------------- 提取实现

def xml_to_text(xml):
    """Office 的 XML → 纯文本：段落结束换行、制表符还原、去标签、反转义。"""
    s = xml
    # 先按"段落/行/单元格"结束打换行，再统一去标签，否则段落会挤成一行
    for close in ("</w:p>", "</a:p>", "</w:tr>", "</a:tr>"):
        s = s.replace(close, "\n")
    s = re.sub(r"<w:tab[^>]*/>", "\t", s)
    s = re.sub(r"<a:tab[^>]*/>", "\t", s)
    s = re.sub(r"<w:br[^>]*/>", "\n", s)
    s = TAG_RE.sub("", s)
    s = html.unescape(s)
    return "\n".join(ln.strip() for ln in s.split("\n"))


def extract_pdf(path):
    """pypdf 逐页 extract_text()。加密 PDF 先试空口令，失败如实报错。"""
    from pypdf import PdfReader
    rd = PdfReader(path)
    if getattr(rd, "is_encrypted", False):
        try:
            rd.decrypt("")
        except Exception:
            pass
        if getattr(rd, "is_encrypted", False):
            raise RuntimeError("PDF 已加密且空口令打不开，无法提取正文")
    parts = []
    for i, pg in enumerate(rd.pages, 1):
        parts.append("----- 第 %d 页 -----" % i)
        parts.append(pg.extract_text() or "")
    return "\n".join(parts)


def extract_docx(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    return xml_to_text(xml)


def extract_pptx(path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if SLIDE_RE.match(n)]
        names.sort(key=lambda n: int(SLIDE_RE.match(n).group(1)))
        parts = []
        for n in names:
            parts.append("----- %s -----" % n)
            parts.append(xml_to_text(z.read(n).decode("utf-8", "replace")))
    return "\n".join(parts)


def extract_xlsx(path, row_limit=200):
    """逐 sheet 逐行；每 sheet 最多 row_limit 行，超出显式写 "…（还有 N 行）"。"""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts = []
    try:
        for ws in wb.worksheets:
            parts.append("----- sheet: %s -----" % ws.title)
            shown = 0
            extra = 0
            for row in ws.iter_rows(values_only=True):
                if shown < row_limit:
                    parts.append("\t".join("" if c is None else str(c) for c in row))
                    shown += 1
                else:
                    extra += 1          # 继续消费迭代器只为计数，不占内存
            if extra:
                parts.append("…（还有 %d 行）" % extra)
    finally:
        wb.close()
    return "\n".join(parts)


def extract_plain(path):
    """纯文本：先 utf-8，失败退 gbk（中文项目常见），再失败按 replace 读。"""
    raw = open(path, "rb").read()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def extract(path, ext):
    e = (ext or "").lower()
    if e == "pdf":
        return extract_pdf(path)
    if e == "docx":
        return extract_docx(path)
    if e == "pptx":
        return extract_pptx(path)
    if e == "xlsx":
        return extract_xlsx(path)
    if e in PLAIN_EXT:
        return extract_plain(path)
    raise UnsupportedExt(e)


# ---------------------------------------------------------------- 索引读写

def fmt_bytes(n):
    if not isinstance(n, int):
        return "-"
    if n < 1024:
        return "%dB" % n
    if n < 1024 * 1024:
        return "%.1fKB" % (n / 1024.0)
    return "%.1fMB" % (n / 1048576.0)


def load_index(date):
    """返回 (索引路径, 索引对象)；不存在返回 (路径, None)。"""
    p = os.path.join(DAYS, "%s_files.json" % date)
    if not os.path.exists(p):
        return p, None
    with open(p, encoding="utf-8") as f:
        return p, json.load(f)


def fmt_line(i, f):
    return "%3d  found=%-5s ext=%-4s readable=%-9s read_status=%-7s %8s  %s" % (
        i, str(f.get("found")), (f.get("ext") or "-"), (f.get("readable") or "-"),
        (f.get("read_status") or "-"), fmt_bytes(f.get("bytes")), f.get("title") or "(无标题)")


def save_index(path, obj):
    """备份（.bak，已存在则不动）后原地重写索引。不删除任何文件。"""
    bak = path + ".bak"
    if os.path.exists(bak):
        print("（备份 %s 已存在，保留首次备份不动）" % os.path.basename(bak))
    else:
        shutil.copyfile(path, bak)
        print("（已备份：%s）" % os.path.basename(bak))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    print("（已回写索引：%s）" % os.path.relpath(path, HERE))


def clip(s, n):
    """截断到 n 字符。返回 (正文, 被截掉的字数)。"""
    if not n or n <= 0 or len(s) <= n:
        return s, 0
    return s[:n], len(s) - n


def read_one(i, f, max_chars):
    """读一条并打印。返回 (退出码, 是否已成功提取需要回写)；退出码 0＝读成功。"""
    title = f.get("title") or "(无标题)"
    path = f.get("path")
    print("== 序号 %d ｜ %s ｜ %s ｜ %s ==" % (i, title, fmt_bytes(f.get("bytes")), path or "(无路径)"))

    if not f.get("found") or not path:
        print("索引项 found=false：本机没有这个文件，不提取（如实报没有，不猜）")
        return 4, False
    if not os.path.exists(path):
        print("路径已不存在：%s（文件可能被移动，按没有处理）" % path)
        return 4, False

    readable = f.get("readable") or "unknown"
    if readable != "text":
        # A01：音视频/图片等必须"明确读取范围"，这里只说明、不改 read_status
        print("本线不读这个范围，原因是：%s（readable=%s，read_status 保持 %s）"
              % (REFUSE_REASON.get(readable, "未知范围"), readable, f.get("read_status") or "-"))
        return 0, False

    ext = (f.get("ext") or "").lower()
    try:
        body = extract(path, ext)
    except UnsupportedExt:
        print("扩展名 %s 不在本工具读取范围内（doc/xls/ppt 旧版二进制需先转换），未提取" % ext)
        return 6, False
    except Exception as e:
        print("提取失败：%s: %s" % (type(e).__name__, e))
        return 7, False

    if not body.strip():
        print("提取到 0 字符：多为扫描件/纯图 PDF（需走图片线）；不算读成功，read_status 保持 %s"
              % (f.get("read_status") or "-"))
        return 5, False

    shown, cut = clip(body, max_chars)
    print(shown)
    if cut:
        print("…[+%d字被截断，用 --max-chars 放大]" % cut)

    f["read_status"] = "read"
    f["read_chars"] = len(body)
    f["read_at"] = int(time.time())
    return 0, True


def pick_by_name(files, sub):
    """按标题子串选；也允许命中命中路径的文件名。返回 (下标列表)。"""
    hits = [i for i, f in enumerate(files) if sub in (f.get("title") or "")]
    if not hits:
        hits = [i for i, f in enumerate(files) if sub in os.path.basename(f.get("path") or "")]
    return hits


def main():
    ap = argparse.ArgumentParser(description="按索引提取附件正文（A01）")
    ap.add_argument("date", help="YYYY-MM-DD")
    ap.add_argument("--list", action="store_true", help="列出索引里每条附件")
    ap.add_argument("--index", type=int, help="选 0 基下标为 N 的那条")
    ap.add_argument("--name", help="按标题子串选一条")
    ap.add_argument("--all-readable", action="store_true", help="提取所有 readable==text 的条目")
    ap.add_argument("--max-chars", type=int, default=3000, help="每条打印的字符上限（默认 3000）")
    a = ap.parse_args()

    ipath, obj = load_index(a.date)
    if obj is None:
        print("找不到索引：%s（先跑 scripts\\find_attachments.py %s）" % (ipath, a.date))
        return 3
    files = obj.get("files") or []

    if a.list:
        print("== %s ｜ %s ｜ 共 %d 条 ==" % (a.date, os.path.relpath(ipath, HERE), len(files)))
        for i, f in enumerate(files):
            print(fmt_line(i, f))
        return 0

    if a.all_readable:
        changed = False
        ok = bad = err = 0
        first = True
        for i, f in enumerate(files):
            if (f.get("readable") or "") != "text":
                continue
            if not first:
                print("=====")
            first = False
            code, ch = read_one(i, f, a.max_chars)
            changed = changed or ch
            if code == 0:
                ok += 1
            elif code in (4, 5, 6):
                bad += 1
            else:
                err += 1
        print("== 汇总：成功 %d ｜ 未成功 %d ｜ 异常 %d ==" % (ok, bad, err))
        if changed:
            save_index(ipath, obj)
        return 7 if err else 0

    if a.index is not None:
        if a.index < 0 or a.index >= len(files):
            print("--index %d 越界：本日共 %d 条（0..%d）" % (a.index, len(files), len(files) - 1))
            return 2
        sel = [a.index]
    elif a.name:
        sel = pick_by_name(files, a.name)
        if not sel:
            print("没有标题含「%s」的条目；用 --list 看全部" % a.name)
            return 2
        if len(sel) > 1:
            print("标题含「%s」的有 %d 条，请用 --index 指定：" % (a.name, len(sel)))
            for i in sel:
                print(fmt_line(i, files[i]))
            return 2
    else:
        print("请给 --list / --index N / --name 子串 / --all-readable 之一")
        return 2

    code, changed = read_one(sel[0], files[sel[0]], a.max_chars)
    if changed:
        save_index(ipath, obj)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
