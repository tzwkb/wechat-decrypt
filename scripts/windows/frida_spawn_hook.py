#!/usr/bin/env python3
# frida SPAWN mode: kill Weixin, relaunch it under frida, hook bcrypt from startup so we catch
# the K1 derivation (PBKDF2) / AES key creation when WeChat opens its db.
# Usage: python frida_spawn_hook.py [seconds]
import frida, sys, time, subprocess

EXE = r"C:\Program Files\Tencent\Weixin\Weixin.exe"
secs = int(sys.argv[1]) if len(sys.argv) > 1 else 30

subprocess.run(["taskkill", "/F", "/IM", "Weixin.exe"], capture_output=True)
time.sleep(3)

pid = frida.spawn(EXE)
print("spawned pid:", pid)
session = frida.attach(pid)

JS = r"""
function hx(p, n){ var s=""; var b=new Uint8Array(p.readByteArray(n)); for(var i=0;i<b.length;i++) s+=("0"+b[i].toString(16)).slice(-2); return s; }
function findExp(name){
    try{ if(Module.findGlobalExportByName) return Module.findGlobalExportByName(name); }catch(e){}
    try{ var m=Process.findModuleByName("bcrypt.dll"); if(m&&m.findExportByName) return m.findExportByName(name); }catch(e){}
    return null;
}
var gk = findExp("BCryptGenerateSymmetricKey");
if(gk) Interceptor.attach(gk, { onEnter:function(a){
    var cb=a[5].toInt32();
    if(cb==16||cb==24||cb==32) send("GenSymKey cb="+cb+" key="+hx(a[4],cb));
}});
var pb = findExp("BCryptDeriveKeyPBKDF2");
if(pb) Interceptor.attach(pb, {
    onEnter:function(a){ this.pw=a[1]; this.cbpw=a[2].toInt32(); this.it=a[5].toInt32(); this.dk=a[6]; this.cbdk=a[7].toInt32(); },
    onLeave:function(r){ send("PBKDF2 iter="+this.it+" pw="+hx(this.pw,Math.min(this.cbpw,48))+" derived="+hx(this.dk,this.cbdk)); }
});
send("HOOKS GenSymKey="+(gk!=null)+" PBKDF2="+(pb!=null));
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
frida.resume(pid)
print("resumed; capturing startup db-open crypto for", secs, "s...")
time.sleep(secs)
session.detach()
print("DONE")
