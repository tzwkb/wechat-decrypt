#!/usr/bin/env python3
# AOB step 2 (static): find xrefs to the kdf_iter string by scanning Weixin.dll for
# `lea reg, [rip+disp32]` whose computed target == kdf_iter address. Locates SQLCipher codec code
# without runtime triggering. Usage: python frida_xref.py <pid>
import frida, sys, time

pid = int(sys.argv[1])
session = frida.attach(pid)

JS = r"""
function s2p(s){ var o=[]; for(var i=0;i<s.length;i++) o.push(('0'+s.charCodeAt(i).toString(16)).slice(-2)); return o.join(' '); }
var m = Process.findModuleByName("Weixin.dll");
var hits = Memory.scanSync(m.base, m.size, s2p("kdf_iter"));
if(!hits.length){ send("kdf_iter NOT found"); }
else {
  var T = hits[0].address;
  send("kdf_iter @ " + T + " rva=" + T.sub(m.base));
  // lea reg,[rip+disp32] = 48 8d <modrm> disp32, modrm in {05,0d,15,1d,25,2d,35,3d} (mod=00,rm=101)
  var modrms = ["05","0d","15","1d","25","2d","35","3d"];
  var total = 0;
  ["48 8d","4c 8d"].forEach(function(op){
    modrms.forEach(function(mr){
      try {
        var res = Memory.scanSync(m.base, m.size, op + " " + mr);
        res.forEach(function(r){
          try {
            var I = r.address;
            var disp = I.add(3).readS32();
            var tgt = I.add(7).add(disp);
            if (tgt.equals(T)) { total++; send("XREF " + op + " @ " + I + " rva=" + I.sub(m.base)); }
          } catch(e){}
        });
      } catch(e){}
    });
  });
  send("total_lea_xrefs=" + total);
  // pointer to kdf_iter (pragma-name table entry in .rdata)
  try {
    var pr = Memory.scanSync(m.base, m.size, T.toMatchPattern());
    send("ptr_to_kdf_iter x" + pr.length);
    pr.slice(0,6).forEach(function(r){ send("PTR @ " + r.address + " rva=" + r.address.sub(m.base)); });
  } catch(e){ send("ptr scan err " + e); }
}
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
time.sleep(2)
session.detach()
print("DONE")
