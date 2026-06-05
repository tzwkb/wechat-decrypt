#!/usr/bin/env python3
# Restart WeChat and race-attach, then hook sha512_block (rva 0x512a053). On startup WeChat opens its
# dbs -> PBKDF2 derives keys; the HMAC ipad/opad block exposes the RAW KEY (same for every db). No user
# action needed. Usage: python frida_sha512_race.py [seconds]
import frida, subprocess, time, sys

EXE = r"C:\Program Files\Tencent\Weixin\Weixin.exe"
secs = int(sys.argv[1]) if len(sys.argv) > 1 else 70

subprocess.run(["taskkill", "/F", "/IM", "Weixin.exe"], capture_output=True)
time.sleep(2)
subprocess.Popen(["cmd", "/c", "start", "", EXE])

def big():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-Process Weixin -EA SilentlyContinue | Where-Object {$_.WorkingSet64 -gt 25MB} | Sort-Object WorkingSet64 -Descending | Select-Object -First 1 -ExpandProperty Id"],
        capture_output=True, text=True)
    s = r.stdout.strip()
    return int(s) if s.isdigit() else None

dev = frida.get_local_device()
pid = None
for _ in range(500):
    pid = big()
    if pid:
        break
    time.sleep(0.1)
if not pid:
    print("no main Weixin"); sys.exit(1)
print("attaching main pid:", pid)
session = dev.attach(pid)
JS = r"""
var m = Process.findModuleByName("Weixin.dll");
if (!m) { send("Weixin.dll not loaded yet"); }
else {
  var lea = m.base.add(0x512a053);
  function checkPad(p, pad) {
    try { var b = new Uint8Array(p.readByteArray(128)); for (var j=32;j<128;j++) if (b[j]!==pad) return null;
      var s=""; for (var k=0;k<32;k++) s+=('0'+(b[k]^pad).toString(16)).slice(-2); return s; } catch(e){ return null; }
  }
  var hits = {};
  Interceptor.attach(lea, {
    onEnter: function(){
      var c = this.context;
      var regs = [c.rax,c.rbx,c.rcx,c.rdx,c.rsi,c.rdi,c.rbp,c.rsp,c.r8,c.r9,c.r10,c.r11,c.r12,c.r13,c.r14,c.r15];
      for (var i=0;i<regs.length;i++) {
        var ip = checkPad(regs[i], 0x36); if (ip && !hits[ip]) { hits[ip]=1; send("*** KEY via ipad: " + ip); }
        var op = checkPad(regs[i], 0x5c); if (op && !hits["o"+op]) { hits["o"+op]=1; send("*** KEY via opad: " + op); }
      }
    }
  });
  send("hooked sha512 @ lea 0x512a053; waiting for startup db PBKDF2");
}
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
print("hooked early; waiting", secs, "s for WeChat startup PBKDF2...")
time.sleep(secs)
print("done")
