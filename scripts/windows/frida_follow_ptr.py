#!/usr/bin/env python3
# Follow pointers out of the codec_ctx (which contains the salt) to reach cipher_ctx where K1 lives.
# Read each 8-byte word around every salt hit as a pointer, dereference, dump 160 bytes, AES-search K1.
# Usage: python frida_follow_ptr.py <pid> <message_0.db>
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
        for off in range(0, len(d) - 31):
            if vk1(d[off:off + 32]):
                print("*** K1 FOUND", d[off:off + 32].hex()); found.append(d[off:off + 32].hex())

session = frida.attach(pid)
JS = r"""
var pat = "SALTHEX".match(/../g).join(' ');
var salts = [];
Process.enumerateRanges('rw-').forEach(function(rg){
  try { Memory.scanSync(rg.base, rg.size, pat).forEach(function(r){ salts.push(r.address); }); } catch(e){}
});
send("salt at " + salts.length + " addrs; following codec_ctx pointers");
var lo = ptr("0x10000"), hi = ptr("0x7fffffffffff");
salts.forEach(function(sa){
  for (var o = -2048; o <= 2048; o += 8) {
    try {
      var p = sa.add(o).readPointer();
      if (!p.isNull() && p.compare(lo) > 0 && p.compare(hi) < 0) {
        var blk = p.readByteArray(160);
        if (blk) send({d:1}, blk);
        // one more hop: pointers inside that block may point to cipher_ctx
        for (var q = 0; q <= 64; q += 8) {
          try {
            var p2 = p.add(q).readPointer();
            if (!p2.isNull() && p2.compare(lo) > 0 && p2.compare(hi) < 0) {
              var blk2 = p2.readByteArray(160); if (blk2) send({d:1}, blk2);
            }
          } catch(e){}
        }
      }
    } catch(e){}
  }
});
send("DONE");
""".replace("SALTHEX", page1[:16].hex())
s = session.create_script(JS)
s.on("message", on_msg)
s.load()
time.sleep(10)
print("K1 found:", len(found))
if found:
    print("K1:", found[0])
