#!/usr/bin/env python3
# Full brute-force for K1 via rpc: Python drives JS one range at a time (no single load() that can time
# out, no size filter -> covers large heaps too). ptr.readByteArray in 256KB chunks. AES-verify vs page1.
# Usage: python frida_brute_rpc.py <pid> <message_0.db>
import frida, sys
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

session = frida.attach(pid)
JS = r"""
rpc.exports = {
  getRanges: function(){
    return Process.enumerateRanges('rw-').map(function(r){ return [r.base.toString(), r.size]; });
  },
  scanRange: function(baseStr, size){
    var base = ptr(baseStr), off = 0, cands = [];
    while (off < size) {
      var chunk = Math.min(262144, size - off), buf;
      try { buf = new Uint8Array(base.add(off).readByteArray(chunk)); } catch(e){ off += chunk; continue; }
      if (buf && buf.length) {
        for (var i = 0; i + 32 <= buf.length; i += 8) {
          var mm = {}, dist = 0, na = 0;
          for (var j = 0; j < 32; j++) { var b = buf[i+j]; if(mm[b]===undefined){mm[b]=1;dist++;} if(b<32||b>126)na++; }
          if (dist >= 22 && na >= 12) cands.push(buf.slice(i, i+32));
        }
      }
      off += chunk;
    }
    var blob = new Uint8Array(cands.length * 32);
    for (var y = 0; y < cands.length; y++) blob.set(cands[y], y*32);
    return blob.buffer;
  }
};
"""
s = session.create_script(JS)
s.load()
ranges = s.exports_sync.get_ranges()
print("scanning %d rw- ranges via rpc (no size filter)" % len(ranges))
total = 0
for idx, (base, size) in enumerate(ranges):
    try:
        blob = s.exports_sync.scan_range(base, size)
    except Exception:
        continue
    if blob:
        b = bytes(blob)
        total += len(b) // 32
        for off in range(0, len(b) - 31, 32):
            if vk1(b[off:off + 32]):
                print("*** K1 FOUND", b[off:off + 32].hex()); found.append(b[off:off + 32].hex())
        if found:
            break
    if idx % 200 == 0:
        print("  ...%d/%d ranges, %d candidates checked" % (idx, len(ranges), total))
print("RESULT total_candidates=%d K1=%d" % (total, len(found)))
if found:
    print("K1:", found[0])
