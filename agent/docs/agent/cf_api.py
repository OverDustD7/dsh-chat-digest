"""chat-feed 插件 HTTP 客户端（本机回环，自带签名 cookie）。

为什么需要它：`/chat-feed/api/*` 在认证闸门后面，裸请求恒 401。
签名密钥是 DSH Home 里 `client-connection/browser-session` 的 grant 记录
（`$DSH_HOME/.credentials.yaml`，实测可读），cookie 算法见
`dsh-client-connection/lib/index.js`（encodeCookie / cookieName / signature）。

用法（只读）：
    python cf_api.py state
    python cf_api.py get /chat-feed/api/panel
    python cf_api.py get panel                （简写，自动补 /chat-feed/api/）
写入：
    python cf_api.py post items <json文件>
    python cf_api.py post item '{"action":"toggle","id":"I5"}'
    python cf_api.py post quote '{"id":"I5","no":"I5","text":"..."}'
    python cf_api.py post quote '{"clear":true}'
    python cf_api.py post collect '{"from":...,"to":...}'
    python cf_api.py post set-auto '{"auto":false}'
通用选项：
    --out <文件>   完整响应体（UTF-8）写到这个文件；默认 output\\logs\\_last_http.json
不打印任何密钥。
为什么每次都落盘：响应体里的中文在 pwsh 控制台（cp936）必然花屏，
所以完整响应一律写进 output\\logs\\_last_http.json，终端只打一行纯 ASCII 摘要；
要看中文全文就用 read 工具读那个文件 —— 不要凭控制台输出下结论。
"""
import base64
import hashlib
import hmac
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DSH_HOME = os.environ.get("DSH_HOME") or os.path.expanduser("~/.dsh")
CRED = os.path.join(DSH_HOME, ".credentials.yaml")
BASE = os.environ.get("DSH_CHAT_FEED_BASE_URL", "http://127.0.0.1:3080").rstrip("/")
_base_url = urllib.parse.urlsplit(BASE)
if _base_url.scheme != "http" or _base_url.hostname not in ("127.0.0.1", "localhost", "::1"):
    raise RuntimeError("DSH_CHAT_FEED_BASE_URL 必须是本机 HTTP 回环地址")
AUTHORITY = _base_url.netloc
COOKIE_PREFIX = "dsh-auth-"
RECORD_KEY = "client-connection/browser-session"

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(HERE))  # docs\agent -> docs -> 工作区根
PROFILE = os.path.realpath(os.environ.get("DSH_CHAT_FEED_LOCAL") or os.path.join(DSH_HOME, "dsh-chat-digest"))
DEFAULT_OUT = os.path.join(PROFILE, "output", "logs", "_last_http.json")


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def load_secret() -> bytes:
    text = io.open(CRED, encoding="utf-8").read()
    at = text.index(RECORD_KEY)
    m = re.search(r"secret:\s*\"?([A-Za-z0-9_-]+)\"?", text[at:])
    if not m:
        raise SystemExit("credentials: browser-session secret not found")
    value = m.group(1)
    pad = "=" * (-len(value) % 4)
    secret = base64.urlsafe_b64decode(value + pad)
    if len(secret) != 32:
        raise SystemExit("credentials: unexpected secret length %d" % len(secret))
    return secret


def cookie_header() -> str:
    secret = load_secret()
    now_ms = int(time.time() * 1000)
    payload = {
        "version": 1,
        "authority": AUTHORITY,
        "issuedAt": now_ms,
        "expiresAt": now_ms + 30 * 86400 * 1000,
    }
    body = b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = b64u(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
    name = COOKIE_PREFIX + b64u(hashlib.sha256(AUTHORITY.encode("ascii")).digest())
    return "%s=v1.%s.%s" % (name, body, sig)


def call(method: str, path: str, payload=None, tries: int = 1, note_retry=True):
    """发一次请求；`tries>1` 时对**传输层失败**重试。

    为什么要重试（2026-09-15 实测）：连发多次请求时偶发一次拿不到响应（`status=None`），
    同一秒重跑就正常 —— 它会让上层误报"插件没加载新 body / 面板没写进去"。
    这是**面板回写的唯一通道**，所以 CLI 默认给幂等接口带上重试。

    **哪些能重试**：`state` / `get` / `items`（整表替换，天然幂等）/ `quote` / `collect` / `set-auto`。
    **哪些绝不能**：`/item`（toggle / clear-done 是**取反**语义，重试可能双击）→ `tries=1`。
    只在"连 HTTP 响应都没拿到"或 5xx 时重试；4xx 是确定性拒绝，重试没意义。
    """
    last = (None, "")
    for attempt in range(max(1, tries)):
        url = BASE + path
        data = None
        headers = {"Cookie": cookie_header(), "Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = (e.code, e.read().decode("utf-8", "replace"))
            if e.code < 500:
                return last          # 4xx：确定性拒绝，重试无意义
        except Exception as e:  # noqa: BLE001
            last = (None, "%s: %s" % (type(e).__name__, e))
        if attempt + 1 < max(1, tries) and note_retry:
            # 原文一律打出来（stderr）：吞掉错误原文＝让上层自己制造结论
            sys.stderr.write("[cf_api] %s %s 失败（%r），重试 %d/%d\n"
                             % (method, path, last[1][:160], attempt + 2, tries))
    return last


def write_out(path, body):
    """完整响应体落盘（UTF-8），返回回执字符串。"""
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        return path
    except Exception as e:  # noqa: BLE001
        return "SAVE-FAILED(%s: %s)" % (type(e).__name__, e)


# 落盘前遮掉凭据：authUrl 是能直接换出 cookie 的一次性凭据，不该进日志文件。
SECRET_KEYS = ("authUrl", "secret", "token", "password")


def redact(body):
    """把响应体里的凭据字段替换成占位串（仍是合法 JSON，可继续读）。"""
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        return body
    if not isinstance(data, dict):
        return body
    changed = False
    for key in list(data.keys()):
        if key in SECRET_KEYS and data[key]:
            data[key] = "<redacted:%d chars>" % len(str(data[key]))
            changed = True
    if not changed:
        return body
    return json.dumps(data, ensure_ascii=False, indent=1)


def ascii_val(val, limit=40):
    """摘要里的值一律压成纯 ASCII（中文转 \\uXXXX），否则控制台照样花屏。"""
    if not isinstance(val, str):
        return val
    if not all(ord(ch) < 128 for ch in val):
        val = val.encode("ascii", "backslashreplace").decode("ascii")
    if len(val) > limit:
        val = val[:limit] + "..."
    return val


def digest(body):
    """一行纯 ASCII 摘要：控制台（cp936）不花屏，关键数值一眼可见。"""
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        return "non-json %d bytes" % len(body)
    if not isinstance(data, dict):
        return "json %s len=%d" % (type(data).__name__, len(data))
    bits = []
    for key in ("ok", "error", "count", "persist", "busy", "collectDay",
                "auto", "autoTime", "err", "fallback", "source", "lastError",
                "routeError", "saveOk", "quoteNo", "itemCount"):
        if key in data:
            bits.append("%s=%s" % (key, ascii_val(data[key])))
    items = data.get("items")
    if isinstance(items, list):
        bits.append("items=%d" % len(items))
        bits.append("done=%d" % sum(1 for i in items if isinstance(i, dict) and i.get("done")))
        bits.append("isNew=%d" % sum(1 for i in items if isinstance(i, dict) and i.get("isNew")))
        ids = [str(i.get("id")) for i in items if isinstance(i, dict)]
        bits.append("ids=%s%s" % (",".join(ids[:8]), "..." if len(ids) > 8 else ""))
    # 面板结构：既认 /api/panel 的顶层 sections，也认 /state 里的嵌套 panel
    for label, node in (("", data), ("panel.", data.get("panel") if isinstance(data.get("panel"), dict) else {})):
        secs = node.get("sections")
        if isinstance(secs, list):
            bits.append("%ssections=%d" % (label, len(secs)))
            counts = ",".join("%s:%s" % (s.get("id"), s.get("count")) for s in secs if isinstance(s, dict))
            if counts:
                bits.append("%scount[%s]" % (label, counts))
        unknown = node.get("unknownKinds")
        if isinstance(unknown, list):
            bits.append("%sunknown=%d" % (label, len(unknown)))
    return " ".join(bits) if bits else "keys=" + ",".join(sorted(data.keys())[:14])


def parse_payload(arg):
    """容错解析负载：pwsh 把内层双引号吃掉，所以也接受单引号 JSON。"""
    try:
        return json.loads(arg)
    except ValueError:
        pass
    fixed = re.sub(r"'([^']*)'", r'"\1"', arg)
    try:
        return json.loads(fixed)
    except ValueError as e:
        raise SystemExit(
            "payload not valid JSON (%s).\n"
            "pwsh eats inner double quotes when passing args; use single-quote JSON\n"
            "like {'action':'toggle','id':'I5'}, or pass a .json file path." % e)


def main(argv):
    argv = list(argv[1:])
    out = DEFAULT_OUT
    if "--out" in argv:
        i = argv.index("--out")
        if i + 1 >= len(argv):
            print("--out needs a file path")
            return 2
        out = argv[i + 1]
        del argv[i:i + 2]
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    # CLI 的默认重试：幂等接口 3 次，`/item` 1 次（toggle/clear-done 是取反语义，重试＝双击）。
    # 见 call() 的 docstring：偶发拿不到响应会让上层误判"没写进去"。
    READ_TRIES = 3
    if cmd == "state":
        # `state --slim`：**瘦身视图**（2026-09-15 成本审计）。整表 39 条的正文 ≈47 KB（≈2.3 万 token），
        # 而每轮要读好几次；瘦身后只给 id/kind/urgency/done/isNew/date + 首行 60 字 ≈9 KB（省约 80%）。
        # 不带 `--slim` 仍是全量（向后兼容）；**要正文才读全量**。
        path = "/chat-feed/api/state"
        if "--slim" in argv:
            path += "?slim=1"
        status, body = call("GET", path, tries=READ_TRIES)
    elif cmd == "patch":
        # `patch <json 或文件>` → POST /items-patch：**按 id 打补丁**，不必整表回写。
        # 未提供的字段原样保留（漏传 done 不会抹掉用户勾选）；响应回显 added/changed/dropped/done/isNew。
        if len(argv) < 2:
            print("patch needs a payload, e.g. patch \"{'upsert':[{'id':'x','text':'…'}]}\"")
            return 2
        arg = argv[1]
        if arg.startswith("{"):
            payload = parse_payload(arg)
        else:
            with io.open(arg, encoding="utf-8") as fh:
                payload = json.load(fh)
        status, body = call("POST", "/chat-feed/api/items-patch", payload, tries=READ_TRIES)
    elif cmd == "get":
        if len(argv) < 2:
            print("get needs a path, e.g. get panel")
            return 2
        path = argv[1]
        if not path.startswith("/"):
            path = "/chat-feed/api/" + path
        status, body = call("GET", path, tries=READ_TRIES)
    elif cmd == "post":
        if len(argv) < 2:
            print("post needs a target: items / item / quote / collect / set-auto")
            return 2
        target = argv[1]
        arg = argv[2] if len(argv) > 2 else "{}"
        if arg.startswith("{"):
            payload = parse_payload(arg)
        else:
            with io.open(arg, encoding="utf-8") as fh:
                payload = json.load(fh)
        if isinstance(payload, list):
            payload = {"items": payload}
        # **只有真正幂等的才重试**（2026-09-15 晚收紧：原来是"黑名单排除 /item"，太危险）：
        #   · items  = 整表替换 → 幂等
        #   · quote / set-auto → 幂等
        #   · collect **仅当带 at/dry** → 只拨指针/只看不改，幂等；
        #     不带参数的 collect 会**触发一轮**，重试＝触发两轮（虽然 busy 会挡，但不该赌）
        #   · item(toggle/clear-done 取反)、rotate(建新会话)、say/ss(灌消息) → **一律 1 次**
        idem = target in ("items", "quote", "set-auto") or (
            target == "collect" and isinstance(payload, dict) and ("at" in payload or payload.get("dry")))
        status, body = call("POST", "/chat-feed/api/" + target, payload, tries=READ_TRIES if idem else 1)
    else:
        print("unknown command", cmd)
        return 2
    saved = write_out(out, redact(body))
    print("HTTP %s  %s" % (status, digest(body)))
    if all(ord(ch) < 128 for ch in body):
        print(body[:4000])
    else:
        print("body has non-ASCII -> read it with the read tool: %s" % saved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
