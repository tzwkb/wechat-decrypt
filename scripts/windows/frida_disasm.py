#!/usr/bin/env python3
# Disassemble around the K-table lea (rva 0x512a053) to find the sha512_block function entry, so we can
# hook the entry (where rdx = input block) instead of mid-function. Usage: python frida_disasm.py <pid>
import frida, sys, time

pid = int(sys.argv[1])
session = frida.attach(pid)
JS = r"""
var m = Process.findModuleByName("Weixin.dll");
var lea = m.base.add(0x512a053);
send("module base=" + m.base + "; lea rva=0x512a053");
// scan backwards for int3 (0xCC) padding that precedes a function entry
var p = lea;
var entry = null;
for (var back = 0; back < 4096; back++) {
  var a = lea.sub(back);
  try {
    var bytes = new Uint8Array(a.sub(1).readByteArray(1));
    if (bytes[0] === 0xCC) { entry = a; break; }   // first byte after an int3 pad
  } catch(e){}
}
send("guessed entry (after 0xCC) rva=" + (entry ? entry.sub(m.base) : "none"));
// disassemble from entry (or lea-128) forward through lea
var start = entry ? entry : lea.sub(128);
var addr = start;
for (var i = 0; i < 60; i++) {
  try {
    var insn = Instruction.parse(addr);
    send("  " + addr.sub(m.base) + ": " + insn.toString());
    addr = insn.next;
    if (addr.compare(lea.add(16)) > 0) break;
  } catch(e){ break; }
}
send("DONE");
"""
s = session.create_script(JS)
s.on("message", lambda m, d: print(m.get("payload", m)))
s.load()
time.sleep(3)
print("done")
