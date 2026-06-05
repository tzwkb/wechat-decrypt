#!/usr/bin/env python3
# Hook sha512_block entry, capture HMAC ipad keys, and AUTO-VERIFY each as raw key (PBKDF2->AES page1)
# or K1 (direct AES). Opening a NEW db triggers PBKDF2(raw,salt) -> raw key appears. User opens new dbs
# (search / oldest chats / restart). Usage: python frida_entry_verify.py <pid>
import frida, sys, time, hashlib, glob
from Crypto.Cipher import AES

pid = int(sys.argv[1])
db = glob.glob(r"C:\Users\*\Documents\xwechat_files\*\db_storage\message\message_0.db")[0]
page1 = open(db, "rb").read(4096)
salt, iv, ct = page1[:16], page1[4016:4032], page1[16:32]

def hdr(pt):
    return pt[0] == 0x10 and pt[1] == 0x00 and pt[4] == 0x50 and pt[5] == 0x40 and pt[7] == 0x20

found = []
def on_msg(m, d):
    if m.get("type") != "send":
        return
    p = m.get("payload", "")
    if isinstance(p, str) and p.startswith("KEY:"):
        kh = p[4:]
        k = bytes.fromhex(kh)
        try:
            enc = hashlib.pbkdf2_hmac("sha512", k, salt, 256000, 32)
            if hdr(AES.new(enc, AES.MODE_CBC, iv).decrypt(ct)):
                print("*** RAW KEY CONFIRMED:", kh); found.append(("raw", kh))
        except Exception:
            pass
        try:
            if hdr(AES.new(k, AES.MODE_CBC, iv).decrypt(ct)):
                print("*** K1 CONFIRMED:", kh); found.append(("k1", kh))
        except Exception:
            pass
    else:
        print(p)

session = frida.attach(pid)
JS = r"""
var m = Process.findModuleByName("Weixin.dll");
var entry = m.base.add(0x5129f80);
function checkPad(p, pad) {
  try { var b = new Uint8Array(p.readByteArray(128)); for (var j=32;j<128;j++) if (b[j]!==pad) return null;
    var s=""; for (var k=0;k<32;k++) s+=('0'+(b[k]^pad).toString(16)).slice(-2); return s; } catch(e){ return null; }
}
var hits = {};
Interceptor.attach(entry, { onEnter: function(){ var ip = checkPad(this.context.rdx, 0x36); if (ip && !hits[ip]) { hits[ip]=1; send("KEY:" + ip); } } });
send("hooked; OPEN NEW DB now (search / oldest chats / restart)");
"""
s = session.create_script(JS)
s.on("message", on_msg)
s.load()
print(">>> HOOKED + auto-verify. Now: search a word, click OLDEST chats, or restart WeChat. 75s <<<")
time.sleep(75)
print("RESULT:", found if found else "no raw key / K1 yet (try opening more new dbs)")
