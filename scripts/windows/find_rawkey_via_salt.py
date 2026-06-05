#!/usr/bin/env python3
# Locate the SQLCipher codec ctx by scanning WeChat memory for the KNOWN salt (db page1[0:16]).
# The codec ctx stores salt next to the derived key, so dump the neighborhood and AES-verify each
# 32-byte window as K1 (fast, decrypts that db) / PBKDF2-verify as raw key (works for all dbs).
# No timing/trigger/disasm/spawn needed -- pure scan of a running WeChat.
# Usage: python find_rawkey_via_salt.py <pid> <message_0.db>
import frida, sys, hashlib
from Crypto.Cipher import AES

pid = int(sys.argv[1])
dbpath = sys.argv[2]
with open(dbpath, "rb") as f:
    page1 = f.read(4096)
salt = page1[:16]
iv = page1[4016:4032]
ct = page1[16:32]
print("salt:", salt.hex())

def verify_k1(k):
    try:
        pt = AES.new(k, AES.MODE_CBC, iv).decrypt(ct)
        return pt[0] == 0x10 and pt[1] == 0x00 and pt[4] == 0x50 and pt[5] == 0x40 and pt[7] == 0x20
    except Exception:
        return False

def verify_raw(r):
    try:
        return verify_k1(hashlib.pbkdf2_hmac("sha512", r, salt, 256000, 32))
    except Exception:
        return False

k1_found, raw_found = [], []
def on_msg(msg, data):
    if msg.get("type") == "send" and isinstance(msg.get("payload"), str):
        print(msg["payload"]); return
    if data:
        for off in range(0, len(data) - 31):
            c = data[off:off + 32]
            if not any(c):
                continue
            if verify_k1(c):
                print("*** K1 FOUND off=%d %s" % (off, c.hex())); k1_found.append(c.hex())

session = frida.attach(pid)
JS = r"""
var saltHex = "%s";
var pat = saltHex.match(/../g).join(' ');
var ranges = Process.enumerateRanges('rw-').filter(function(r){ return r.size < 64*1024*1024; });
send("scanning " + ranges.length + " rw- ranges (<64MB) for salt...");
var found = 0;
ranges.forEach(function(rg){
  try {
    Memory.scanSync(rg.base, rg.size, pat).forEach(function(r){
      found++;
      for (var d = -8192; d <= 8192; d += 4096) {
        try { send({nb:1}, r.address.add(d).readByteArray(4096)); } catch(e){}
      }
      send("SALT @ " + r.address);
    });
  } catch(e){}
});
send("salt_hits=" + found);
""" % salt.hex()
s = session.create_script(JS)
s.on("message", on_msg)
s.load()
import time
time.sleep(8)
print("RESULTS: K1=%d RAWKEY=%d" % (len(k1_found), len(raw_found)))
if k1_found:
    print("K1:", k1_found[0])
if raw_found:
    print("RAWKEY:", raw_found[0])
