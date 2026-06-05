#!/usr/bin/env python3
# Attach an already-running Weixin pid and enumerate Weixin.dll exports/imports for sqlite3/WCDB/
# OpenSSL functions we could hook. Usage: python frida_enum_dll.py <pid>
import frida, sys, time

pid = int(sys.argv[1])
session = frida.attach(pid)

JS = r"""
var m = Process.findModuleByName("Weixin.dll");
if(!m){ send("NO Weixin.dll module"); }
else {
  var exps = m.enumerateExports();
  send("Weixin.dll total_exports=" + exps.length);
  var pat = /sqlite3|sqlcipher|wcdb|codec|pbkdf|pkcs5|evp_|aes_set|aes_enc|aes_dec|hmac|cipher_key|raw_?key/i;
  var hits=0;
  exps.forEach(function(e){ if(pat.test(e.name)){ hits++; if(hits<=70) send("EXP " + e.name); } });
  send("matched_exports=" + hits);
  // imports too (maybe sqlite3 from a sibling dll)
  var imps = m.enumerateImports();
  var ih=0;
  imps.forEach(function(e){ if(/sqlite3|libssl|libcrypto|wcdb|pbkdf/i.test(e.name)){ ih++; if(ih<=20) send("IMP " + e.name + " <- " + (e.module||"?")); } });
  send("matched_imports=" + ih);
}
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
time.sleep(3)
session.detach()
print("DONE")
