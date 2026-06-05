#!/usr/bin/env python3
# Verify the keys captured from HMAC ipad/opad: test each as raw key (PBKDF2->AES page1) and as K1
# (direct AES page1). Usage: python verify_keys.py <key1> <key2> ...
import sys, hashlib, glob
from Crypto.Cipher import AES

db = glob.glob(r"C:\Users\*\Documents\xwechat_files\*\db_storage\message\message_0.db")[0]
page1 = open(db, "rb").read(4096)
salt, iv, ct = page1[:16], page1[4016:4032], page1[16:32]
print("db:", db)
print("salt:", salt.hex())

def hdr_ok(pt):
    return pt[0] == 0x10 and pt[1] == 0x00 and pt[4] == 0x50 and pt[5] == 0x40 and pt[7] == 0x20

for kh in sys.argv[1:]:
    k = bytes.fromhex(kh)
    enc = hashlib.pbkdf2_hmac("sha512", k, salt, 256000, 32)
    pt_raw = AES.new(enc, AES.MODE_CBC, iv).decrypt(ct)
    if hdr_ok(pt_raw):
        print("*** RAW KEY CONFIRMED:", kh)
    pt_k1 = AES.new(k, AES.MODE_CBC, iv).decrypt(ct)
    if hdr_ok(pt_k1):
        print("*** K1 CONFIRMED:", kh)
print("done")
