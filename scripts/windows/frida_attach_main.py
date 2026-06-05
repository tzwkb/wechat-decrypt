#!/usr/bin/env python3
# Attach the MAIN Weixin process (the one that loaded Weixin.dll, WorkingSet>80MB) right after a
# normal launch, while it is still opening its dbs. Hook bcrypt: BCryptDeriveKeyPBKDF2's pw arg is
# the account RAW KEY (same for ALL dbs) -> catching ANY db open gives us the key.
# Avoids: frida-spawn (incompat) and attaching the short-lived launcher (which broke startup).
import frida, subprocess, time, sys

EXE = r"C:\Program Files\Tencent\Weixin\Weixin.exe"
secs = int(sys.argv[1]) if len(sys.argv) > 1 else 45

subprocess.run(["taskkill", "/F", "/IM", "Weixin.exe"], capture_output=True)
time.sleep(2)
subprocess.Popen(["cmd", "/c", "start", "", EXE])
print("launched via 'start'; waiting for MAIN process (WorkingSet>80MB)...")

def big_weixin():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-Process Weixin -EA SilentlyContinue | Where-Object {$_.WorkingSet64 -gt 28MB} | Sort-Object WorkingSet64 -Descending | Select-Object -First 1 -ExpandProperty Id"],
        capture_output=True, text=True)
    s = r.stdout.strip()
    return int(s) if s.isdigit() else None

dev = frida.get_local_device()
main_pid = None
for _ in range(500):
    main_pid = big_weixin()
    if main_pid:
        break
    time.sleep(0.1)
if not main_pid:
    print("main Weixin process never reached 80MB"); sys.exit(1)
print("attaching MAIN pid:", main_pid)
session = dev.attach(main_pid)

JS = r"""
function hx(p, n){ var s=""; var b=new Uint8Array(p.readByteArray(n)); for(var i=0;i<b.length;i++) s+=("0"+b[i].toString(16)).slice(-2); return s; }
function g(name){ try{ return Module.findGlobalExportByName(name); }catch(e){ return null; } }
var gk=g("BCryptGenerateSymmetricKey");
if(gk) Interceptor.attach(gk, { onEnter:function(a){ var cb=a[5].toInt32(); if(cb==16||cb==24||cb==32) send("GenSymKey cb="+cb+" key="+hx(a[4],cb)); } });
var pb=g("BCryptDeriveKeyPBKDF2");
if(pb) Interceptor.attach(pb, { onEnter:function(a){ this.pw=a[1]; this.cbpw=a[2].toInt32(); this.it=a[5].toInt32(); this.dk=a[6]; this.cbdk=a[7].toInt32(); }, onLeave:function(r){ send("PBKDF2 iter="+this.it+" pw="+hx(this.pw,Math.min(this.cbpw,48))+" derived="+hx(this.dk,this.cbdk)); } });
var dec=g("BCryptDecrypt"); var dn=0;
if(dec) Interceptor.attach(dec, { onEnter:function(a){ dn++; if(dn==1||dn==20||dn==200) send("BCryptDecrypt called, count="+dn); } });
var ha=g("BCryptHashData"); var hn=0;
if(ha) Interceptor.attach(ha, { onEnter:function(a){ hn++; if(hn==1||hn==200) send("BCryptHashData called, count="+hn); } });
send("HOOKS GenSymKey="+(gk!=null)+" PBKDF2="+(pb!=null)+" Decrypt="+(dec!=null)+" Hash="+(ha!=null));
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
print("hooked main; waiting", secs, "s for db opens (PBKDF2 pw=raw key)...")
time.sleep(secs)
print("DONE")
