#!/usr/bin/env python3
# Enumerate ALL loaded modules (not just Weixin.dll) for sqlite3/WCDB/SQLCipher exports. WCDB is often
# a separate dll that DOES export sqlite3_key -> hook it to grab the raw key directly.
# Usage: python frida_enum_modules.py <pid>
import frida, sys, time

pid = int(sys.argv[1])
session = frida.attach(pid)
JS = r"""
var mods = Process.enumerateModules();
send("total modules: " + mods.length);
var pat = /sqlite3_key|sqlite3_open|sqlite3_prepare|sqlite3_exec|sqlcipher|wcdb|pbkdf|codec_attach|raw_?key/i;
mods.forEach(function(m){
  try {
    var exps = m.enumerateExports();
    var hits = exps.filter(function(e){ return pat.test(e.name); });
    if (hits.length) {
      send("MODULE " + m.name + " base=" + m.base + " exports=" + exps.length + " -> " + hits.length + " matches:");
      hits.slice(0, 20).forEach(function(e){ send("  EXP " + e.name + " @ " + e.address); });
    } else if (/wcdb|sqlite|cipher/i.test(m.name)) {
      send("MODULE " + m.name + " (name-match, " + exps.length + " exports, 0 sqlite-export)");
    }
  } catch(e){}
});
// also list all module names so we can eyeball db-related ones
send("--- all module names ---");
mods.forEach(function(m){ send(m.name); });
send("DONE");
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
time.sleep(5)
print("done")
