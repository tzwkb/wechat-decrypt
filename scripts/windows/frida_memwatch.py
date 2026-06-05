#!/usr/bin/env python3
# AOB step 2: MemoryAccessMonitor on the kdf_iter string. When WeChat opens a db and SQLCipher's
# codec touches that string, capture the accessing instruction (-> SQLCipher codec code), from which
# we trace to the key-setting function. Race-attach the main process to catch db opens.
# Usage: python frida_memwatch.py [seconds]
import frida, subprocess, time, sys

EXE = r"C:\Program Files\Tencent\Weixin\Weixin.exe"
secs = int(sys.argv[1]) if len(sys.argv) > 1 else 40

subprocess.run(["taskkill", "/F", "/IM", "Weixin.exe"], capture_output=True)
time.sleep(2)
subprocess.Popen(["cmd", "/c", "start", "", EXE])

def big():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-Process Weixin -EA SilentlyContinue | Where-Object {$_.WorkingSet64 -gt 28MB} | Sort-Object WorkingSet64 -Descending | Select-Object -First 1 -ExpandProperty Id"],
        capture_output=True, text=True)
    s = r.stdout.strip()
    return int(s) if s.isdigit() else None

dev = frida.get_local_device()
pid = None
for _ in range(400):
    pid = big()
    if pid:
        break
    time.sleep(0.1)
if not pid:
    print("no main Weixin"); sys.exit(1)
print("attaching main pid:", pid)
session = dev.attach(pid)

JS = r"""
function s2p(s){ var o=[]; for(var i=0;i<s.length;i++) o.push(('0'+s.charCodeAt(i).toString(16)).slice(-2)); return o.join(' '); }
var m = Process.findModuleByName("Weixin.dll");
var hits = Memory.scanSync(m.base, m.size, s2p("kdf_iter"));
if(!hits.length){ send("kdf_iter NOT found"); }
else {
  var target = hits[0].address;
  send("monitoring kdf_iter @ " + target + " base=" + m.base);
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
  send("monitor armed");
}
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
print("armed; waiting", secs, "s for db opens to touch kdf_iter...")
time.sleep(secs)
print("DONE")
