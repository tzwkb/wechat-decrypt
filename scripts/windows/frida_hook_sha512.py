#!/usr/bin/env python3
# Locate sha512_block via xref to the K-table (rva 0x512b200), hook those lea sites, and on each call
# scan registers/stack for an HMAC ipad/opad block ((key XOR 0x36/0x5c) || pad). The PBKDF2 that derives
# the db key reveals the RAW KEY (and the next PBKDF2 reveals K1) at the instant HMAC is built.
# User triggers opening a new db. Usage: python frida_hook_sha512.py <pid>
import frida, sys, time

pid = int(sys.argv[1])
session = frida.attach(pid)
JS = r"""
var m = Process.findModuleByName("Weixin.dll");
var Ktab = m.base.add(0x512b200);
send("K_table @ " + Ktab + "; scanning xrefs...");
var leas = [];
["48 8d", "4c 8d"].forEach(function(op){
  ["05","0d","15","1d","25","2d","35","3d"].forEach(function(mr){
    try { Memory.scanSync(m.base, m.size, op + " " + mr).forEach(function(r){
      try { var I = r.address; var disp = I.add(3).readS32(); if (I.add(7).add(disp).equals(Ktab)) leas.push(I); } catch(e){}
    }); } catch(e){}
  });
});
send("K_table xref lea sites: " + leas.length);
function checkPad(b, pad) {
  for (var j = 32; j < 128; j++) if (b[j] !== pad) return null;
  var s = ""; for (var k = 0; k < 32; k++) s += ('0' + (b[k] ^ pad).toString(16)).slice(-2);
  return s;
}
var hits = {};
leas.forEach(function(L){
  send("  lea @ " + L + " rva=" + L.sub(m.base));
  Interceptor.attach(L, {
    onEnter: function(){
      var c = this.context;
      var regs = [c.rcx, c.rdx, c.r8, c.r9, c.rsp, c.rsi, c.rdi, c.rbx];
      for (var i = 0; i < regs.length; i++) {
        try {
          var b = new Uint8Array(regs[i].readByteArray(128));
          var ip = checkPad(b, 0x36); if (ip && !hits[ip]) { hits[ip]=1; send("*** RAW/KEY via ipad: " + ip); }
          var op = checkPad(b, 0x5c); if (op && !hits["o"+op]) { hits["o"+op]=1; send("*** RAW/KEY via opad: " + op); }
        } catch(e){}
      }
    }
  });
});
send("hooked " + leas.length + " sites; TRIGGER NEW DB NOW");
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
print(">>> HOOKED sha512. Now in WeChat: click OLD chats / search / open Moments-Files. 60s <<<")
time.sleep(60)
print("done")
