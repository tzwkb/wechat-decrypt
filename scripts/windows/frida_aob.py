#!/usr/bin/env python3
# AOB recon step 1: locate SQLCipher / key-derivation code inside Weixin.dll by scanning for
# SQLCipher PRAGMA strings and the kdf_iter=256000 constant (0x0003E800). The hits anchor where
# the raw key flows through, so we can pick a hook point next. Usage: python frida_aob.py <pid>
import frida, sys, time

pid = int(sys.argv[1])
session = frida.attach(pid)

JS = r"""
var m = Process.findModuleByName("Weixin.dll");
send("Weixin.dll base=" + m.base + " size=" + m.size);
function s2p(s){ var o=[]; for(var i=0;i<s.length;i++){ o.push(('0'+s.charCodeAt(i).toString(16)).slice(-2)); } return o.join(' '); }
["kdf_iter","cipher_compatibility","cipher_page_size","HMAC_SHA512","cipher_hmac_algorithm","PRAGMA key","sqlite3","SQLCipher","wxSQLite3"].forEach(function(sv){
    try { var r=Memory.scanSync(m.base, m.size, s2p(sv)); if(r.length) send("STR '"+sv+"' x"+r.length+" @ "+r[0].address); }
    catch(e){}
});
// kdf iteration constant 256000 = 0x0003E800 -> LE bytes 00 e8 03 00
try { var c=Memory.scanSync(m.base, m.size, "00 e8 03 00"); send("const_256000 x"+c.length+(c.length?(" first@"+c[0].address):"")); } catch(e){ send("c256k_err "+e); }
send("SCAN_DONE");
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
time.sleep(3)
session.detach()
print("DONE")
