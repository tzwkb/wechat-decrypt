#!/usr/bin/env python3
"""Decrypt EVERY WeChat db under db_storage into the plaintext DECRYPTED_DIR (Windows sqlite3 backend).

After extract_raw_key.py yields the raw key, this rebuilds a full plaintext mirror so server.py /
export_chat.py / transcribe_db.py (config.DB_BACKEND='sqlite3') can read it like Mac reads the
encrypted store directly. Preserves the {wxid}_{device}/db_storage/... layout that db.py expects.

Pure pycryptodome (the VM has no `cryptography`). Usage: python decrypt_all.py [raw_key_hex]
(raw key defaults to ../../key_windows.txt).
"""
import sys, os, glob, hashlib

try:                                    # AES 后端: pycryptodome(Windows/VM) 优先, 退 cryptography(macOS)
    from Crypto.Cipher import AES

    def _aes_cbc_dec(key, iv, ct):
        return AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
except ImportError:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    def _aes_cbc_dec(key, iv, ct):
        d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        return d.update(ct) + d.finalize()

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DECRYPTED_DIR = os.path.join(SKILL_DIR, "decrypted")
PAGE, RESERVE, SALT_SZ = 4096, 80, 16


def decrypt_db(raw: bytes, src: str, dst: str) -> bool:
    """Decrypt one SQLCipher v4 db to plaintext sqlite. Returns False if key/format mismatch."""
    data = open(src, "rb").read()
    if len(data) < PAGE or len(data) % PAGE:
        return False
    salt = data[:SALT_SZ]
    enc = hashlib.pbkdf2_hmac("sha512", raw, salt, 256000, 32)
    rstart = PAGE - RESERVE
    # verify page 1 header before committing
    iv0 = data[rstart:rstart + 16]
    pt0 = _aes_cbc_dec(enc, iv0, data[SALT_SZ:rstart])
    if not (pt0[0] == 0x10 and pt0[1] == 0x00 and pt0[4] == 0x50 and pt0[5] == 0x40 and pt0[7] == 0x20):
        return False
    out = bytearray(b"SQLite format 3\x00")
    out += pt0 + data[rstart:PAGE]
    for i in range(1, len(data) // PAGE):
        page = data[i * PAGE:(i + 1) * PAGE]
        iv = page[rstart:rstart + 16]
        out += _aes_cbc_dec(enc, iv, page[:rstart]) + page[rstart:]
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "wb").write(out)
    return True


def main():
    if len(sys.argv) > 1:
        raw_hex = sys.argv[1].strip()
    else:
        raw_hex = open(os.path.join(SKILL_DIR, "key_windows.txt")).read().strip()
    raw = bytes.fromhex(raw_hex)

    src_roots = glob.glob(os.path.expanduser(r"~/Documents/xwechat_files/*/db_storage"))
    if not src_roots:
        print("ERR: no encrypted db_storage under ~/Documents/xwechat_files/*/"); sys.exit(1)
    src_root = max(src_roots, key=os.path.getmtime)
    account = os.path.basename(os.path.dirname(src_root))  # {wxid}_{device}
    dst_root = os.path.join(DECRYPTED_DIR, account, "db_storage")

    ok = skip = 0
    for src in sorted(glob.glob(os.path.join(src_root, "**", "*.db"), recursive=True)):
        rel = os.path.relpath(src, src_root)
        dst = os.path.join(dst_root, rel)
        try:
            if decrypt_db(raw, src, dst):
                ok += 1; print("OK  ", rel)
            else:
                skip += 1; print("skip", rel, "(key/format mismatch or empty)")
        except Exception as e:
            skip += 1; print("ERR ", rel, e)
    print(f"\n{ok} decrypted, {skip} skipped -> {dst_root}")
    if ok:
        print(">>> plaintext store ready; server.py / export_chat.py can now read it <<<")


if __name__ == "__main__":
    main()
