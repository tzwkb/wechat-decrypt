#!/usr/bin/env python3
"""Verify raw key against all WeChat databases using HMAC-SHA512 page verification."""
import hashlib, hmac, os, glob, struct, sys

PAGE_SZ, SALT_SZ, KEY_SZ = 4096, 16, 32
_bases = glob.glob(os.path.expanduser(
    "~/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
    "xwechat_files/*/db_storage"
))
BASE = _bases[0] if _bases else ""
KEY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "key.txt")

def verify_enc_key(enc_key, db_page1):
    salt = db_page1[:SALT_SZ]
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SZ)
    hmac_data = db_page1[SALT_SZ: PAGE_SZ - 80 + 16]
    stored_hmac = db_page1[PAGE_SZ - 64: PAGE_SZ]
    hm = hmac.new(mac_key, hmac_data, hashlib.sha512)
    hm.update(struct.pack("<I", 1))
    return hm.digest() == stored_hmac

def main():
    if len(sys.argv) > 1:
        raw_hex = sys.argv[1]
    elif os.path.exists(KEY_FILE):
        raw_hex = open(KEY_FILE).read().strip()
    else:
        print("Usage: verify_key.py <64-char-hex-key>")
        print("Or ensure key.txt exists in the skill directory")
        sys.exit(1)

    raw_key = bytes.fromhex(raw_hex)

    dbs = glob.glob(f"{BASE}/**/*.db", recursive=True)
    ok, fail = 0, 0
    for db_path in dbs:
        with open(db_path, "rb") as f:
            page1 = f.read(PAGE_SZ)
        if page1[:15] == b"SQLite format 3":
            continue  # skip unencrypted

        derived = hashlib.pbkdf2_hmac("sha512", raw_key, page1[:SALT_SZ], 256000, dklen=KEY_SZ)
        if verify_enc_key(derived, page1):
            ok += 1
        else:
            fail += 1
            print(f"  FAIL: {os.path.relpath(db_path, BASE)}")

    print(f"Verified: {ok} OK, {fail} FAILED, {ok+fail} total")
    if fail > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
