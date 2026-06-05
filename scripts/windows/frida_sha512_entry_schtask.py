#!/usr/bin/env python3
# Restart WeChat via schtasks (interactive desktop session so it ACTUALLY opens dbs), race-attach, hook
# sha512_block ENTRY (0x5129f80 -- the common entry, called millions of times; rdx = input block).
# Startup PBKDF2 builds the HMAC ipad/opad block exposing the RAW KEY. Usage: python ... [seconds]
import frida, subprocess, time, sys

secs = int(sys.argv[1]) if len(sys.argv) > 1 else 75
subprocess.run(["taskkill", "/F", "/IM", "Weixin.exe"], capture_output=True)
time.sleep(2)
subprocess.run(["schtasks", "/run", "/tn", "WXLaunch"], capture_output=True)

def big():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-Process Weixin -EA SilentlyContinue | Where-Object {$_.WorkingSet64 -gt 25MB} | Sort-Object WorkingSet64 -Descending | Select-Object -First 1 -ExpandProperty Id"],
        capture_output=True, text=True)
    s = r.stdout.strip()
    return int(s) if s.isdigit() else None

dev = frida.get_local_device()
pid = None
for _ in range(1000):
    pid = big()
    if pid:
        break
    time.sleep(0.04)
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
  var hits = {}, n = 0;
  Interceptor.attach(entry, {
    onEnter: function(){
      n++;
      var in_ = this.context.rdx;
      var ip = checkPad(in_, 0x36); if (ip && !hits[ip]) { hits[ip]=1; send("*** KEY via ipad: " + ip); }
      var op = checkPad(in_, 0x5c); if (op && !hits["o"+op]) { hits["o"+op]=1; send("*** KEY via opad: " + op); }
    }
  });
  send("hooked sha512 ENTRY 0x5129f80; waiting startup PBKDF2");
  setTimeout(function(){ send("sha512 entry calls so far: " + n); }, 30000);
}
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
print("hooked; waiting", secs, "s for startup PBKDF2 ipad...")
time.sleep(secs)
print("done")
