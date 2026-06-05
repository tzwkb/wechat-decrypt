#!/usr/bin/env python3
# Attach existing Weixin, arm MemoryAccessMonitor on kdf_iter. User manually clicks chats in the VM
# so WeChat opens dbs / its codec touches kdf_iter; we capture the accessing instruction (codec code)
# -> from there we locate the key function. Usage: python frida_memwatch_attach.py <pid> [seconds]
import frida, sys, time

pid = int(sys.argv[1])
secs = int(sys.argv[2]) if len(sys.argv) > 2 else 120
session = frida.attach(pid)

JS = r"""
function s2p(s){ var o=[]; for(var i=0;i<s.length;i++) o.push(('0'+s.charCodeAt(i).toString(16)).slice(-2)); return o.join(' '); }
var m = Process.findModuleByName("Weixin.dll");
var hits = Memory.scanSync(m.base, m.size, s2p("kdf_iter"));
if(!hits.length){ send("kdf_iter NOT found"); }
else {
  var target = hits[0].address;
  send("monitoring kdf_iter @ " + target + " rva=" + target.sub(m.base));
  var seen = {};
  MemoryAccessMonitor.enable([{ base: target, size: 8 }], {
    onAccess: function(d){
      try {
        if (d.address.compare(target) >= 0 && d.address.compare(target.add(8)) < 0) {
          var f = d.from.toString();
          if (!seen[f]) { seen[f] = 1;
            var insn = ""; try { insn = Instruction.parse(d.from).toString(); } catch(e){}
            send("KDF_XREF from=" + f + " rva=" + d.from.sub(m.base) + " op=" + d.operation + " insn=[" + insn + "]");
          }
        }
      } catch(e){ send("onAccess err " + e); }
    }
  });
  send("ARMED -- click chats in WeChat now");
}
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
print("armed; waiting", secs, "s (user clicks chats to trigger)...")
time.sleep(secs)
print("DONE")
