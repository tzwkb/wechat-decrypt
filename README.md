# wechat-decrypt

English | [中文](README_ZH.md)


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

The following code blocks keep commands, paths, filenames, and configuration keys literal; explanatory comments are translated for the English README.

```
WeChat → WCDB encryption layer
         │
         ├── macOS:  CCKeyDerivationPBKDF → Frida hook → raw key
         │
         └── Windows: SQLCipher (statically linked) → wechat-dump-rs → raw key
                                                                    │
                                              PBKDF2(raw_key, salt, 256000)
                                                                    │
                                              sqlcipher (kdf_iter=1) ─┬─ MCP Server (browse/search)
                                                                      │
                                                                      └─ export_chat.py (export + voice transcription)
```

```bash
bash setup.sh               # one-click macOS install
# or
powershell -File setup.ps1  # Windows

# extract key → write key.txt → restart Claude Code
```

```bash
python3 scripts/common/export_chat.py 张三 --year 2026 -o ~/Desktop/out.txt
python3 scripts/common/export_chat.py 张三 --start 2026-01-01 --end 2026-06-03
python3 scripts/common/export_chat.py 张三 --year 2026 --transcribe   # transcribe voice messages
```

## Detailed Technical Notes

The primary README keeps the original technical details, history notes, full commands, and file layout. This file maintains the English version of the core documentation; consult the primary README code blocks and paths when exact commands are needed.
