# Moved Windows data directories

If WeChat's `xwechat_files` directory lives outside Documents, set its parent
account root before extracting, decrypting, running the doctor, or querying:

```powershell
$env:WECHAT_DATA_ROOT = 'D:\WeChat\xwechat_files'
& .venv\Scripts\python.exe scripts\windows\extract_raw_key.py
& .venv\Scripts\python.exe scripts\windows\decrypt_all.py
& .venv\Scripts\python.exe scripts\common\doctor.py --json
```

This directory contains the account folders, each with a `db_storage` directory.
All Windows discovery paths honor the same override. An explicit missing override
does not fall back to another account under Documents. Without an override the
existing Documents discovery behavior is preserved.
