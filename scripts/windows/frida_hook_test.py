#!/usr/bin/env python3
# Diagnostic: attach a NORMALLY-running WeChat and count calls to sha512_block entry (0x5129f80) and the
# scalar-path lea (0x512a053). A running WeChat does tons of TLS/db SHA-512, so a nonzero count proves
# frida CAN hook Weixin.dll internal x64 functions under xtajit emulation; zero means it can't.
# Usage: python frida_hook_test.py <pid>
import frida, sys, time

pid = int(sys.argv[1])
session = frida.attach(pid)
JS = r"""
var m = Process.findModuleByName("Weixin.dll");
var entry = m.base.add(0x5129f80);
var lea = m.base.add(0x512a053);
var ne = 0, nl = 0;
try { Interceptor.attach(entry, { onEnter: function(){ ne++; } }); } catch(e){ send("entry hook err " + e); }
try { Interceptor.attach(lea, { onEnter: function(){ nl++; } }); } catch(e){ send("lea hook err " + e); }
send("hooked sha512 entry + lea; counting for 25s");
setTimeout(function(){ send("RESULT entry_calls=" + ne + " lea_calls=" + nl); }, 25000);
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
time.sleep(30)
print("done")
