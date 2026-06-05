#!/usr/bin/env python3
# Thorough raw-key search: collect 32B candidates from salt +-2KB inline AND behind every pointer near
# salt (codec_ctx -> cipher_ctx.pass), dedupe, then verify in parallel with a process Pool
# (PBKDF2-HMAC-SHA512 x256000 -> AES page1). Usage: python find_rawkey_v2.py <pid> <message_0.db>
import frida, sys, time, hashlib
from Crypto.Cipher import AES
from multiprocessing import Pool

pid, db = int(sys.argv[1]), sys.argv[2]
page1 = open(db, "rb").read(4096)
SALT, IV, CT = page1[:16], page1[4016:4032], page1[16:32]

def vraw(r):
    try:
        k = hashlib.pbkdf2_hmac("sha512", r, SALT, 256000, 32)
        pt = AES.new(k, AES.MODE_CBC, IV).decrypt(CT)
        if pt[0] == 0x10 and pt[1] == 0x00 and pt[4] == 0x50 and pt[5] == 0x40 and pt[7] == 0x20:
            return r.hex()
    except Exception:
        pass
    return None

cands = set()
def on_msg(m, d):
    if m.get("type") == "send" and isinstance(m.get("payload"), str):
        print(m["payload"]); return
    if d:
        for off in range(0, len(d) - 31, 8):
            c = d[off:off + 32]
            if any(c):
                cands.add(c)

if __name__ == "__main__":
    session = frida.attach(pid)
    JS = r"""
    var pat = "SALTHEX".match(/../g).join(' ');
    var salts = [];
    Process.enumerateRanges('rw-').forEach(function(rg){
      try { Memory.scanSync(rg.base, rg.size, pat).forEach(function(r){ salts.push(r.address); }); } catch(e){}
    });
    send("salt at " + salts.length + " addrs; collecting inline + pointer targets");
    salts.forEach(function(sa){
      try { var inl = sa.sub(2048).readByteArray(4096); if (inl) send({d:1}, inl); } catch(e){}
      for (var o = -2048; o <= 2048; o += 8) {
        try {
          var p = sa.add(o).readPointer();
          if (!p.isNull() && p.compare(ptr("0x10000")) > 0 && p.compare(ptr("0x7fffffffffff")) < 0) {
            var t = p.readByteArray(256); if (t) send({d:1}, t);
          }
        } catch(e){}
      }
    });
    send("DONE");
    """.replace("SALTHEX", SALT.hex())
    s = session.create_script(JS)
    s.on("message", on_msg)
    s.load()
    time.sleep(15)
    try:
        session.detach()
    except Exception:
        pass
    cl = list(cands)
    print("collected %d unique candidates; parallel PBKDF2 verify..." % len(cl))
    found = []
    with Pool() as pool:
        for res in pool.imap_unordered(vraw, cl, chunksize=40):
            if res:
                print("*** RAW KEY FOUND", res); found.append(res)
    print("RESULT raw_keys=%d" % len(found))
    if found:
        print("RAW KEY:", found[0])
