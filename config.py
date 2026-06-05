"""WeChat MCP Server — configuration and platform detection."""
import os
import platform

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))

KEY_FILE = os.path.join(SKILL_DIR, "key.txt")
CONTACTS_FILE = os.path.join(SKILL_DIR, "contacts.json")

IS_MACOS = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"

if IS_MACOS:
    DB_BACKEND = "sqlcipher"
    SQLCIPHER_PATH = "/opt/homebrew/bin/sqlcipher"
    WECHAT_DATA_GLOB = os.path.expanduser(
        "~/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
        "xwechat_files/*/db_storage"
    )
elif IS_WINDOWS:
    DB_BACKEND = "sqlite3"
    # decrypt_all.py 解密产物根目录（明文库，保留 {wxid}/db_storage 结构）
    DECRYPTED_DIR = os.path.join(SKILL_DIR, "decrypted")
    # 原始加密库（仅供提 key/解密时定位源）
    WECHAT_DATA_GLOB = os.path.expanduser(
        "~/Documents/xwechat_files/*/db_storage"
    )
else:
    raise RuntimeError(f"Unsupported platform: {platform.system()}")
