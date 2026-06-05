"""Key loading and PBKDF2 derivation."""
import hashlib
import os

import config


def load_key() -> str:
    """Load the raw key from key.txt (64 hex chars = 32 bytes)."""
    if not os.path.exists(config.KEY_FILE):
        raise FileNotFoundError(
            f"密钥文件不存在: {config.KEY_FILE}\n"
            "运行 scripts/macos/extract_key.sh 提取密钥"
        )
    return open(config.KEY_FILE).read().strip()


def derive_key(raw_key_hex: str, db_path: str) -> str:
    """Derive per-DB encryption key from raw key + DB file salt.

    WeChat uses: PBKDF2-HMAC-SHA512(raw_key, db_salt[0:16], 256000) → 32 bytes
    SQLCipher then uses the derived key with kdf_iter=1 (no further PBKDF2).
    """
    with open(db_path, "rb") as f:
        salt = f.read(16)
    raw_key = bytes.fromhex(raw_key_hex)
    derived = hashlib.pbkdf2_hmac("sha512", raw_key, salt, 256000, dklen=32)
    return derived.hex()
