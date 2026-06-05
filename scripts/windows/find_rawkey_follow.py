#!/usr/bin/env python3
# Find the RAW KEY (not K1) in the SQLCipher codec_ctx: codec_ctx holds the `pass` field (= raw key)
# next to kdf_salt. Scan for salt, then check 32B windows inline AND behind each pointer near salt via
# PBKDF2(candidate, salt, 256000)->AES page1 verify. Few candidates -> PBKDF2 cost is affordable.
# Usage: python find_rawkey_follow.py <pid> <message_0.db>
import frida, sys, time, hashlib
from Crypto.Cipher import AES

pid, db = int(sys.argv[1]), sys.argv[2]
page1 = open(db, "rb").read(4096)
salt, iv, ct = page1[:16], page1[4016:4032], page1[16:32]
found = []
checked = [0]

def vraw(r):
    if len(r) != 32 or not any(r):
        return False
    try:
        k = hashlib.pbkdf2_hmac("sha512", r, salt, 256000, 32)
        pt = AES.new(k, AES.MODE_CBC, iv).decrypt(ct)
        return pt[0] == 0x10 and pt[1] == 0x00 and pt[4] == 0x50 and pt[5] == 0x40 and pt[7] == 0x20
    except Exception:
        return False

def on_msg(m, d):
    if m.get("type") == "send" and isinstance(m.get("payload"), str):
        print(m["payload"]); return
    if d:
        for off in range(0, len(d) - 31, 8):
            checked[0] += 1
            if vraw(d[off:off + 32]):
                print("*** RAW KEY FOUND", d[off:off + 32].hex()); found.append(d[off:off + 32].hex())

session = frida.attach(pid)
JS = r"""
var pat = "SALTHEX".match(/../g).join(' ');
var salts = [];
Process.enumerateRanges('rw-').forEach(function(rg){
  try { Memory.scanSync(rg.base, rg.size, pat).forEach(function(r){ salts.push(r.address); }); } catch(e){}
});
send("salt at " + salts.length + " addrs; searching codec_ctx pass (raw key)");
salts.forEach(function(sa){
  try { var inl = sa.sub(256).readByteArray(512); if (inl) send({d:1}, inl); } catch(e){}
  for (var o = -256; o <= 256; o += 8) {
    try {
      var p = sa.add(o).readPointer();
      if (!p.isNull() && p.compare(ptr("0x10000")) > 0 && p.compare(ptr("0x7fffffffffff")) < 0) {
        var t = p.readByteArray(64); if (t) send({d:1}, t);
      }
    } catch(e){}
  }
});
send("DONE");
""".replace("SALTHEX", salt.hex())
s = session.create_script(JS)
s.on("message", on_msg)
s.load()
time.sleep(100)
print("checked %d windows; RAW KEY found: %d" % (checked[0], len(found)))
if found:
    print("RAW KEY:", found[0])
