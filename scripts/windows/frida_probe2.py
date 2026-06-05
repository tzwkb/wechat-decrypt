#!/usr/bin/env python3
# Enumerate Weixin.dll exports to find sqlite3 / WCDB / SQLCipher / OpenSSL functions we could hook
# (sqlite3_key -> raw key; sqlite3_step/column -> plaintext rows, bypassing key extraction entirely).
import frida, subprocess, time, sys

EXE = r"C:\Program Files\Tencent\Weixin\Weixin.exe"
subprocess.run(["taskkill", "/F", "/IM", "Weixin.exe"], capture_output=True)
time.sleep(2)
subprocess.Popen(["cmd", "/c", "start", "", EXE])

def big():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-Process Weixin -EA SilentlyContinue | Where-Object {$_.WorkingSet64 -gt 60MB} | Sort-Object WorkingSet64 -Descending | Select-Object -First 1 -ExpandProperty Id"],
        capture_output=True, text=True)
    s = r.stdout.strip()
    return int(s) if s.isdigit() else None

dev = frida.get_local_device()
pid = None
for _ in range(300):
    pid = big()
    if pid:
        break
    time.sleep(0.2)
if not pid:
    print("no main Weixin"); sys.exit(1)
print("attached main pid:", pid)
session = dev.attach(pid)

JS = r"""
var m = Process.findModuleByName("Weixin.dll");
if(!m){ send("NO Weixin.dll module"); }
else {
  var exps = m.enumerateExports();
  send("Weixin.dll base="+m.base+" total_exports="+exps.length);
  var pat = /sqlite3|sqlcipher|codec|pbkdf|pkcs5|evp_|aes_set|aes_enc|aes_dec|hmac|wcdb|key|cipher/i;
  var hits=0;
  exps.forEach(function(e){
    if(pat.test(e.name)){ hits++; if(hits<=80) send("EXP "+e.name); }
  });
  send("matched_exports="+hits);
  // also check imports for OpenSSL/sqlite from other dlls
  var imps = m.enumerateImports();
  var ih=0;
  imps.forEach(function(e){
    if(/sqlite3|ssl|crypto|pbkdf/i.test(e.name)){ ih++; if(ih<=20) send("IMP "+e.name+" <- "+(e.module||"")); }
  });
  send("matched_imports="+ih);
}
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
time.sleep(3)
session.detach()
print("DONE")
