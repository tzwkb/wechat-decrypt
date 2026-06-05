#!/usr/bin/env python3
# Catch the raw key at the instant sqlite3_key copies it: hook RtlAllocateHeap, keep a ring buffer of
# recent small allocations (32/48/64B = the pass copy). User clicks OLD chats to make WeChat open new
# dbs (-> sqlite3_key -> malloc+memcpy raw key); then we dump the ring and PBKDF2-verify.
# Usage: python frida_hook_alloc.py <pid> <message_0.db>
import frida, sys, time, hashlib
from Crypto.Cipher import AES

pid, db = int(sys.argv[1]), sys.argv[2]
page1 = open(db, "rb").read(4096)
SALT, IV, CT = page1[:16], page1[4016:4032], page1[16:32]
blocks = []

def vraw(r):
    try:
        k = hashlib.pbkdf2_hmac("sha512", r, SALT, 256000, 32)
        pt = AES.new(k, AES.MODE_CBC, IV).decrypt(CT)
        return pt[0] == 0x10 and pt[1] == 0x00 and pt[4] == 0x50 and pt[5] == 0x40 and pt[7] == 0x20
    except Exception:
        return False

def on_msg(m, d):
    if m.get("type") == "send" and isinstance(m.get("payload"), str):
        print(m["payload"]); return
    if d:
        blocks.append(bytes(d))

session = frida.attach(pid)
JS = r"""
var recs = [];
var alloc = Module.findGlobalExportByName('RtlAllocateHeap');
Interceptor.attach(alloc, {
  onEnter: function(a){ this.sz = a[2].toInt32(); },
  onLeave: function(r){
    if (!r.isNull() && (this.sz === 32 || this.sz === 33 || this.sz === 48 || this.sz === 64 || this.sz === 66)) {
      recs.push([r, this.sz]);
      if (recs.length > 4000) recs.shift();
    }
  }
});
send("hooked RtlAllocateHeap; recording small allocs (ring 4000)");
rpc.exports = {
  dump: function(){
    send("ring has " + recs.length + " allocs; reading contents");
    recs.forEach(function(rec){ try { var b = rec[0].readByteArray(rec[1]); if (b) send({d:1}, b); } catch(e){} });
    return recs.length;
  }
};
"""
s = session.create_script(JS)
s.on("message", on_msg)
s.load()
print(">>> HOOKED. Now click several OLD chats in WeChat (open new message dbs). 45s window. <<<")
time.sleep(45)
s.exports_sync.dump()
time.sleep(8)
print("checking %d blocks for raw key..." % len(blocks))
found = []
for b in blocks:
    for off in range(0, len(b) - 31, 1):
        c = b[off:off + 32]
        if any(c) and vraw(c):
            print("*** RAW KEY FOUND", c.hex()); found.append(c.hex())
print("RESULT raw_keys=%d" % len(found))
if found:
    print("RAW KEY:", found[0])
