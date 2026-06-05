#!/usr/bin/env python3
# Hook BCryptDeriveKeyPBKDF2 (exported by bcrypt.dll). If WeChat derives the db key via the system
# PBKDF2, args[1] = pbPassword = the raw key. User triggers opening a NEW db so the call fires.
# Also hooks BCryptGenerateSymmetricKey as a fallback. Usage: python frida_hook_pbkdf2.py <pid>
import frida, sys, time

pid = int(sys.argv[1])
session = frida.attach(pid)
JS = r"""
function hx(p, n){ try { var b = new Uint8Array(p.readByteArray(n)); var s=""; for(var i=0;i<b.length;i++) s+=('0'+b[i].toString(16)).slice(-2); return s; } catch(e){ return "?"; } }
function g(n){ try { return Module.findGlobalExportByName(n); } catch(e){ return null; } }

var pb = g('BCryptDeriveKeyPBKDF2');
if (pb) Interceptor.attach(pb, {
  onEnter: function(a){
    var cbpw = a[2].toInt32(), it = a[5].toInt32();
    send("*** PBKDF2 CALLED iter=" + it + " pwlen=" + cbpw + " pw=" + hx(a[1], Math.min(cbpw, 64)));
  }
});
var gk = g('BCryptGenerateSymmetricKey');
if (gk) Interceptor.attach(gk, {
  onEnter: function(a){ var cb = a[5].toInt32(); if (cb===16||cb===24||cb===32) send("GenSymKey cb=" + cb + " key=" + hx(a[4], cb)); }
});
send("hooked PBKDF2=" + (pb!=null) + " GenSymKey=" + (gk!=null) + " -- trigger new db now");
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
print(">>> HOOKED. Now in WeChat: click OLD chats, use SEARCH, open Moments/Files -- anything that opens a new db. 60s <<<")
time.sleep(60)
print("done")
