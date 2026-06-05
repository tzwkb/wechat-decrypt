#!/usr/bin/env python3
# Hook sha512_block at the K-table lea (rva 0x512a053). On each call, scan ALL 16 general registers'
# pointees for an HMAC ipad/opad block ((key XOR 0x36/0x5c) || pad*96). PBKDF2 deriving the db key
# exposes the RAW KEY (and next PBKDF2 the K1). User opens NEW dbs. Usage: python frida_hook_sha512_v2.py <pid>
import frida, sys, time

pid = int(sys.argv[1])
session = frida.attach(pid)
JS = r"""
var m = Process.findModuleByName("Weixin.dll");
var lea = m.base.add(0x512a053);
function checkPad(p, pad) {
  try {
    var b = new Uint8Array(p.readByteArray(128));
    for (var j = 32; j < 128; j++) if (b[j] !== pad) return null;
    var s = ""; for (var k = 0; k < 32; k++) s += ('0' + (b[k] ^ pad).toString(16)).slice(-2);
    return s;
  } catch(e){ return null; }
}
var hits = {};
Interceptor.attach(lea, {
  onEnter: function(){
    var c = this.context;
    var regs = [c.rax,c.rbx,c.rcx,c.rdx,c.rsi,c.rdi,c.rbp,c.rsp,c.r8,c.r9,c.r10,c.r11,c.r12,c.r13,c.r14,c.r15];
    for (var i = 0; i < regs.length; i++) {
      var ip = checkPad(regs[i], 0x36); if (ip && !hits[ip]) { hits[ip]=1; send("*** KEY via ipad: " + ip); }
      var op = checkPad(regs[i], 0x5c); if (op && !hits["o"+op]) { hits["o"+op]=1; send("*** KEY via opad: " + op); }
    }
  }
});
send("hooked sha512 @ lea 0x512a053; TRIGGER NEW DB NOW");
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
print(">>> HOOKED. In WeChat click the OLDEST chats you never open + search. 70s <<<")
time.sleep(70)
print("done")
