#!/usr/bin/env python3
"""Decrypt a WeChat 4.0 SQLCipher v4 database to plaintext sqlite, given the account raw key.

Pure-Python replacement for wechat-dump-rs decryption (DMCA'd off GitHub). Used on Windows where
no sqlcipher binary is available: extract raw key (frida) -> decrypt here -> read with builtin sqlite3.

SQLCipher v4: PBKDF2-HMAC-SHA512(raw, salt, 256000) -> enc_key; HMAC-SHA512 page auth;
AES-256-CBC; page 4096 with 80-byte reserve (IV16 + HMAC64); page1 first 16 bytes = plaintext salt.

Usage: python sqlcipher_decrypt.py <raw_key_hex> <encrypted.db> <plaintext.db>
"""
import hashlib
import hmac
import struct
import sys
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PAGE, SALT_SZ, RESERVE, IV_SZ, HMAC_SZ, KEY_SZ = 4096, 16, 80, 16, 64, 32


def decrypt_db(raw_key_hex, src, dst, verify=True):
    raw = bytes.fromhex(raw_key_hex.strip())
    data = open(src, "rb").read()
    salt = data[:SALT_SZ]
    enc_key = hashlib.pbkdf2_hmac("sha512", raw, salt, 256000, KEY_SZ)
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, KEY_SZ)
    n = len(data) // PAGE
    out = bytearray()
    rstart = PAGE - RESERVE          # 4016: start of [IV16 | HMAC64]
    for i in range(n):
        page = data[i * PAGE:(i + 1) * PAGE]
        start = SALT_SZ if i == 0 else 0
        ct = page[start:rstart]
        iv = page[rstart:rstart + IV_SZ]
        if verify:
            h = hmac.new(mac_key, page[start:rstart + IV_SZ], hashlib.sha512)
            h.update(struct.pack("<I", i + 1))
            if h.digest() != page[rstart + IV_SZ:rstart + IV_SZ + HMAC_SZ]:
                raise ValueError(f"HMAC mismatch at page {i + 1} -- wrong key")
        dec = Cipher(algorithms.AES(enc_key), modes.CBC(iv)).decryptor()
        pt = dec.update(ct) + dec.finalize()
        if i == 0:
            out += b"SQLite format 3\x00" + pt + page[rstart:]
        else:
            out += pt + page[rstart:]
    with open(dst, "wb") as f:
        f.write(out)
    return n


def decrypt_db_k1(enc_key_hex, src, dst, verify=True):
    """Decrypt using the derived 32B encryption key (K1) directly, skipping PBKDF2 on the raw key."""
    enc_key = bytes.fromhex(enc_key_hex.strip())
    data = open(src, "rb").read()
    salt = data[:SALT_SZ]
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, KEY_SZ)
    n = len(data) // PAGE
    out = bytearray()
    rstart = PAGE - RESERVE
    for i in range(n):
        page = data[i * PAGE:(i + 1) * PAGE]
        start = SALT_SZ if i == 0 else 0
        ct = page[start:rstart]
        iv = page[rstart:rstart + IV_SZ]
        if verify:
            h = hmac.new(mac_key, page[start:rstart + IV_SZ], hashlib.sha512)
            h.update(struct.pack("<I", i + 1))
            if h.digest() != page[rstart + IV_SZ:rstart + IV_SZ + HMAC_SZ]:
                raise ValueError(f"HMAC mismatch at page {i + 1} -- wrong K1")
        dec = Cipher(algorithms.AES(enc_key), modes.CBC(iv)).decryptor()
        pt = dec.update(ct) + dec.finalize()
        out += (b"SQLite format 3\x00" + pt + page[rstart:]) if i == 0 else (pt + page[rstart:])
    with open(dst, "wb") as f:
        f.write(out)
    return n


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit("usage: sqlcipher_decrypt.py <raw_key_hex> <src.db> <dst.db>")
    pages = decrypt_db(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"decrypted {pages} pages -> {sys.argv[3]}")
