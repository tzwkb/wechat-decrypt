#!/usr/bin/env python3
# frida hook on bcrypt.dll: if WeChat's SQLCipher uses Windows CNG, catch the key when it
# derives K1 (PBKDF2) or creates the AES key object. Usage: python frida_hook_bcrypt.py [pid] [seconds]
import frida, sys, time

pid = int(sys.argv[1]) if len(sys.argv) > 1 else None
secs = int(sys.argv[2]) if len(sys.argv) > 2 else 25
if pid is None:
    ps = [p.pid for p in frida.enumerate_processes() if p.name.lower() == "weixin.exe"]
    pid = ps[0] if ps else None
print("attach pid:", pid, "listen", secs, "s")
session = frida.attach(pid)

JS = r"""
function hx(p, n){ var s=""; var b=new Uint8Array(p.readByteArray(n)); for(var i=0;i<b.length;i++) s+=("0"+b[i].toString(16)).slice(-2); return s; }
function findExp(name){
    try{ if(Module.findGlobalExportByName) return Module.findGlobalExportByName(name); }catch(e){}
    try{ var m=Process.findModuleByName("bcrypt.dll"); if(m&&m.findExportByName) return m.findExportByName(name); }catch(e){}
    return null;
}

// BCryptGenerateSymmetricKey(hAlg, phKey, pbKeyObj, cbKeyObj, pbSecret, cbSecret, flags) -> pbSecret=a[4],cbSecret=a[5]
var gk = findExp("BCryptGenerateSymmetricKey");
if(gk) Interceptor.attach(gk, { onEnter:function(a){
    var cb=a[5].toInt32();
    if(cb==16||cb==24||cb==32) send("GenSymKey cb="+cb+" key="+hx(a[4],cb));
}});

// BCryptDeriveKeyPBKDF2(hPrf, pbPassword, cbPassword, pbSalt, cbSalt, cIterations, pbDerivedKey, cbDerivedKey, flags)
var pb = findExp("BCryptDeriveKeyPBKDF2");
if(pb) Interceptor.attach(pb, {
    onEnter:function(a){ this.pw=a[1]; this.cbpw=a[2].toInt32(); this.it=a[5].toInt32(); this.dk=a[6]; this.cbdk=a[7].toInt32(); },
    onLeave:function(r){ send("PBKDF2 iter="+this.it+" pw="+hx(this.pw,Math.min(this.cbpw,48))+" derived="+hx(this.dk,this.cbdk)); }
});

// BCryptDecrypt(hKey, pbInput, cbInput, ...) -> cbInput=a[2]
var dec = findExp("BCryptDecrypt");
var decN=0;
if(dec) Interceptor.attach(dec, { onEnter:function(a){ decN++; if(decN<=3) send("BCryptDecrypt call#"+decN+" cbIn="+a[2].toInt32()); } });

send("HOOKS GenSymKey="+(gk!=null)+" PBKDF2="+(pb!=null)+" Decrypt="+(dec!=null));
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
print("listening (WeChat background db reads should trigger crypto)...")
time.sleep(secs)
session.detach()
print("DONE")
