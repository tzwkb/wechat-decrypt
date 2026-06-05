#!/usr/bin/env python3
# End-to-end verify on Windows: decrypt message_0.db with the captured raw key (pure pycryptodome
# SQLCipher v4) and read messages with builtin sqlite3. Usage: python decrypt_read.py <raw_key_hex>
import sys, hashlib, glob, sqlite3, os
from Crypto.Cipher import AES

raw = bytes.fromhex(sys.argv[1].strip())
db = glob.glob(r"C:\Users\*\Documents\xwechat_files\*\db_storage\message\message_0.db")[0]
data = open(db, "rb").read()
PAGE, RESERVE = 4096, 80
salt = data[:16]
enc = hashlib.pbkdf2_hmac("sha512", raw, salt, 256000, 32)
n = len(data) // PAGE
out = bytearray()
rstart = PAGE - RESERVE
for i in range(n):
    page = data[i * PAGE:(i + 1) * PAGE]
    start = 16 if i == 0 else 0
    ct = page[start:rstart]
    iv = page[rstart:rstart + 16]
    dec = AES.new(enc, AES.MODE_CBC, iv).decrypt(ct)
    out += (b"SQLite format 3\x00" + dec + page[rstart:]) if i == 0 else (dec + page[rstart:])

dst = r"C:\Users\claude\_dec_msg0.db"
open(dst, "wb").write(out)
try:
    con = sqlite3.connect(dst)
    n2i = con.execute("SELECT count(*) FROM Name2Id").fetchone()[0]
    msgtabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
    total = sum(con.execute("SELECT count(*) FROM " + t).fetchone()[0] for t in msgtabs)
    print("Name2Id (会话数):", n2i)
    print("Msg 表数:", len(msgtabs))
    print("消息总数:", total)
    sample = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%' LIMIT 3").fetchall()
    print("Msg 表样例:", [r[0] for r in sample])
    con.close()
    print(">>> WINDOWS DECRYPT + READ VERIFIED <<<")
finally:
    if os.path.exists(dst):
        os.remove(dst)
