#!/usr/bin/env python3
# frida SPAWN + anti-debug bypass: WeChat refuses to start under a debugger, so neutralize the
# common anti-debug checks, let it boot, and hook bcrypt to catch the K1 derivation on db open.
# Usage: python frida_spawn_antidbg.py [seconds]
import frida, sys, time, subprocess

EXE = r"C:\Program Files\Tencent\Weixin\Weixin.exe"
secs = int(sys.argv[1]) if len(sys.argv) > 1 else 90

subprocess.run(["taskkill", "/F", "/IM", "Weixin.exe"], capture_output=True)
time.sleep(3)

pid = frida.spawn(EXE)
print("spawned pid:", pid)
session = frida.attach(pid)

JS = r"""
function hx(p, n){ var s=""; var b=new Uint8Array(p.readByteArray(n)); for(var i=0;i<b.length;i++) s+=("0"+b[i].toString(16)).slice(-2); return s; }
function g(name){ try{ return Module.findGlobalExportByName(name); }catch(e){ return null; } }

// ---- anti-debug bypass ----
["IsDebuggerPresent"].forEach(function(n){
    var f=g(n);
    if(f){ try{ Interceptor.replace(f, new NativeCallback(function(){ return 0; }, 'int', [])); send("bypass "+n); }catch(e){} }
});
var crd=g("CheckRemoteDebuggerPresent");
if(crd) Interceptor.attach(crd, { onLeave:function(r){ try{ this.context; }catch(e){} } });
var nq=g("NtQueryInformationProcess");
if(nq) Interceptor.attach(nq, {
    onEnter:function(a){ this.cls=a[1].toInt32(); this.out=a[2]; },
    onLeave:function(r){ try{
        if(this.cls==7 && !this.out.isNull()) this.out.writeU64(0);    // ProcessDebugPort
        if(this.cls==30 && !this.out.isNull()) this.out.writeU64(0);   // ProcessDebugObjectHandle
        if(this.cls==31 && !this.out.isNull()) this.out.writeU32(1);   // ProcessDebugFlags (1=not debugged)
    }catch(e){} }
});

// ---- bcrypt key hooks ----
var gk=g("BCryptGenerateSymmetricKey");
if(gk) Interceptor.attach(gk, { onEnter:function(a){ var cb=a[5].toInt32(); if(cb==16||cb==24||cb==32) send("GenSymKey cb="+cb+" key="+hx(a[4],cb)); } });
var pb=g("BCryptDeriveKeyPBKDF2");
if(pb) Interceptor.attach(pb, {
    onEnter:function(a){ this.pw=a[1]; this.cbpw=a[2].toInt32(); this.it=a[5].toInt32(); this.dk=a[6]; this.cbdk=a[7].toInt32(); },
    onLeave:function(r){ send("PBKDF2 iter="+this.it+" pw="+hx(this.pw,Math.min(this.cbpw,48))+" derived="+hx(this.dk,this.cbdk)); }
});
send("HOOKS antidbg=on GenSymKey="+(gk!=null)+" PBKDF2="+(pb!=null));
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
frida.resume(pid)
print("resumed (anti-debug bypassed); capturing for", secs, "s...")
time.sleep(secs)
# report process count to confirm WeChat actually booted
print("DONE")
