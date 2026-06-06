---
name: wechat-decrypt
description: WeChat 4.x chat decrypt & query (macOS + Windows, both verified). Use when user asks about their WeChat messages, chats, contacts, or needs to re-extract the encryption key after WeChat update.
allowed-tools: Bash
---

# WeChat 4.x 聊天记录解密与查询（macOS + Windows）

## 首次加载自检（Agent 必须执行）

```bash
python3 -c "import platform; print(platform.system())"
claude mcp list 2>&1 | grep -q "wechat.*Connected" && echo "MCP_OK" || echo "MCP_MISSING"
test -f ~/.claude/skills/wechat-decrypt/key.txt && echo "KEY_OK" || echo "KEY_MISSING"
```

| 状态 | 行动 |
|------|------|
| `MCP_MISSING` | macOS `bash setup.sh` / Windows `powershell -File setup.ps1`，告知「重启 Claude Code」 |
| `KEY_MISSING` | 执行「密钥提取」对应平台流程（Windows 提 key 后还需 `python scripts\windows\decrypt_all.py` 解密全库到明文） |
| 全部 OK | 直接使用 MCP 工具 |

> Windows 自检用 `where python` + `test key_windows.txt` + 检查 `decrypted\` 是否有明文库；缺明文库即跑 `decrypt_all.py`。

不要跳过自检。

## Agent 触发规则

| 用户意图 | 行动 |
|----------|------|
| "看我微信" "最近聊天" "谁找我" "有什么消息" | MCP: `wechat_recent_messages` / `wechat_chat_summary` |
| "搜XX的聊天" "和XX提到" | MCP: `wechat_search_messages` |
| "列出会话" "有哪些群" | MCP: `wechat_list_chats` |
| "读和XX的聊天" | MCP: `wechat_read_chat` |
| "导出和XX的聊天" "导出XX到桌面" | 先做①模型检查（见下），再 `python3 scripts/common/export_chat.py <contact> --year YYYY [-o path]`（模型在则默认转写，`--no-transcribe` 可关） |
| "转写XX的语音" "语音转文字" "把语音导成文字" | `python3 scripts/common/export_chat.py <contact> --year YYYY --transcribe`，或单独 `python3 scripts/common/transcribe_db.py <contact> -o map.json` |
| "微信更新了" "重新破解" "密钥失效" | 执行下方「密钥提取」对应平台流程 |

### ① 导出前置——语音转写模型检查（默认执行）

导出/转写任何可能含语音的对话前，先查模型是否就位：

```bash
test -d ~/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-mlx && echo MODEL_OK || echo MODEL_MISSING
```

| 结果 | 行动 |
|------|------|
| `MODEL_OK` | 导出**默认开启语音转写**（脚本检测到模型即自动转，无需 `--transcribe`；用户明确不要才加 `--no-transcribe`） |
| `MODEL_MISSING` | **先问用户是否安装**（whisper-large-v3 ~3GB，纯离线一次性）。装→加 `--transcribe`（首次自动下载并转写）；不装→普通导出，语音保留 `[Audio]` |

脚本侧已内置同逻辑（模型在→默认转，不在→留 `[Audio]` 并提示）。但 `MODEL_MISSING` 时 Agent 必须主动问，别擅自下 3GB。

## MCP 工具（注册名 `wechat`）

| 工具 | 参数 | 用途 |
|------|------|------|
| `wechat_list_chats` | 无 | 所有会话（群名+备注已解析） |
| `wechat_read_chat` | contact, limit(50), days(7) | 特定对话 |
| `wechat_search_messages` | keyword, days(30), limit(50) | 全文搜索 |
| `wechat_recent_messages` | days(3), limit(100) | 最近动态 |
| `wechat_chat_summary` | days(3) | 结构化摘要 + 待办 |

`[我]` = 用户发的，`[对方]` = 联系人发的。

## 语音转写（全自动）

语音消息（`local_type=34`）的音频以 SILK v3 存在 `media_0.db` 的 `VoiceInfo.voice_data`，按 `svr_id == server_id` 对齐。链路：VoiceInfo 直取 → `pilk` 解码 SILK→wav → whisper large-v3 转写 → 按 server_id 回填。全自动、批量、纯离线，无需 BlackHole/播放/重启。**默认行为：模型已缓存即自动转写；`--transcribe` 强制（含首次下载 ~3GB 模型，缓存 `~/.cache/huggingface/`）；`--no-transcribe` 关闭。** **后端按平台自动切**：macOS = `mlx-whisper`（Apple Silicon），Windows = `faster-whisper`（CPU int8，按需下载）；旧 BlackHole+Swift 方案在 langlobal 开发仓。

## 命令行 entry（逻辑核心；MCP 是可选薄门面）

逻辑核心在 `scripts/common/query.py`（命令行），`server.py` 的 MCP 工具只是转发到它。**agent 调用推荐加 `--json` 拿结构化输出**（解析可靠，不受文字排版影响）；人调试时不加、看文字。

```bash
SKILL_DIR=~/.claude/skills/wechat-decrypt
python3 "$SKILL_DIR/scripts/common/query.py" list
python3 "$SKILL_DIR/scripts/common/query.py" recent -d 3 --json      # agent 用 --json
python3 "$SKILL_DIR/scripts/common/query.py" search 关键词 --json
# 子命令: list / read <contact> / search <kw> / recent / summary / stats / media / openfile
```

## 密钥体系（两端通用）

- **Raw Key**: 64 hex，**每设备独立**（微信 4.0：同账号 macOS 与 Windows 的 raw key 不同，不可互用）；微信不更新就持续有效
- **派生公式**: `PBKDF2-HMAC-SHA512(raw_key, db_file_salt, 256000) → 32 bytes`
- **SQLCipher 参数**: `PRAGMA key = "x'<derived>'"; PRAGMA kdf_iter = 1; PRAGMA cipher_compatibility = 4; PRAGMA cipher_page_size = 4096;`

## 数据库路径

| 平台 | 路径 |
|------|------|
| macOS | `~/Library/Containers/com.tencent.xinWeChat/.../xwechat_files/{wxid}/db_storage/` |
| Windows | `~/Documents/xwechat_files/{wxid}/db_storage/` |

---

# 密钥提取

## macOS

### Agent 执行流程

1. 检查重签名：`codesign -dv /Applications/WeChat.app 2>&1 | grep -q "Signature=adhoc" || echo "NEED_RESIGN"`
   - `NEED_RESIGN` → 告知用户执行 `sudo codesign --force --deep --sign - /Applications/WeChat.app`
2. 运行 `bash ~/.claude/skills/wechat-decrypt/scripts/macos/extract_key.sh`
3. 脚本会 spawn 微信 → **告知用户扫码登录** → 登录后 key 自动写入 `key.txt`
4. 验证：`test -f ~/.claude/skills/wechat-decrypt/key.txt && echo "OK"`
5. **提取后必须告知用户恢复签名**：adhoc 重签名是单向破坏性操作，会覆盖腾讯原始签名，导致微信截图/数据访问反复弹权限框。codesign 无法还原第三方签名，只能重装微信恢复。聊天记录在独立容器目录（`~/Library/Containers/com.tencent.xinWeChat/`），重装 `/Applications/WeChat.app` 不受影响。密钥提取后日常查消息只读 DB、不再需要重签名。

### 关键认知

- 重签名只在「提取密钥」这一瞬间需要，提取完即应重装微信恢复签名。
- 反复弹权限框 = 微信签名是 adhoc 状态的症状，不是 Claude Code/MCP 引起的。
- 密钥每设备独立（同账号各端 key 不同，不可互用），微信不更新就一直有效，无需反复提取。

### 原理

微信 4.x macOS 版不调 `sqlite3_key`（苹果系统 SQLite 的该函数为空壳），而是通过 WCDB 统一加密层调用 `CCKeyDerivationPBKDF`（CommonCrypto）。Frida 使用 `Module.findGlobalExportByName`（Frida 17.x+ API）hook 该函数，在 `passwordLen=32, rounds>1000, dkLen=32` 时捕获密码参数（raw key）。

## Windows（已攻克：提 key→解密→读取，能力对标 macOS）

**现状（2026-06-06 UTM 实测跑通）**：提 key→解密全库→MCP/导出/语音转写，与 macOS 同能力。message_0 解出 99 会话/1384 消息。全流程见 `docs/2026-06-06-windows-raw-key-journey.md`。

### Agent 执行流程
1. 登录微信
2. **提 key**：`python scripts\windows\extract_raw_key.py` → 按提示**桌面手动重启微信**（必须；schtasks/SSH 起的是空壳、不读 db）→ 脚本自动 race-attach + hook sha512 抓 raw key + 验证，写入 `key_windows.txt`
3. **解密全库**：`python scripts\windows\decrypt_all.py` → 用 raw key 把 db_storage 所有库解密到 `decrypted\{wxid}_<device>\db_storage\`（明文）
4. 重启 Claude Code → **MCP 工具、导出、语音转写与 macOS 完全一致**（server/export/transcribe 走 `DB_BACKEND="sqlite3"` 读明文库；语音用 faster-whisper）

单库验证/调试用 `scripts\windows\decrypt_read.py <raw_key>`（只解 message_0 验证）。

### 提 key 原理（sha512 入口 hook + HMAC ipad）
**核心**：raw key/K1 在内存被三重保护（AES-NI 轮密钥/用后清除/secure mem，内存 brute 全失败），但 SQLCipher 派生 key 走 **PBKDF2-HMAC-SHA512**，HMAC 构造 ipad block 那一刻是 key 的**明文** `key XOR 0x36`（后 96 字节恒 0x36）——绕过所有保护直取。
`extract_raw_key.py` 自包含：**自动定位** sha512 入口（搜 K 常量 `0x428a2f98d728ae22`→xref→反汇编，不硬编码地址，换微信版本也行）+ race-attach（赶在开 db 前）+ hook 入口（rdx=input block）+ 检测 ipad + 自动验证（`PBKDF2→AES page1` 出头=raw key 通用 / 直接 `AES` 出头=K1 单库）。启动 `PBKDF2(raw,salt)` 暴露 raw key；运行时 page-MAC 只暴露 mac_key（无用）→ 必须 race 赶**启动**。
**frida 在 ARM 模拟（xtajit 翻译 x64）下能 hook 微信内部 x64 函数**（1127万次验证）；spawn 不兼容用 race-attach。
- 数据路径：`C:\Users\<用户>\Documents\xwechat_files\{wxid}_<device>\db_storage\`。`wechat-dump-rs` 被 DMCA 封，本方法已替代。
- 开发期全套攻关脚本（定位/brute/失败记录）在 langlobal 开发仓，运行只需 `extract_raw_key.py`+`decrypt_all.py`。

---

## 分发与安装

拷贝整个 skill 目录。接收方执行：

**macOS:** `bash setup.sh`
**Windows:** `powershell -File setup.ps1`

`key.txt`、`contacts.json`、`all_keys.json` 是个人数据，分发前删除（已 `.gitignore`）。

## 文件清单

```
~/.claude/skills/wechat-decrypt/          # 运行单元；开发全套(tests/docs/攻关脚本/legacy)在 langlobal 开发仓
├── server.py config.py crypto.py db.py contacts.py message.py   ← MCP 运行核心(6)，db.py 双后端
├── scripts/
│   ├── common/    ← 跨平台：export_chat(导出+转写) transcribe_db voice_decode sqlcipher_decrypt read_doc export_media verify_key
│   ├── macos/     ← extract_key.sh + hook_pbkdf.js (CCKeyDerivationPBKDF)
│   └── windows/   ← extract_raw_key.py(自包含提key) decrypt_all.py(解密全库→明文) decrypt_read.py(单库验证)
├── setup.sh / setup.ps1   ← 平台安装
├── SKILL.md README.md LICENSE
├── key.txt key_windows.txt   ← .gitignore
└── contacts.json             ← .gitignore
```

依赖：**macOS** 全局 python（mcp/frida/cryptography/pilk/mlx-whisper/zstd）；**Windows**（mcp/frida/pycryptodome/pilk/faster-whisper/zstandard）。语音模型缓存 `~/.cache/huggingface/`。
