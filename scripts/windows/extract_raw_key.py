#!/usr/bin/env python3
"""Self-contained Windows WeChat 4.x raw-key extractor (the single distributable unit).

Auto-locates all sha512_block entries inside Weixin.dll (no hard-coded address), race-attaches a
freshly-restarted WeChat, and reads the raw key out of the PBKDF2 HMAC ipad block the moment
SQLCipher derives the db key. Verifies each candidate as raw key (PBKDF2->AES page1) or K1.

WHY this works: raw key/K1 are protected in memory (AES-NI round keys / wiped after use / secure heap),
but the HMAC ipad block is the plaintext `key XOR 0x36` at construction time — bypassing all protection.

REQUIREMENTS: pip install frida pycryptodome ; WeChat logged in ; run, then USER restarts WeChat
(SSH/session-0/schtasks-started WeChat is a hollow shell that never opens dbs — must be desktop-launched).

Usage: python extract_raw_key.py [seconds]   -> writes key_windows.txt on success.
"""
import argparse
import csv
import glob
import hashlib
import io
import os
import re
import subprocess
import sys
import time

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KEY_FILE = os.path.join(SKILL_DIR, "key_windows.txt")

JS = r"""
function scanRanges(m, protection, pattern) {
  var hits = [];
  m.enumerateRanges(protection).forEach(function(range) {
    try {
      Memory.scanSync(range.base, range.size, pattern).forEach(function(hit) {
        hits.push({address: hit.address, range: range});
      });
    } catch (e) {
      send("WARN: scan skipped range @ " + range.base + ": " + e.message);
    }
  });
  return hits;
}

function findEntry(lea, rangeBase) {
  for (var b = 0; b < 8192; b++) {
    var a = lea.sub(b);
    if (a.compare(rangeBase) <= 0) break;
    try {
      if (a.sub(1).readU8() === 0xCC) return a;
    } catch (e) {
      send("WARN: entry inspection failed near " + lea + ": " + e.message);
      break;
    }
  }
  return null;
}

// At an x64 SHA-512 entry, rdx is the input block: key XOR 0x36 || 0x36*96.
function checkPad(p, pad) {
  try { var b = new Uint8Array(p.readByteArray(128)); for (var j=32;j<128;j++) if (b[j]!==pad) return null;
    var s=""; for (var k=0;k<32;k++) s+=('0'+(b[k]^pad).toString(16)).slice(-2); return s; } catch(e){ return null; }
}
var seen = Object.create(null);

function installHooks(m) {
  var kh = scanRanges(m, "r--", "22 ae 28 d7 98 2f 8a 42");
  if (!kh.length) throw new Error("SHA512 K-table not found");
  var tables = Object.create(null);
  kh.forEach(function(hit) { tables[hit.address.toString()] = true; });
  send("SHA-512 K-tables found: " + Object.keys(tables).length);

  // Mask REX.R and ModRM.reg to cover all 16 RIP-relative LEA encodings in one pass.
  var leas = scanRanges(m, "r-x", "48 8d 05 : fb ff c7");
  var entries = Object.create(null);
  var matchingXrefs = 0;
  leas.forEach(function(hit) {
    try {
      if (hit.address.add(7).compare(hit.range.base.add(hit.range.size)) > 0) return;
      var target = hit.address.add(7).add(hit.address.add(3).readS32());
      if (!tables[target.toString()]) return;
      matchingXrefs++;
      var entry = findEntry(hit.address, hit.range.base);
      if (entry) entries[entry.toString()] = entry;
      else send("WARN: entry not found for xref @ " + hit.address);
    } catch (e) {
      send("WARN: xref skipped @ " + hit.address + ": " + e.message);
    }
  });
  send("SHA-512 K-table xrefs found: " + matchingXrefs);
  if (!Object.keys(entries).length) throw new Error("SHA512 entries not found from K-table xrefs");

  var attached = 0;
  Object.keys(entries).forEach(function(address) {
    var entry = entries[address];
    try {
      Interceptor.attach(entry, {onEnter: function() {
        var ip = checkPad(this.context.rdx, 0x36);
        if (ip && !seen[ip]) { seen[ip] = true; send("KEY:" + ip); }
      }});
      attached++;
      send("sha512 entry @ " + entry + " (rva " + entry.sub(m.base) + ")");
    } catch (e) {
      send("WARN: hook failed @ " + entry + ": " + e.message);
    }
  });
  if (!attached) throw new Error("no SHA512 entries could be hooked");
  send("hooked " + attached + " SHA-512 entries; waiting for startup PBKDF2 (raw key)...");
}

var installed = false;
send("waiting for Weixin.dll...");
var moduleObserver = Process.attachModuleObserver({onAdded: function(m) {
  if (installed || m.name.toLowerCase() !== "weixin.dll") return;
  installed = true;
  try { installHooks(m); }
  catch (e) { send("ERR: " + e.message); }
}});
"""


def parse_main_pid(output):
    candidates = []
    for row in csv.reader(io.StringIO(output)):
        if len(row) < 5 or row[0].casefold() != "weixin.exe":
            continue
        memory = re.sub(r"[^0-9]", "", row[4])
        if not row[1].isdigit() or not memory:
            continue
        pid, memory_kib = int(row[1]), int(memory)
        if pid > 0 and memory_kib > 20 * 1024:
            candidates.append((memory_kib, pid))
    return max(candidates)[1] if candidates else None


def main_pid(timeout=2):
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, errors="replace", check=True, timeout=timeout,
    )
    return parse_main_pid(result.stdout)


def wait_for_process(seconds, *, stopped=False):
    deadline = time.monotonic() + seconds
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            pid = main_pid(timeout=min(2, remaining))
        except subprocess.TimeoutExpired:
            continue
        if (pid is None) == stopped:
            return pid
        time.sleep(min(0.04, max(0, deadline - time.monotonic())))
    raise TimeoutError("WeChat did not exit" if stopped else "WeChat did not start")


def hdr_ok(pt):
    return len(pt) >= 8 and pt[0] == 0x10 and pt[1] == 0x00 and pt[4] == 0x50 and pt[5] == 0x40 and pt[7] == 0x20


def verify_candidate(key, page1):
    from Crypto.Cipher import AES

    salt, iv, ct = page1[:16], page1[4016:4032], page1[16:32]
    derived = hashlib.pbkdf2_hmac("sha512", key, salt, 256000, 32)
    if hdr_ok(AES.new(derived, AES.MODE_CBC, iv).decrypt(ct)):
        return "raw"
    if hdr_ok(AES.new(key, AES.MODE_CBC, iv).decrypt(ct)):
        return "k1"
    return None


class KeyCapture:
    def __init__(self, page1):
        self.page1 = page1
        self.seen = set()
        self.raw_key = None
        self.error = False

    def on_message(self, message, data):
        if message.get("type") == "error":
            self.error = True
            print("ERR: Frida script failed: " + message.get("description", "unknown error"))
            return
        if message.get("type") != "send":
            return
        payload = message.get("payload", "")
        if not isinstance(payload, str):
            return
        if not payload.startswith("KEY:"):
            self.error |= payload.startswith("ERR:")
            print(payload)
            return
        candidate = payload[4:].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", candidate) or candidate in self.seen:
            return
        self.seen.add(candidate)
        kind = verify_candidate(bytes.fromhex(candidate), self.page1)
        if kind == "raw":
            self.raw_key = candidate
            print("\n*** RAW KEY captured and verified ***")
        elif kind == "k1":
            print("*** K1 candidate verified (this db only) ***")


def capture_key(device, pid, page1, seconds):
    capture = KeyCapture(page1)
    session = device.attach(pid)
    try:
        script = session.create_script(JS)
        script.on("message", capture.on_message)
        script.load()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not capture.raw_key and not capture.error:
            time.sleep(0.1)
    finally:
        try:
            session.detach()
        except Exception:
            pass
    if not capture.raw_key and not capture.error:
        print("ERR: raw key not captured; check the entry logs, WeChat build, and desktop restart timing")
    return capture.raw_key


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seconds", nargs="?", type=int, default=90)
    args = parser.parse_args(argv)
    if args.seconds <= 0:
        parser.error("seconds must be positive")
    if os.name != "nt":
        print("ERR: this extractor requires Windows")
        return 1
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    try:
        import frida
        from Crypto.Cipher import AES  # Check dependencies before closing WeChat.

        dbs = glob.glob(r"C:\Users\*\Documents\xwechat_files\*\db_storage\message\message_0.db")
        if not dbs:
            raise FileNotFoundError("message_0.db not found")
        with open(dbs[0], "rb") as source:
            page1 = source.read(4096)
        if len(page1) != 4096:
            raise ValueError("message_0.db has an incomplete first page")

        device = frida.get_local_device()
        subprocess.run(["taskkill", "/F", "/IM", "Weixin.exe"], capture_output=True, timeout=10)
        wait_for_process(10, stopped=True)
        print(">>> Now RESTART WeChat from the desktop (double-click). Race-attaching... <<<")
        pid = wait_for_process(args.seconds)
        print("attached pid:", pid)
        raw_key = capture_key(device, pid, page1, args.seconds)
        if not raw_key:
            return 1

        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as target:
            target.write(raw_key + "\n")
        try:
            os.chmod(KEY_FILE, 0o600)
        except OSError:
            pass
    except Exception as exc:
        print(f"ERR: {exc}")
        return 1
    print(f"\nDONE. verified key saved to {KEY_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
