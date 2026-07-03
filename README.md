# wechat-decrypt

[中文](README_ZH.md) | English


## Overview

 WeChat 4.x chat decrypt, query, export, and voice transcription Agent Skill for verified macOS/Windows workflows with MCP access.

## Key Capabilities

- Decrypts local WeChat databases.
- Provides chat, contact, full-text search, and export capabilities.
- Can expose query tools through MCP.

## Usage

 Follow the platform-specific README/SKILL.md flow to extract keys, decrypt databases, and start query tools.

## Status

 This repository is maintained or used according to the current README notes.

## Notes

 Use only for local data the user is authorized to access.

## Command and Configuration Reference

The following code blocks are preserved from the primary README. Commands, paths, and configuration keys are not translated; adjust them for the actual environment.

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

```bash
bash setup.sh               # macOS 一键安装
# 或
powershell -File setup.ps1  # Windows

# 提取密钥 → 写入 key.txt → 重启 Claude Code
```

```bash
python3 scripts/common/export_chat.py 张三 --year 2026 -o ~/Desktop/out.txt
python3 scripts/common/export_chat.py 张三 --start 2026-01-01 --end 2026-06-03
python3 scripts/common/export_chat.py 张三 --year 2026 --transcribe   # 语音转文字
```

## Detailed Technical Notes

The primary README keeps the original technical details, history notes, full commands, and file layout. This file maintains the English version of the core documentation; consult the primary README code blocks and paths when exact commands are needed.
