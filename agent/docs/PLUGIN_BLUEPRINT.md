# 插件蓝图：把聊天数据管道做成 DSH 插件（2026-09-12 起草）

> 目的：本文件把**已验证可用的整套流程、数据结构、字段语义、坑与约束**整理成一份可直接照着写插件的规格书。
> 现状：全部能力已由 `scripts\` 下的 Python/Node 脚本验证可用（端到端 9/9 通过）；尚未封装成 Cordis 插件。
> 相关：`docs\README.md`（总览）· `docs\guidelines.md`（17 条原则）· `docs\output_format.md`（输出规范）· `docs\knowledge\lessons.md`（34 条经验/坑）

---

## 一、插件应提供的用户能力（面向最终目标）

| 能力 | 说明 | 现状 |
|---|---|---|
| **每日总结** | 一条命令/一次点击 → 当天主稿（结构见 `output_format.md`「主稿结构」＝**一、待办 + 二、有用信息 2.1–2.4**；图片与文件融入正文） | 脚本已通（`daily_prep.py` + 子代理任务书） |
| **历史按天总结** | 指定某天 → 同格式产出（历史日不列已过期待办） | 脚本已通（`extract_day.py` + `day_brief.py`） |
| **资源检索** | "群里发过哪些教材/资料/链接" → 带可操作链接与可访问性 | 已通（`resources.md` 38 条 + 链接验证） |
| **文件审查** | 已下载→读取+总结；未下载→标题+上下文推测+是否推荐下载 | 规则已定（原则 17），待做 |
| **实时提醒**（用户预告） | 只推"未过期且紧急"的，弹窗形式 | 未做（原则 11） |

---

## 二、数据层（插件的最小依赖）

### 2.1 微信（Weixin 4.1.13）
- 数据根：`E:\Documents\xwechat_files\<wxid>_<suffix>\`
- 库：`db_storage\message\message_0..4.db`（**今天的新消息主要在 message_0**）、`contact.db`、`session.db`、`general.db`
- 解密：`scripts\wx_decrypt3.py <key>`（key = 内存掩码 ⊕ Weixin.dll 内部密钥；本机 key 见 `docs\README.md`）
  - 页面 4096、`PRAGMA key="x'<hex>'"`、kdf_iter=256000、HMAC_SHA512（**必须用 WeChatDataAnalysis 的纯 Python 解密器**，sqlcipher3 直开会 HMAC 失败）
- 消息表：`Msg_<md5(username)>`；列：`local_id / server_id / local_type / real_sender_id / create_time / message_content / compress_content / WCDB_CT_message_content`
  - 内容解码：明文 / hex+zstd（magic `28 b5 2f fd`）/ base64
- 名称：`contact.username/remark/nick_name`；`contact.extra_buffer`（protobuf，**免打扰不可靠**）

### 2.2 QQ（NT 9.9）
- 数据根：`C:\Users\<user>\Documents\Tencent Files\<QQ>\nt_qq\`
- 库：`nt_db\nt_msg.db`（消息，**1024 字节自定义头 + SQLCipher raw key**）、`group_info.db`、`file_assistant.db`、`profile_info.db`、`rich_media.db`、`settings.db`、`misc.db`
- 解密：`scripts\qq_decrypt_hex.py <key> <src> <out>`（strip 1024 头 → raw key）
  - **多库多 key**：`agent\qq_dump_db\key_map.json` 的**键 = db 文件偏移 1024 处的 16 字节 hex**，值 = 该库 key → 见 `scripts\diag_keymap_decrypt.py`
- 结构化导出：`agent\nt_msg_db_util\3.export.py --src <plain> --dst <export>` → 表 `group_messages` / `c2c_messages`
  - **非文本消息 `text` 为空**，真内容在 `content`（JSON）→ 必须过 `qq_content_summary()`（在 `extract_window.py` 里）
- 原始表列：`40001`=msg_id、`40002`=seq、`40010`=会话类型、`40021`=群号/peer、`40058`=时间戳、`40080`=文本…
- **文件助手**（`file_assistant.db` → `file_assistant_v2`）：`200002`=文件名、`200005`=大小、`200001`=file_uuid、`200011/200014`=本地路径、`200013`=过期时间、`60001`=群号

### 2.3 媒体
- 微信图片容器：`msg\attach\<md5(chat)>\YYYY-MM\{Img\*.dat | Rec\<msgid>\Img\<N>}`（V2 容器：15B 头 `<6sLLx>` + AES-ECB + 尾部 XOR；密钥由 **kvcomm code** 派生：`aes=md5(code+wxid)[:16]`、`xor=code&0xFF`）
- **wxgf**（微信动图/原图，HEVC 封装）：用 **PyAV** 解码（`scripts\wxgf_decode.py`）；**匹配用原始字节 md5、显示用转码 jpg**
- 微信文件：`msg\file\YYYY-MM\<原文件名>`（明文，自动下载）；少量历史在 `attach\...\Rec\...\F\0\`
- QQ 媒体：`nt_data\{Pic|File|Video|Ptt|Emoji}\...`（**文件本体常未下载**，只有 Thumb）

---

## 三、分析层（判定逻辑，务必按此实现）

1. **图片锚定**：① 解密内容 md5 == 消息 XML `md5`（conf 1.0）② 解密 `_t` 字节数 == 消息 `cdnthumblength`（conf 0.8）③ 时间推定（标注推定）
2. **免打扰**：本地字段**不可靠**（field11/field12 都被推翻）→ 用**人工确认清单** `docs\knowledge\channels.md`
3. **"用户可能没看"的替代信号**：发言占比（0% 优先）、未读数、群性质（水群/通知群）
4. **水群候选筛选**（`qq_filter.py`）：长文本(≥40) / 含 URL / 关键词 / @所有人 / 文件；**同内容去重**
5. **时效**：作用＝"提醒当时去做某事"且时间已过 → 不进待办（只存档）
6. **已知度**：自己发的/自己问来的/亲历家常 = 已知；对方单方发来的 = 未知候选；涉及别人 = 需核对

---

## 四、输出层（**结构一律以 `output_format.md` 的「主稿结构」为唯一口径**）

```
一、待办（🔴 今天 / 🟡 本周 / ⚪ 更远；空档不写）
二、有用信息（2.1 官方 / 2.2 同学与群里的经验·标"听说/个例" / 2.3 资源与工具 / 2.4 生活与办事；空类不写）
```
> 旧口径（"三栏""五栏"、15–25K、≤8K）均已废止；本文件只留指针，规则正文只在 `output_format.md`。
- 资源型信息**必须给可操作链接**（上下文 → 搜索 → 如实报告未找到）
- 图片用 ``<img src="../output/window/images/<会话>/<文件>.jpg" width="480" alt="说明">`` 嵌入；文件给可点击路径
- 限长：交付稿 **6K–12K 字符**（**少而深**：一天 5–10 条）；附 debug 日志 ≤3K

---

## 五、插件形态建议（Cordis）

| 部分 | 归属 | 说明 |
|---|---|---|
| `chatdata` Service | **Host** | 封装：解密、按天/窗口读取、图片/文件索引、链接验证；对上暴露只读方法 |
| Tools | Host | `chat_summary(day)`、`chat_day_extract(day)`、`chat_files_review()`、`chat_resources()` |
| 定时任务 | Host | 每日固定时间跑 `daily_prep` + 触发总结（原则 11 的"总结模式"） |
| 实时提醒 | Host+Client | 轮询新消息 → 命中"紧急且未过期" → Client Slot 弹窗（原则 11 的"实时模式"） |
| 经验库读写 | Host | 提炼后写回 `knowledge/*.md`（原则 12） |

**硬约束（写插件时不可违反）**
- 全流程**避免宿主插件调用**（不用 `browser_*`/`web_fetch`）；**记忆插件除外**
- 一律本机自研（Python/Node）；中文用 Python 读写；不用内联 `python -c` 跑含正则的代码
- 只读用户数据；**不自行删除任何文件**（只出建议清单）
- epoch 计算用 Python 显式时区（禁用 PowerShell `-UFormat %s`）
- 抓微信文章用 `node scripts\fetch_article.mjs`（云端抓取会被反爬拦截）

---

## 六、当前未完成 / 未来要做的

1. **QQ 文件本体下载**：不可自研（私有协议 + 登录态）→ 需客户端下载一次；插件里做"清单展示 + 一键提示"
2. **wxgf 已解决**（PyAV），但**微信视频/语音**（silk 解码、ASR）仍未做
3. **图片语义**：目前靠 `read_image` 逐张读；量大时可考虑本地视觉模型（用户已装 Ollama，可跑本地多模态）
4. **结构化记忆**：把"每日提炼"结果自动沉淀到 `knowledge/`（人物/群档案/经验）——已定规则，待自动化
5. **UI**：主稿目前是 Markdown 文件；插件可做成 Client Slot 面板（列表 + 嵌图 + 链接可点）

> **关于文中出现的"找不到的脚本"（2026-09-14 审计后加）**
> 本文档里形如 `_diag_*.py` / `fix_*.py` / `patch_*.py` / `_*.mjs` / `wx_key_driver*.py` 的名字，
> 绝大多数是**当轮排障用的一次性脚本**（用完即清，不进仓库），**按名找不到是正常的，不是缺失**。
> 另有个别是**动态插件时代**的工具（如 `dump-defines.mjs` / `extract-define.mjs`）——
> chat-feed 2026-09-14 已改为**常驻 profile bundle**，这两个的定义/导出需求随之消失，**不必再找**。
> 判据：**权威可执行清单**＝`scripts/daily_prep.py` 里 `run(...)` 的调用（步数以 `prep_report.md` 行数为准；
> 别在本文件里再抄数字，查数字是否腐烂跑 `python tools\check_step_count.py`），
> 以及 `docs/INDEX.md` 的文件地图。这两个以外的脚本名，按"历史遗迹"对待。
> 复核工具：`python tools\audit_refs.py`（扫全部权威文档 → `output/window/_refs_audit.md`）。
