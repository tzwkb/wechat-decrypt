# wechat-decrypt

[![tests](https://github.com/tzwkb/wechat-decrypt/actions/workflows/tests.yml/badge.svg)](https://github.com/tzwkb/wechat-decrypt/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

English | [中文](README_ZH.md)

A local-first [Codex Skill](https://developers.openai.com/codex/skills) for reading, searching, summarizing, exporting, and transcribing WeChat 4.x history on macOS and Windows. The command-line core also works without MCP; the bundled server provides an optional [Codex MCP](https://developers.openai.com/codex/mcp) facade.

Use it only with local data you own or are authorized to access.

## What it does

- Lists chats and resolves contact remarks, nicknames, aliases, and group names.
- Reads, searches, summarizes, and measures messages across multiple database shards.
- Classifies pats, recalls, group/friend changes, red packets, payments, calls, pins, and unknown system events.
- Parses music, video links, Channels/live streams, mini programs, files, quotes, and unknown share cards while preserving titles, descriptions, sources, and URLs.
- Exports a contact and date range without an artificial message-count cap.
- Transcribes locally downloaded SILK voice messages with Whisper.
- Diagnoses the installation without exposing raw keys.
- Supports verified macOS and Windows key/decryption flows.

```text
macOS:  encrypted WeChat DB ── raw key ── SQLCipher read-only ─┐
                                                               ├─ query.py ── CLI / MCP
Windows: encrypted WeChat DB ── raw key ── private plaintext ──┘             └─ export / voice
```

## Quick start

Clone the repository, then run the setup script from its root.

### macOS

```bash
bash setup.sh
.venv/bin/python scripts/common/doctor.py --json
```

Setup creates an isolated `.venv`, installs SQLCipher and Python dependencies, links the checkout at `$HOME/.agents/skills/wechat-decrypt`, and registers the `wechat` stdio MCP server with Codex. Missing keys and local caches are migrated from the legacy `$HOME/.codex/skills/wechat-decrypt` copy without overwriting current files. If the user-skill path points to another checkout, inspect it first and then run `bash setup.sh --upgrade`; the previous path is retained as a timestamped backup.

Core setup stays lightweight. Install the optional local voice stack only when needed with `bash setup.sh --with-voice`; this installs sizeable ML libraries but not the approximately 3 GB model.

First-time key extraction requires temporary ad-hoc signing:

```bash
sudo codesign --force --deep --sign - /Applications/WeChat.app
bash scripts/macos/extract_key.sh
```

The script closes WeChat, opens it through Frida, and waits for QR login. After the key is captured, reinstall WeChat from the App Store or official site to restore Tencent's signature. See [the macOS guide](references/macos.md) before extracting.

### Windows

```powershell
powershell -File setup.ps1
$Python = ".\.venv\Scripts\python.exe"
& $Python scripts\windows\extract_raw_key.py
& $Python scripts\windows\decrypt_all.py
& $Python scripts\common\doctor.py --json
```

The extractor closes WeChat and asks you to restart it manually from the visible desktop. `decrypt_all.py` then creates a private local plaintext mirror used by the read-only query layer. See [the Windows guide](references/windows.md).

For an existing user-skill junction that points elsewhere, use `powershell -File setup.ps1 -Upgrade`. Private files are copied only when missing; an existing `decrypted/` mirror is linked rather than duplicated.

Install the optional Windows voice stack with `powershell -File setup.ps1 -WithVoice`. Ordinary query and export do not require it.

## Query

Agents should prefer `--json`; omit it for human-readable output.

```bash
.venv/bin/python scripts/common/query.py list --json
.venv/bin/python scripts/common/query.py read "Alice" -d 7 -n 50 --json
.venv/bin/python scripts/common/query.py search "deadline" -d 30 -n 50 --json
.venv/bin/python scripts/common/query.py recent -d 3 -n 100 --json
.venv/bin/python scripts/common/query.py summary -d 3 --json
.venv/bin/python scripts/common/query.py events -e pat -d 30 -n 100 --json
```

Stable event filters are `pat`, `recall`, `group_join`, `group_remove`, `group_leave`, `group_rename`, `group_notice`, `group_admin`, `group_owner`, `group_disband`, `friend_added`, `red_packet`, `payment`, `call`, `chat_pinned`, and `system`. Chinese labels are also accepted.

Type-49 share cards use the same parser in reads, searches, summaries, statistics, and exports. JSON output adds an `app` object with a stable kind, title, description, source, URL, and music/Channels/mini-program metadata. Unknown subtypes preserve common card fields and remain searchable through their local payload.

Search decodes every compressed-text and type-49 candidate in bounded pages, so results are not limited to a fixed recent-card window. It does not create a persistent plaintext search index.

The MCP server exposes the same core operations:

| Tool | Purpose |
|---|---|
| `wechat_list_chats` | List conversations |
| `wechat_read_chat` | Read one contact or group |
| `wechat_search_messages` | Full-text search |
| `wechat_recent_messages` | Review recent activity |
| `wechat_chat_summary` | Structured recent-chat context |
| `wechat_system_events` | Pats, recalls, group/friend changes, payments, calls, pins, and unknown events |

## Export and voice

```bash
.venv/bin/python scripts/common/export_chat.py "Alice" --year 2026 -o ~/Desktop/alice-2026.txt
.venv/bin/python scripts/common/export_chat.py "Alice" --start 2026-01-01 --end 2026-06-30
```

If the platform's Whisper large-v3 model is already cached, voice transcription is automatic. Otherwise ordinary export leaves `[Audio]` and does not download a model. Use `--transcribe` only after approving the approximately 3 GB first download, or `--no-transcribe` to disable transcription. See [the export and transcription guide](references/export-transcription.md).

## Security model

- Query backends open databases read-only; SQLite writes are blocked with `query_only`.
- Raw keys are validated, stored with private permissions, ignored by Git, and never echoed by extractors or diagnostics.
- Plaintext databases, exports, derived-key caches, and voice caches use private permissions where supported.
- The project does not upload chat data or use a cloud transcription service.
- `key.txt`, `key_windows.txt`, `decrypted/`, `all_keys.json`, `contacts.json`, and `voice_cache.json` must never be committed.

## Development

Unit tests use synthetic databases and require no personal WeChat data. The Windows extractor tests also execute its embedded JavaScript against synthetic memory using Node.js 22 or newer. Install test dependencies with `python3 -m pip install pytest pycryptodome 'mcp[cli]>=1,<2'`:

```bash
python3 -m pytest -q
python3 -m compileall -q appmsg.py config.py contacts.py crypto.py db.py message.py server.py scripts/common scripts/windows
bash -n setup.sh scripts/macos/extract_key.sh
.venv/bin/python -c "import asyncio, server; assert len(asyncio.run(server.mcp.list_tools())) == 6"
```

Real-data checks are documented in [e2e/README.md](e2e/README.md). The Skill entrypoint is [SKILL.md](SKILL.md); platform and export details live under `references/` to keep agent context small.

## License

MIT
