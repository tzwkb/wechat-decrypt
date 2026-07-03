# wechat-decrypt

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-Codex-blue.svg)](SKILL.md)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)

[English](README.md) | 中文

**Agent Skill** — WeChat 4.x 聊天记录解密、查询、导出和语音转写工具，支持 macOS/Windows 已验证流程与 MCP 查询接口。


作为 Agent Skill 分发：拷贝整个目录到对应 agent 的 skills 目录，Agent 通过 [SKILL.md](SKILL.md) 自动加载触发规则，并以 MCP Server 形式暴露查询工具。也可脱离 Agent 单独运行导出脚本。

## 架构

```
微信 → WCDB 加密层
         │
         ├── macOS:  CCKeyDerivationPBKDF → Frida hook → raw key
         │
         └── Windows: SQLCipher (静态链接) → wechat-dump-rs → raw key
                                                                    │
                                              PBKDF2(raw_key, salt, 256000)
                                                                    │
                                              sqlcipher (kdf_iter=1) ─┬─ MCP Server（浏览/搜索）
                                                                      │
                                                                      └─ export_chat.py（导出+语音转写）
```

## 快速开始

```bash
bash setup.sh               # macOS 一键安装
# 或
powershell -File setup.ps1  # Windows

# 提取密钥 → 写入 key.txt → 重启 Claude Code
```

详见 [SKILL.md](SKILL.md)。

## 功能

### MCP Server (`server.py`)

| 工具 | 用途 |
|------|------|
| `wechat_list_chats` | 所有会话列表 |
| `wechat_read_chat` | 读取特定对话 |
| `wechat_search_messages` | 全文搜索 |
| `wechat_recent_messages` | 最近动态 |
| `wechat_chat_summary` | 结构化摘要 + 待办提取 |

### 导出脚本 (`scripts/common/export_chat.py`)

```bash
python3 scripts/common/export_chat.py 张三 --year 2026 -o ~/Desktop/out.txt
python3 scripts/common/export_chat.py 张三 --start 2026-01-01 --end 2026-06-03
python3 scripts/common/export_chat.py 张三 --year 2026 --transcribe   # 语音转文字
```

- 自动按月分片，无条数上限
- 支持整年或自定义区间
- 说话人用各自的微信昵称（非备注）；发送者身份逐 DB 解析，避免跨 DB rowid 冲突
- 消息格式：
  - 文本：原文，换行转空格
  - 图片：`[Image]`
  - 视频：`[Video]`
  - 贴纸：`[Sticker]`
  - 语音：`[Audio 5s]`（含时长）
  - 引用回复：`回复文字 [↩ 发件人: 被引内容]`
  - 链接/小程序：`[Link: 标题]` / `[MiniApp: 名称]`
  - 转发聊天记录：`[Chat History]`
- `--transcribe` 全自动语音转写（见下方）

### 语音转写（`scripts/common/transcribe_db.py` + `voice_decode.py`）

全自动，无需播放/录音/重启。仅在 `--transcribe` 且存在语音消息时触发：
1. 收集目标对话 `local_type=34` 的 `server_id`
2. 从 `media_0.db` 的 `VoiceInfo` 表直取 `voice_data`（SILK v3 BLOB）
3. `pilk` 解码 SILK → 24kHz wav（首字节 `0x02` 为微信私有前缀，需剥离）
4. `mlx-whisper` large-v3 转写（`language=zh`，Apple Silicon Metal 加速）
5. 按 `svr_id == server_id` 精确回填到每条消息（不依赖播放顺序）

依赖全部装在全局 `/opt/homebrew/bin/python3`：

| 组件 | 大小 | 位置 |
|------|------|------|
| pilk | <1MB | 全局 site-packages |
| mlx-whisper | ~150MB（含 mlx/torch） | 全局 site-packages |
| whisper-large-v3 模型 | ~3GB | `~/.cache/huggingface/` |

> 旧的 BlackHole + Swift Speech 方案已移到 `scripts/legacy/`（仅 Intel Mac 或无 `VoiceInfo` 时备用）。

## 平台差异

| | macOS | Windows |
|---|---|---|
| 密钥提取 | Frida `CCKeyDerivationPBKDF` | wechat-dump-rs 内存扫描 |
| 前置步骤 | codesign 重签名 | 无 |
| DB 路径 | `~/Library/Containers/...` | `~/Documents/xwechat_files/...` |
| sqlcipher | brew 安装 | 随 skill 分发 |
| 语音转写 | VoiceInfo 直取 + mlx-whisper（Apple Silicon） | 未适配 |

## 文件

| 文件 | 用途 |
|------|------|
| `SKILL.md` | Agent 指令 |
| `server.py` | MCP Server |
| `scripts/common/export_chat.py` | 导出脚本（自动分片） |
| `scripts/common/transcribe_db.py` | 语音转写（VoiceInfo + mlx-whisper） |
| `scripts/common/voice_decode.py` | SILK v3 BLOB → wav 解码 |
| `scripts/common/verify_key.py` | HMAC 密钥验证 |
| `scripts/macos/extract_key.sh` | macOS 密钥提取 |
| `scripts/macos/hook_pbkdf.js` | Frida 拦截（macOS 提取） |
| `scripts/windows/extract_key.ps1` | Windows 密钥提取 + 解密（wechat-dump-rs） |
| `scripts/legacy/` | 旧 BlackHole+Swift 方案（备用） |
| `setup.sh / setup.ps1` | 平台安装脚本 |

## License

MIT
