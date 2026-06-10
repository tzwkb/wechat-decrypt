#!/usr/bin/env python3
"""WCDB/SQLCipher 损坏库逐页抢救（复刻 RepairKit 原理）。

针对微信 factory 归档的损坏 message 库：首页/部分页损坏导致正常 open 失败，
但 SQLCipher 4 每页独立 AES-256-CBC 加密——逐页解密能解的页，从 leaf table
page 解析 cells 抢救记录，绕过损坏的 header。

只读输入库，绝不写原始/微信目录。

用法:
    python3 repair_factory.py <corrupt.db> --diagnose
    python3 repair_factory.py <corrupt.db> --salvage-table Msg_<md5> -o out.json
"""
import argparse
import hashlib
import json
import os
import struct
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SKILL_DIR)

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    def _aes_cbc_decrypt(key: bytes, iv: bytes, ct: bytes) -> bytes:
        d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        return d.update(ct) + d.finalize()
except ImportError:
    from Crypto.Cipher import AES
    def _aes_cbc_decrypt(key: bytes, iv: bytes, ct: bytes) -> bytes:
        return AES.new(key, AES.MODE_CBC, iv).decrypt(ct)

PAGE = 4096
KEY_FILE = os.path.join(SKILL_DIR, "key.txt")
BTREE_TYPES = {2, 5, 10, 13}  # interior index/table, leaf index/table


def load_raw_key() -> bytes:
    return bytes.fromhex(open(KEY_FILE).read().strip())


def derive_enc_keys(raw: bytes, salt: bytes):
    """微信: derived = PBKDF2-SHA512(raw, salt, 256000); 传 sqlcipher 后 kdf_iter=1.
    返回候选 (名称, aes_key) 列表，诊断阶段自动选对的。"""
    derived = hashlib.pbkdf2_hmac("sha512", raw, salt, 256000, 32)
    return [
        ("derived_direct", derived),
        ("kdf_iter1", hashlib.pbkdf2_hmac("sha512", derived, salt, 1, 32)),
    ]


def decrypt_page(data: bytes, page_no: int, reserve: int, key: bytes):
    """解密单页。page1 前16字节是明文 salt。失败返回 None。"""
    off = (page_no - 1) * PAGE
    page = data[off:off + PAGE]
    if len(page) < PAGE:
        return None
    start = 16 if page_no == 1 else 0
    ct_end = PAGE - reserve
    iv = page[ct_end:ct_end + 16]
    ct = page[start:ct_end]
    if len(ct) % 16:
        return None
    try:
        return _aes_cbc_decrypt(key, iv, ct)
    except Exception:
        return None


def page_is_valid_btree(pt: bytes, page_no: int) -> bool:
    """解密后是否像合法 SQLite B-tree 页。"""
    if not pt:
        return False
    # page1: 解密区从原 header offset 16 开始，前2字节=page size 字段(4096→0x1000)
    if page_no == 1:
        return pt[:2] == b"\x10\x00"
    return pt[0] in BTREE_TYPES


def find_params(data: bytes, raw: bytes):
    """自动探测 (key, reserve)：解开 page2 即命中。返回 (kname, key, reserve) 或 None。"""
    salt = data[:16]
    for kname, key in derive_enc_keys(raw, salt):
        for reserve in (80, 64, 48):
            p2 = decrypt_page(data, 2, reserve, key)
            if page_is_valid_btree(p2, 2):
                return kname, key, reserve
    return None


def diagnose(path: str):
    data = open(path, "rb").read()
    raw = load_raw_key()
    salt = data[:16]
    npages = len(data) // PAGE
    print(f"文件: {path}")
    print(f"大小: {len(data):,} bytes | 页数@4096: {npages} | salt: {salt.hex()}")

    found = find_params(data, raw)
    if not found:
        print("\n✗ 现有 key 解不开任何数据页 → 要么换钥了，要么页加密格式不符。逐页抢救无法用此 key。")
        return None
    kname, key, reserve = found
    print(f"\n✓ 命中参数: key={kname}  reserve={reserve}  → 现有 raw key 有效，只是部分页损坏")

    good = bad = 0
    bad_pages = []
    for pn in range(1, npages + 1):
        pt = decrypt_page(data, pn, reserve, key)
        if page_is_valid_btree(pt, pn):
            good += 1
        else:
            bad += 1
            if len(bad_pages) < 30:
                bad_pages.append(pn)
    print(f"\n逐页校验: 完好 {good} / 损坏 {bad}  (完好率 {good*100//npages}%)")
    print(f"损坏页(前30): {bad_pages}")
    print(f"\n→ 完好的数据页可逐页抢救记录。下一步: --salvage-table <表名>")
    return {"key_kind": kname, "reserve": reserve, "npages": npages,
            "good": good, "bad": bad}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="损坏库路径（用备份副本！）")
    ap.add_argument("--diagnose", action="store_true")
    a = ap.parse_args()
    if a.diagnose:
        diagnose(a.db)
    else:
        ap.error("先 --diagnose")


if __name__ == "__main__":
    main()
