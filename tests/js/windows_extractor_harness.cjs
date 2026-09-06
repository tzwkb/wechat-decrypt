const fs = require('node:fs');
const vm = require('node:vm');

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const moduleBytes = Buffer.from(input.memory, 'hex');
const calls = input.calls || [];
const memory = Buffer.concat([moduleBytes, ...calls.map(call => Buffer.from(call.block, 'hex'))]);
const base = 0x7ff000000000;
const ranges = input.ranges || [{offset: 0, size: moduleBytes.length, protection: 'r-x'}];
const messages = [], hooks = new Map(), attempts = [], scans = [];

class Pointer {
  constructor(value) { this.value = Number(value); }
  valueOf() { return this.value; }
  toString() { return '0x' + this.value.toString(16); }
  add(value) { return new Pointer(this.value + Number(value)); }
  sub(value) { return new Pointer(this.value - Number(value)); }
  compare(value) { return Math.sign(this.value - Number(value)); }
  equals(value) { return this.value === Number(value); }
  bytes(size) {
    const offset = this.value - base;
    if (offset < 0 || offset + size > memory.length) throw new Error('unreadable address');
    return memory.subarray(offset, offset + size);
  }
  readU8() { return this.bytes(1)[0]; }
  readS32() { return this.bytes(4).readInt32LE(); }
  readByteArray(size) { return Uint8Array.from(this.bytes(size)).buffer; }
}

const wechatModule = {
  name: 'Weixin.dll', base: new Pointer(base), size: moduleBytes.length,
  enumerateRanges(protection) {
    return ranges.filter(range => [...protection].every((p, i) => p === '-' || range.protection[i] === p))
      .map(range => ({base: new Pointer(base + range.offset), size: range.size, protection: range.protection}));
  },
};

function scanSync(address, size, pattern) {
  const offset = Number(address) - base;
  scans.push({offset, size, pattern});
  if ((input.fail_scans || []).includes(offset)) throw new Error('synthetic scan failure');
  const [needleText, maskText] = pattern.split(':');
  const tokens = needleText.trim().split(/\s+/);
  const needle = tokens.map(token => parseInt(token.replace(/\?/g, '0'), 16));
  const mask = maskText ? maskText.trim().split(/\s+/).map(token => parseInt(token, 16))
    : tokens.map(token => parseInt(token.replace(/[0-9a-f]/gi, 'f').replace(/\?/g, '0'), 16));
  if (!mask.length || mask[0] === 0 || mask[mask.length - 1] === 0) {
    throw new Error('invalid match pattern: Frida 17.x rejects leading/trailing wildcard bytes');
  }
  const bytes = address.bytes(size), hits = [];
  for (let i = 0; i <= bytes.length - needle.length; i++) {
    if (needle.every((byte, j) => (bytes[i + j] & mask[j]) === (byte & mask[j]))) {
      hits.push({address: address.add(i), size: needle.length});
    }
  }
  return hits;
}

let observer;
const context = {
  Uint8Array,
  send: payload => messages.push(payload),
  Memory: {scanSync},
  Process: {
    findModuleByName: name => name === wechatModule.name && !input.late_module ? wechatModule : null,
    attachModuleObserver(callbacks) {
      observer = callbacks;
      callbacks.onAdded({name: 'Other.dll'});
      if (!input.late_module) callbacks.onAdded(wechatModule);
      return {detach() {}};
    },
  },
  Interceptor: {
    attach(address, callbacks) {
      const offset = Number(address) - base;
      attempts.push(offset);
      if ((input.fail_hooks || []).includes(offset)) throw new Error('synthetic hook failure');
      if (hooks.has(offset)) throw new Error('duplicate hook');
      hooks.set(offset, callbacks);
      return {detach() { hooks.delete(offset); }};
    },
  },
};

let error = null, beforeLateEntries;
try {
  vm.runInNewContext(input.script, context, {timeout: 5000});
  beforeLateEntries = hooks.size;
  if (input.late_module) observer.onAdded(wechatModule);
  if (input.repeat_module && observer) observer.onAdded(wechatModule);
  let blockOffset = moduleBytes.length;
  for (const call of calls) {
    const hook = hooks.get(call.entry);
    if (hook) hook.onEnter.call({context: {rdx: new Pointer(base + blockOffset)}});
    blockOffset += Buffer.from(call.block, 'hex').length;
  }
} catch (e) {
  error = String(e);
}
process.stdout.write(JSON.stringify({entries: [...hooks.keys()], attempts, messages, scans, beforeLateEntries, error}));
