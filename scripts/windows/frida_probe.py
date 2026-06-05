#!/usr/bin/env python3
# frida probe: attach a Weixin.exe, enumerate modules + look for SQLCipher/crypto hook points.
# Usage: python frida_probe.py [pid]   (default: first Weixin.exe)
import frida, sys, time

pid = int(sys.argv[1]) if len(sys.argv) > 1 else None
if pid is None:
    ps = [p.pid for p in frida.enumerate_processes() if p.name.lower() == "weixin.exe"]
    pid = ps[0] if ps else None
print("attach pid:", pid)

session = frida.attach(pid)

JS = r"""
send("modules=" + Process.enumerateModules().length);
Process.enumerateModules().forEach(function(m){
    if(/weixin|sqlite|cipher|crypt|mm|wx|ssl|tls|xlog|common/i.test(m.name))
        send("MOD " + m.name + " base=" + m.base + " size=" + m.size);
});
// direct exports (works only if dynamically exported)
["sqlite3_key","sqlite3_key_v2","sqlite3_rekey","sqlcipher_export","sqlite3_open"].forEach(function(n){
    var a=null; try{ a=Module.findExportByName(null,n); }catch(e){}
    send("exp " + n + "=" + a);
});
// scan main module exports for crypto-ish names
try {
  var main = Process.enumerateModules()[0];
  var hit=0;
  main.enumerateExports().forEach(function(e){
    if(/sqlite|cipher|crypt|pbkdf|aes|hmac|codec|kdf/i.test(e.name) && hit<40){ hit++; send("MAINEXP " + e.name + " @ " + e.address); }
  });
  send("main_module=" + main.name + " crypto_exports=" + hit);
} catch(e) { send("mainexp_err " + e); }
"""
out = []
s = session.create_script(JS)
s.on("message", lambda m, d: out.append(m.get("payload", str(m))))
s.load()
time.sleep(2.0)
for o in out:
    print(o)
session.detach()
print("DONE")
