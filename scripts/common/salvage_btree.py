#!/usr/bin/env python3
"""SQLite B-tree 抢救解析器——配合 repair_factory，从 HMAC 完好的解密页里
绕过损坏的 page1，按表 root page 遍历 B-tree、解析记录（含 overflow 链）。

用于微信 factory 损坏库：首页 salt 被覆盖、page1 损坏，但数据页完好。
真 salt 从配对的 .material 文件头取（material 与主库共享 cipher salt）。
"""
import hashlib
import hmac as _hmac
import struct

PAGE = 4096
RESERVE = 80
USABLE = PAGE - RESERVE  # 4016


def _aes_dec(key, iv, ct):
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        return d.update(ct) + d.finalize()
    except ImportError:
        from Crypto.Cipher import AES
        return AES.new(key, AES.MODE_CBC, iv).decrypt(ct)


def decrypt_good_pages(data: bytes, salt: bytes, raw: bytes):
    """HMAC 校验 + 解密所有完好页。返回 {page_no: 解密内容(USABLE字节)}。
    page1 内容前 16 字节补零占位（原是明文 salt）。"""
    enc = hashlib.pbkdf2_hmac("sha512", raw, salt, 256000, 32)
    hkey = hashlib.pbkdf2_hmac("sha512", enc, bytes(b ^ 0x3a for b in salt), 2, 32)
    npg = len(data) // PAGE
    pages = {}
    bad = []
    for pn in range(1, npg + 1):
        off = (pn - 1) * PAGE
        pg = data[off:off + PAGE]
        if len(pg) < PAGE:
            break
        start = 16 if pn == 1 else 0
        ctend = PAGE - RESERVE
        iv = pg[ctend:ctend + 16]
        mac = _hmac.new(hkey, pg[start:ctend + 16] + struct.pack("<I", pn), hashlib.sha512).digest()
        if mac != pg[ctend + 16:ctend + 16 + 64]:
            bad.append(pn)
            continue
        try:
            pt = _aes_dec(enc, iv, pg[start:ctend])
        except Exception:
            bad.append(pn)
            continue
        pages[pn] = (b"\x00" * 16 + pt) if pn == 1 else pt
    return pages, npg, bad


def varint(buf, o):
    v = 0
    for i in range(9):
        if o + i >= len(buf):
            return v, o + i
        x = buf[o + i]
        if i == 8:
            return (v << 8) | x, o + 9
        v = (v << 7) | (x & 0x7F)
        if not x & 0x80:
            return v, o + i + 1
    return v, o + 9


def _full_payload(pages, pg, co):
    """读 leaf table cell 的完整 payload（跨 overflow 链）。返回 (rowid, payload)。"""
    plen, o = varint(pg, co)
    rowid, o = varint(pg, o)
    X = USABLE - 35
    if plen <= X:
        return rowid, pg[o:o + plen]
    M = ((USABLE - 12) * 32 // 255) - 23
    local = M + (plen - M) % (USABLE - 4)
    if local > X:
        local = M
    buf = bytearray(pg[o:o + local])
    ovf = int.from_bytes(pg[o + local:o + local + 4], "big")
    guard = 0
    while ovf and ovf in pages and len(buf) < plen and guard < 100000:
        opg = pages[ovf]
        nxt = int.from_bytes(opg[:4], "big")
        buf += opg[4:4 + min(USABLE - 4, plen - len(buf))]
        ovf = nxt
        guard += 1
    return rowid, bytes(buf[:plen])


def parse_record(payload):
    """SQLite record → 值列表。健壮容错。"""
    try:
        hlen, p = varint(payload, 0)
        types = []
        while p < hlen and p < len(payload):
            st, p = varint(payload, p)
            types.append(st)
        vals = []
        d = hlen
        for st in types:
            if st == 0:
                vals.append(None)
            elif 1 <= st <= 4:
                vals.append(int.from_bytes(payload[d:d + st], "big", signed=True)); d += st
            elif st == 5:
                vals.append(int.from_bytes(payload[d:d + 6], "big", signed=True)); d += 6
            elif st == 6:
                vals.append(int.from_bytes(payload[d:d + 8], "big", signed=True)); d += 8
            elif st == 7:
                vals.append(struct.unpack(">d", payload[d:d + 8])[0]); d += 8
            elif st == 8:
                vals.append(0)
            elif st == 9:
                vals.append(1)
            else:
                n = (st - 12) // 2 if st % 2 == 0 else (st - 13) // 2
                vals.append(payload[d:d + n]); d += n
        return vals
    except Exception:
        return None


def _leaf_cells(pages, pg, pn):
    base = 100 if pn == 1 else 0
    if base >= len(pg) or pg[base] != 0x0D:
        return []
    n = int.from_bytes(pg[base + 3:base + 5], "big")
    out = []
    hdr = base + 8
    for i in range(n):
        po = hdr + i * 2
        if po + 2 > len(pg):
            break
        co = int.from_bytes(pg[po:po + 2], "big")
        if co == 0 or co >= len(pg):
            continue
        try:
            rowid, payload = _full_payload(pages, pg, co)
            out.append((rowid, payload))
        except Exception:
            continue
    return out


def walk_table(pages, rootpage):
    """从 rootpage 遍历 table B-tree，返回所有 leaf (rowid, payload)。"""
    rows = []
    stack = [rootpage]
    seen = set()
    while stack:
        pn = stack.pop()
        if pn in seen or pn not in pages:
            continue
        seen.add(pn)
        pg = pages[pn]
        base = 100 if pn == 1 else 0
        if base >= len(pg):
            continue
        t = pg[base]
        if t == 0x0D:  # leaf table
            rows += _leaf_cells(pages, pg, pn)
        elif t == 0x05:  # interior table
            n = int.from_bytes(pg[base + 3:base + 5], "big")
            hdr = base + 12
            for i in range(n):
                po = hdr + i * 2
                if po + 2 > len(pg):
                    break
                co = int.from_bytes(pg[po:po + 2], "big")
                if co and co + 4 <= len(pg):
                    stack.append(int.from_bytes(pg[co:co + 4], "big"))
            rp = int.from_bytes(pg[base + 8:base + 12], "big")
            if rp:
                stack.append(rp)
    return rows


def find_master_rows(pages):
    """扫所有 leaf page 找 sqlite_master 行 (type,name,tbl_name,rootpage,sql)。
    返回 {name: rootpage}。"""
    schema = {}
    for pn, pg in pages.items():
        base = 100 if pn == 1 else 0
        if base >= len(pg) or pg[base] != 0x0D:
            continue
        for rowid, payload in _leaf_cells(pages, pg, pn):
            v = parse_record(payload)
            if v and len(v) >= 5 and v[0] in (b"table", b"index") and isinstance(v[1], bytes) \
               and isinstance(v[3], int):
                schema[v[1]] = v[3]
    return schema
