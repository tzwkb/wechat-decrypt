#!/usr/bin/env python3
# frida attach-race: WeChat won't boot under frida-spawn (ARM/x64 emu incompat), but attach works.
# So launch WeChat NORMALLY, attach ASAP (before it opens the db), hook bcrypt, then catch the
# PBKDF2 / AES-key creation when it opens the db a few seconds later.
# Usage: python frida_attach_race.py [seconds]
import frida, subprocess, time, sys

EXE = r"C:\Program Files\Tencent\Weixin\Weixin.exe"
secs = int(sys.argv[1]) if len(sys.argv) > 1 else 60

subprocess.run(["taskkill", "/F", "/IM", "Weixin.exe"], capture_output=True)
time.sleep(2)
subprocess.Popen([EXE])  # NORMAL launch (no frida), so WeChat boots fine
print("launched WeChat normally; racing to attach before db opens...")

pid = None
dev = frida.get_local_device()
for _ in range(80):
    ps = sorted([p.pid for p in dev.enumerate_processes() if p.name.lower() == "weixin.exe"])
    if ps:
        pid = ps[0]
        break
    time.sleep(0.12)
if not pid:
    print("no Weixin process appeared"); sys.exit(1)
print("attaching pid:", pid)
session = frida.attach(pid)

JS = r"""
function hx(p, n){ var s=""; var b=new Uint8Array(p.readByteArray(n)); for(var i=0;i<b.length;i++) s+=("0"+b[i].toString(16)).slice(-2); return s; }
function g(name){ try{ return Module.findGlobalExportByName(name); }catch(e){ return null; } }
var gk=g("BCryptGenerateSymmetricKey");
if(gk) Interceptor.attach(gk, { onEnter:function(a){ var cb=a[5].toInt32(); if(cb==16||cb==24||cb==32) send("GenSymKey cb="+cb+" key="+hx(a[4],cb)); } });
var pb=g("BCryptDeriveKeyPBKDF2");
if(pb) Interceptor.attach(pb, { onEnter:function(a){ this.pw=a[1]; this.cbpw=a[2].toInt32(); this.it=a[5].toInt32(); this.dk=a[6]; this.cbdk=a[7].toInt32(); }, onLeave:function(r){ send("PBKDF2 iter="+this.it+" pw="+hx(this.pw,Math.min(this.cbpw,48))+" derived="+hx(this.dk,this.cbdk)); } });
send("HOOKS GenSymKey="+(gk!=null)+" PBKDF2="+(pb!=null));
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
print("hooked early; waiting", secs, "s for db open (PBKDF2 should fire)...")
time.sleep(secs)
print("DONE")
