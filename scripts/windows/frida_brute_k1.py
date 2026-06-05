#!/usr/bin/env python3
# In-process full brute-force for K1, async (setTimeout batches) so load() doesn't block past the
# frida transport timeout. Streams entropy-prefiltered 32B candidates; Python AES-verifies vs page1.
# Usage: python frida_brute_k1.py <pid> <message_0.db>
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
        for off in range(0, len(d) - 31, 32):
            c = d[off:off + 32]
            if vk1(c):
                print("*** K1 FOUND", c.hex()); found.append(c.hex())

session = frida.attach(pid)
JS = r"""
var ranges = Process.enumerateRanges('rw-').filter(function(r){ return r.size <= 32*1024*1024; });
send("brute " + ranges.length + " ranges async");
var ridx = 0, bytesok = 0, candcount = 0;
function scanBatch() {
  var end = Math.min(ridx + 25, ranges.length);
  for (; ridx < end; ridx++) {
    var rg = ranges[ridx], off = 0;
    while (off < rg.size) {
      var chunk = Math.min(65536, rg.size - off);
      var buf;
      try { buf = new Uint8Array(rg.base.add(off).readByteArray(chunk)); } catch(e){ off += chunk; continue; }
      if (buf && buf.length) {
        bytesok += buf.length;
        var batch = [];
        for (var i = 0; i + 32 <= buf.length; i += 8) {
          var mm = {}, distinct = 0, nonascii = 0;
          for (var j = 0; j < 32; j++) { var b = buf[i+j]; if(mm[b]===undefined){mm[b]=1;distinct++;} if(b<32||b>126)nonascii++; }
          if (distinct >= 24 && nonascii >= 14) { batch.push(buf.slice(i, i+32)); candcount++; }
        }
        if (batch.length) {
          var blob = new Uint8Array(batch.length * 32);
          for (var y = 0; y < batch.length; y++) blob.set(batch[y], y*32);
          send({d:1}, blob.buffer);
        }
      }
      off += chunk;
    }
  }
  if (ridx < ranges.length) setTimeout(scanBatch, 0);
  else send("bytes_read=" + bytesok + " candidates=" + candcount + " DONE_SCAN");
}
setTimeout(scanBatch, 0);
"""
s = session.create_script(JS)
s.on("message", on_msg)
s.load()
time.sleep(90)
print("RESULT K1=%d" % len(found))
if found:
    print("K1:", found[0])
