#!/usr/bin/env python3
# Locate K1 via the kdf_iter=256000 (0x3E800) field inside the SQLCipher codec ctx: K1 lives in the
# same ctx struct. Scan rw- for the constant, dump +-2KB around each hit (ptr.readByteArray), AES-search.
# Usage: python frida_find_via_kdfiter.py <pid> <message_0.db>
import frida, sys, time
from Crypto.Cipher import AES

pid, db = int(sys.argv[1]), sys.argv[2]
page1 = open(db, "rb").read(4096)
iv, ct = page1[4016:4032], page1[16:32]
found = []

def vk1(k):
    try:
        pt = AES.new(k, AES.MODE_CBC, iv).decrypt(ct)
        return pt[0] == 0x10 and pt[1] == 0x00 and pt[4] == 0x50 and pt[5] == 0x40 and pt[7] == 0x20
    except Exception:
        return False

def on_msg(m, d):
    if m.get("type") == "send" and isinstance(m.get("payload"), str):
        print(m["payload"]); return
    if d:
        for off in range(0, len(d) - 31, 4):
            if vk1(d[off:off + 32]):
                print("*** K1 FOUND", d[off:off + 32].hex()); found.append(d[off:off + 32].hex())

session = frida.attach(pid)
JS = r"""
var hits = [];
Process.enumerateRanges('rw-').forEach(function(rg){
  try { Memory.scanSync(rg.base, rg.size, "00 e8 03 00").forEach(function(r){ hits.push(r.address); }); } catch(e){}
});
send("kdf_iter const 256000 at " + hits.length + " rw- addrs; dumping +-2KB each");
hits.forEach(function(a){
  try { var b = a.sub(2048).readByteArray(4096); if (b) send({d:1}, b); } catch(e){}
});
send("DONE");
""".replace("X", "X")
s = session.create_script(JS)
s.on("message", on_msg)
s.load()
time.sleep(8)
print("K1 found:", len(found))
if found:
    print("K1:", found[0])
