# -*- coding: utf-8 -*-
"""read_session.py — 读 DSH 会话记录（`session.v3.jsonl.zstd`），用于看主 agent / 子代理到底在干什么。

用法:
    python tools\\read_session.py list                       # 列出有记录的会话（按改动时间）
    python tools\\read_session.py tail <会话id前缀> [条数]     # 打印最近 N 条事件（含工具调用）
    python tools\\read_session.py wscan <会话id前缀>          # 找"重复刷同一个字符"的退化输出
"""
import collections
import datetime as dt
import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DSH = os.path.join(os.environ.get("USERPROFILE", ""), ".dsh", "sessions")
TZ = dt.timezone(dt.timedelta(hours=8))

try:
    from compression import zstd as _zstd            # Python 3.14+
except Exception:  # noqa: BLE001
    try:
        import zstandard as _zstd                     # 第三方
    except Exception:  # noqa: BLE001
        _zstd = None


def load(path):
    raw = io.open(path, "rb").read()
    if _zstd is None:
        raise SystemExit("这个 Python 没有 zstd 支持（试 C:\\Python314\\python.exe）")
    if hasattr(_zstd, "decompress"):
        try:
            data = _zstd.decompress(raw)
        except Exception:  # noqa: BLE001
            d = _zstd.ZstdDecompressor()
            data = d.decompress(raw)
    else:
        d = _zstd.ZstdDecompressor()
        with d.stream_reader(io.BytesIO(raw)) as r:
            data = r.read()
    out = []
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                pass
    return out


def sessions():
    out = []
    for p in glob.glob(os.path.join(DSH, "*", "*", "session.v3.jsonl.zstd")):
        out.append((os.path.getmtime(p), p))
    return sorted(out)


def find(prefix):
    for _, p in sessions():
        if prefix in p:
            return p
    return None


def all_text(o, key_hint=()):
    """把事件里所有像"文本"的字符串收集起来（不依赖固定嵌套层级）。"""
    out = []
    if isinstance(o, str):
        if o.strip():
            out.append(o)
    elif isinstance(o, dict):
        for k, v in o.items():
            if k in ("text", "content", "delta", "message", "output"):
                out.extend(all_text(v))
            elif isinstance(v, (dict, list)) and k in ("data", "message", "content"):
                out.extend(all_text(v))
    elif isinstance(o, list):
        for v in o:
            out.extend(all_text(v))
    return out


def brief(ev):
    """把一条事件压成一行。"""
    if not isinstance(ev, dict):
        return repr(ev)[:100]
    t = ev.get("type") or ev.get("kind") or "?"
    d = ev.get("data") if isinstance(ev.get("data"), dict) else ev
    bits = []
    for k in ("role", "name", "toolName", "tool", "status", "state", "id", "callId"):
        if k in d:
            bits.append("%s=%s" % (k, str(d[k])[:24]))
    txt = ""
    for k in ("text", "content", "delta", "message", "output", "result"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            txt = v.replace("\n", " ⏎ ")
            break
        if isinstance(v, list):
            s = []
            for c in v:
                if isinstance(c, dict):
                    s.append(str(c.get("text") or c.get("name") or c.get("type") or "")[:60])
                else:
                    s.append(str(c)[:60])
            txt = " | ".join(x for x in s if x)
            if txt:
                break
    return "%-28s %s%s" % (t, " ".join(bits), ("  " + txt[:200]) if txt else "")


def main(argv):
    if len(argv) < 2 or argv[1] == "list":
        print("会话记录（按改动时间倒序）:")
        for m, p in reversed(sessions()[-25:]):
            print("  %s  %9d  %s" % (dt.datetime.fromtimestamp(m, TZ).strftime("%m-%d %H:%M:%S"),
                                     os.path.getsize(p), p.replace(DSH + os.sep, "")))
        return 0
    cmd = argv[1]
    prefix = argv[2] if len(argv) > 2 else ""
    p = find(prefix)
    if not p:
        print("没找到会话:", prefix)
        return 1
    evs = load(p)
    print("会话 %s ｜ %d 条事件 ｜ %s" % (prefix, len(evs), p.replace(DSH + os.sep, "")))
    if cmd == "tail":
        n = int(argv[3]) if len(argv) > 3 else 30
        for i, ev in enumerate(evs[-n:], len(evs) - n + 1):
            print("[%4d] %s" % (i, brief(ev)))
    elif cmd == "msgs":
        # 逐条打印 assistant/user 消息的**完整**文本（不截断），用于看退化输出
        n = int(argv[3]) if len(argv) > 3 else 40
        picked = [ev for ev in evs if ev.get("type") in ("assistant/message", "user/message")]
        for i, ev in enumerate(picked[-n:]):
            txt = " | ".join(all_text(ev.get("data") if isinstance(ev.get("data"), dict) else ev))
            print("[%3d] %-18s %6d 字  %s" % (i, ev.get("type"), len(txt),
                                              txt[:260].replace("\n", " ⏎ ")))
            if len(txt) > 260:
                print("        ...尾部: %s" % txt[-260:].replace("\n", " ⏎ "))
    elif cmd == "calls":
        # 列出所有工具调用：序号 / 工具名 / 参数摘要（派活类打印全文）
        full = set((argv[3] if len(argv) > 3 else "subagent,send_message").split(","))
        for i, ev in enumerate(evs):
            if ev.get("type") != "tool/call":
                continue
            d = ev.get("data") if isinstance(ev.get("data"), dict) else ev
            name = d.get("name") or d.get("toolName") or d.get("tool") or "?"
            args = d.get("input") or d.get("arguments") or d.get("args") or {}
            s = json.dumps(args, ensure_ascii=False)
            print("[%4d] %-18s %d 字" % (i, name, len(s)))
            if any(f and f in str(name) for f in full):
                print("        " + s.replace("\\n", "\n        "))
            else:
                print("        " + s[:220])
    elif cmd == "ev":
        # 打印指定序号的原始事件（完整），用于逐字检查派活原文
        for spec in argv[3:]:
            for part in str(spec).split(","):
                i = int(part)
                ev = evs[i]
                print("=" * 100)
                print("事件 [%d] type=%s" % (i, ev.get("type")))
                d = ev.get("data") if isinstance(ev.get("data"), dict) else ev
                args = d.get("input") or d.get("arguments") or d
                print(json.dumps(args, ensure_ascii=False, indent=2))
    elif cmd == "grep":
        # 在整份会话里找一段字面文本（用于核对 seed 进去的 prompt 是不是新的）
        needle = argv[3]
        n = 0
        for i, ev in enumerate(evs):
            s = json.dumps(ev, ensure_ascii=False)
            if needle in s:
                n += 1
                if n <= 4:
                    j = s.index(needle)
                    print("[%4d] %-18s …%s…" % (i, ev.get("type"),
                                                s[max(0, j - 60):j + 120].replace("\\n", " ⏎ ")))
        print("命中 %d 次" % n)
    elif cmd == "types":
        c = collections.Counter()
        for ev in evs:
            c[(ev.get("type") or "?")] += 1
        for k, v in c.most_common(40):
            print("  %-34s %d" % (k, v))
    elif cmd == "wscan":
        # 找"同一个字符反复刷"的退化输出
        bad = []
        for i, ev in enumerate(evs):
            s = json.dumps(ev, ensure_ascii=False)
            for ch in "WwXx.|-_=*#0 ":
                if s.count(ch) > 200 and len(s) > 300:
                    # 该字符是否占了绝大部分
                    if s.count(ch) / max(1, len(s)) > 0.6:
                        bad.append((i, ev.get("type"), ch, len(s), s[:160]))
                        break
        print("可疑退化事件 %d 条" % len(bad))
        for i, t, ch, ln, sample in bad[-12:]:
            print("  [%4d] %-22s 字符 %r ×%d / %d  %s" % (i, str(t), ch, ln - int(ln * 0.4), ln, sample))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
