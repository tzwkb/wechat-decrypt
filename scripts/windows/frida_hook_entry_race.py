#!/usr/bin/env python3
# Restart WeChat, race-attach as early as possible (>=18MB, just after Weixin.dll maps, before dbs open),
# hook sha512_block ENTRY (rva 0x5129f80) where rdx = input block. Detect HMAC ipad/opad
# ((key XOR 0x36/0x5c) || pad*96) -> raw key (and K1). Counts calls to confirm the hook fires.
# Usage: python frida_hook_entry_race.py [seconds]
import frida, subprocess, time, sys

EXE = r"C:\Program Files\Tencent\Weixin\Weixin.exe"
secs = int(sys.argv[1]) if len(sys.argv) > 1 else 70

subprocess.run(["taskkill", "/F", "/IM", "Weixin.exe"], capture_output=True)
time.sleep(2)
subprocess.Popen(["cmd", "/c", "start", "", EXE])

def big():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-Process Weixin -EA SilentlyContinue | Where-Object {$_.WorkingSet64 -gt 18MB} | Sort-Object WorkingSet64 -Descending | Select-Object -First 1 -ExpandProperty Id"],
        capture_output=True, text=True)
    s = r.stdout.strip()
    return int(s) if s.isdigit() else None

dev = frida.get_local_device()
pid = None
for _ in range(800):
    pid = big()
    if pid:
        break
    time.sleep(0.05)
if not pid:
    print("no main Weixin"); sys.exit(1)
print("attaching main pid:", pid)
session = dev.attach(pid)
JS = r"""
var m = Process.findModuleByName("Weixin.dll");
if (!m) { send("Weixin.dll not loaded"); }
else {
  var entry = m.base.add(0x5129f80);
  function checkPad(p, pad) {
    try { var b = new Uint8Array(p.readByteArray(128)); for (var j=32;j<128;j++) if (b[j]!==pad) return null;
      var s=""; for (var k=0;k<32;k++) s+=('0'+(b[k]^pad).toString(16)).slice(-2); return s; } catch(e){ return null; }
  }
  var n = 0, hits = {};
  Interceptor.attach(entry, {
    onEnter: function(){
      n++;
      var in_ = this.context.rdx;   // arg1 = input block
      var ip = checkPad(in_, 0x36); if (ip && !hits[ip]) { hits[ip]=1; send("*** KEY via ipad: " + ip); }
      var op = checkPad(in_, 0x5c); if (op && !hits["o"+op]) { hits["o"+op]=1; send("*** KEY via opad: " + op); }
    }
  });
  send("hooked sha512 ENTRY @ 0x5129f80; waiting startup PBKDF2");
  setTimeout(function(){ send("sha512 entry calls so far: " + n); }, 30000);
}
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
print("hooked; waiting", secs, "s...")
time.sleep(secs)
print("done")
