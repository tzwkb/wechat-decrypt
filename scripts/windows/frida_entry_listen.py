#!/usr/bin/env python3
# Attach an already-running WeChat, hook sha512_block ENTRY (0x5129f80, rdx=input block), and listen for
# HMAC ipad/opad blocks ((key XOR 0x36/0x5c) || pad). Any db PBKDF2 / page-MAC HMAC_Init exposes a key.
# Usage: python frida_entry_listen.py <pid>
import frida, sys, time

pid = int(sys.argv[1])
session = frida.attach(pid)
JS = r"""
var m = Process.findModuleByName("Weixin.dll");
var entry = m.base.add(0x5129f80);
function checkPad(p, pad) {
  try { var b = new Uint8Array(p.readByteArray(128)); for (var j=32;j<128;j++) if (b[j]!==pad) return null;
    var s=""; for (var k=0;k<32;k++) s+=('0'+(b[k]^pad).toString(16)).slice(-2); return s; } catch(e){ return null; }
}
var hits = {}, n = 0;
Interceptor.attach(entry, {
  onEnter: function(){
    n++;
    var in_ = this.context.rdx;
    var ip = checkPad(in_, 0x36); if (ip && !hits[ip]) { hits[ip]=1; send("*** KEY via ipad: " + ip); }
    var op = checkPad(in_, 0x5c); if (op && !hits["o"+op]) { hits["o"+op]=1; send("*** KEY via opad: " + op); }
  }
});
send("hooked entry; listening 50s for ipad/opad (db PBKDF2 / page-MAC)");
setTimeout(function(){ send("entry_calls=" + n + " distinct_keys=" + Object.keys(hits).length); }, 50000);
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
time.sleep(55)
print("done")
