// 回退：hook SQLCipher 的 sqlite3_key / sqlite3_key_v2，打印 raw key hex。
// 适用：微信 4.x 若动态导出该符号。静态内联则符号不可见，需偏移定位（见 ps1 说明）。
function toHex(ptr, len) {
  var b = new Uint8Array(ptr.readByteArray(len));
  var s = "";
  for (var i = 0; i < b.length; i++) s += ("0" + b[i].toString(16)).slice(-2);
  return s;
}
["sqlite3_key", "sqlite3_key_v2"].forEach(function (name) {
  var addr = Module.findExportByName(null, name);
  if (!addr) { console.log("[miss] export not found: " + name); return; }
  Interceptor.attach(addr, {
    onEnter: function (args) {
      // sqlite3_key(db, pKey, nKey) / sqlite3_key_v2(db, zDbName, pKey, nKey)
      var pKey = name === "sqlite3_key" ? args[1] : args[2];
      var nKey = name === "sqlite3_key" ? args[2].toInt32() : args[3].toInt32();
      if (nKey > 0 && nKey <= 64) {
        console.log("[KEY] " + name + " len=" + nKey + " hex=" + toHex(pKey, nKey));
      }
    },
  });
  console.log("[hook] " + name + " @ " + addr);
});
