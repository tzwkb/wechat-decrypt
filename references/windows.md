# Windows setup and key extraction

Read this file only for Windows installation, a missing/invalid key, or re-extraction after WeChat changes.

## Install

From PowerShell in the skill checkout:

```powershell
powershell -File setup.ps1
```

Setup creates `.venv`, installs dependencies, safely creates a junction at `$HOME\.agents\skills\wechat-decrypt`, migrates missing private files from the legacy `$HOME\.codex\skills\wechat-decrypt` copy, and registers the `wechat` stdio MCP server with Codex. It never overwrites a private file or duplicates an existing plaintext mirror.

Ordinary setup omits the sizeable voice stack. Install it only for transcription with `powershell -File setup.ps1 -WithVoice`; this does not download the model.

Windows dependencies are defined in `requirements-windows.txt`. Python 3.10 uses Frida 17.2.17 because Frida 17.17.0 imports `typing.NotRequired`, which is unavailable in Python 3.10. Python 3.11+ uses the current Frida 17.x line.

If the user-skill path already points to another checkout, ordinary setup stops. Inspect it, then explicitly switch with `powershell -File setup.ps1 -Upgrade`; setup retains the old path as a timestamped backup and links an existing `decrypted\` directory instead of copying it. A failed private-state migration restores the prior junction.

```powershell
$Python = ".\.venv\Scripts\python.exe"
& $Python scripts\common\doctor.py --json
```

## Extract and decrypt

This flow requires an interactive desktop session. Before running extraction, tell the user it will close WeChat and that they must restart WeChat manually from the desktop when prompted.

```powershell
& $Python scripts\windows\extract_raw_key.py
```

The extractor race-attaches to the desktop-launched `Weixin.exe`, verifies the captured account-wide raw key, and writes `key_windows.txt` with private permissions. It never echoes the key. Do not launch WeChat through SSH, a scheduled task, or a background service; those processes may not open the databases.

After extraction:

```powershell
& $Python scripts\windows\decrypt_all.py
& $Python scripts\common\doctor.py --json
```

`decrypt_all.py` reads `key_windows.txt` by default and builds a plaintext mirror at `decrypted\<account>\db_storage\`. Files are written atomically with private permissions where the platform supports them. Never upload or expose this directory.

## Troubleshooting

- `message_0.db not found`: sign in to WeChat and confirm `Documents\xwechat_files\...\db_storage\message\message_0.db` exists.
- No raw key before timeout: check the reported K-table count and hooked entry RVAs, then confirm WeChat was manually restarted from the visible desktop after the extractor prompt. Share the WeChat version and status/error lines when reporting a failure; never share keys or database files.
- Decryption yields zero databases: the key is wrong for this device, WeChat changed its format, or the selected account directory is not the active one.
- After a WeChat update: rerun `doctor.py`; repeat extraction only if the current key no longer works.

The extractor scans all SHA-512 K-tables and hooks every distinct resolved entry. Some builds, including the reported WeChat 4.1.12.55 layout, use a different implementation for PBKDF2 than the first table's implementation. Process detection uses `tasklist` CSV output, and hook installation waits for `Weixin.dll` to load. The raw key remains device-specific even for the same WeChat account.
