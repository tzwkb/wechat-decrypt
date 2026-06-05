#!/usr/bin/env python3
# Locate the internal SHA-512 implementation in Weixin.dll by scanning for its round constants K[] and
# initial hash H[]. From there we can hook SHA-512 and recover the raw key from the PBKDF2 HMAC ipad
# block (raw_key XOR 0x36 || 0x36*96). Usage: python frida_find_sha512.py <pid>
import frida, sys, time

pid = int(sys.argv[1])
session = frida.attach(pid)
JS = r"""
var m = Process.findModuleByName("Weixin.dll");
send("Weixin.dll base=" + m.base + " size=" + m.size);
// SHA-512 round constants (stored little-endian)
var consts = {
  "K0=0x428a2f98d728ae22": "22 ae 28 d7 98 2f 8a 42",
  "K1=0x7137449123ef65cd": "cd 65 ef 23 91 44 37 71",
  "K2=0xb5c0fbcfec4d3b2f": "2f 3b 4d ec cf fb c0 b5",
  "Klast=0x6c44198c4a475817": "17 58 47 4a 8c 19 44 6c",
  "H0=0x6a09e667f3bcc908": "08 c9 bc f3 67 e6 09 6a",
  "H1=0xbb67ae8584caa73b": "3b a7 ca 84 85 ae 67 bb"
};
Object.keys(consts).forEach(function(name){
  try {
    var r = Memory.scanSync(m.base, m.size, consts[name]);
    send(name + " x" + r.length + (r.length ? (" @ " + r[0].address + " rva=" + r[0].address.sub(m.base)) : ""));
  } catch(e){ send(name + " scan err " + e); }
});
send("DONE");
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
time.sleep(8)
print("done")
