#!/usr/bin/env python3
# Diagnose why readByteArray returns nothing while scanSync finds the salt. Test BOTH read APIs at
# each salt hit, then dump salt +-4KB via whichever works and AES-search for K1.
# Usage: python frida_diag_read.py <pid> <message_0.db>
import frida, sys, time
from Crypto.Cipher import AES

pid, db = int(sys.argv[1]), sys.argv[2]
page1 = open(db, "rb").read(4096)
salt, iv, ct = page1[:16], page1[4016:4032], page1[16:32]
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
        print("  got %d bytes from dump" % len(d))
        for off in range(0, len(d) - 31, 8):
            if vk1(d[off:off + 32]):
                print("*** K1 FOUND", d[off:off + 32].hex()); found.append(1)

session = frida.attach(pid)
JS = r"""
var pat = "SALTHEX".match(/../g).join(' ');
var addrs = [];
Process.enumerateRanges('rw-').forEach(function(rg){
  try { Memory.scanSync(rg.base, rg.size, pat).forEach(function(r){ addrs.push(r.address); }); } catch(e){}
});
send("salt at " + addrs.length + " addrs");
addrs.forEach(function(a){
  var b1 = "?", b2 = "?";
  try { var x = Memory.readByteArray(a, 64); b1 = x ? x.byteLength : "null"; } catch(e){ b1 = "ERR:" + e; }
  try { var y = a.readByteArray(64); b2 = y ? y.byteLength : "null"; } catch(e){ b2 = "ERR:" + e; }
  send("@" + a + " Memory.readByteArray=" + b1 + " ptr.readByteArray=" + b2);
  try { var big = a.sub(4096).readByteArray(8192); if (big) send({d:1}, big); } catch(e){ send("big read err " + e); }
});
send("DONE");
""".replace("SALTHEX", salt.hex())
s = session.create_script(JS)
s.on("message", on_msg)
s.load()
time.sleep(5)
print("K1 found:", len(found))
