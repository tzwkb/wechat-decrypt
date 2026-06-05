# WeChat 4.0 Windows 提 key 攻关 + 已就绪成果交付

日期: 2026-06-05  环境: Apple Silicon Mac + UTM Windows (ARM, x64 模拟微信 4.0)

## 执行摘要

Windows 端的**解密 / 读取 / 文档 / 媒体全部就绪并验证过**,唯一卡点是**提取 Windows raw key**——这被确诊为 dump-rs 级硬逆向(微信把 key 三重封死)。AOB 逆向第一步已成功(SQLCipher 锚点精确定位),逆向路径已铺好,供离线 IDA/Ghidra 完成最后一步 hook。**一旦拿到那 64 个 hex 字符,整条 Windows 链立刻全通。**

---

## 一、已就绪并验证(不依赖提 key)

| 模块 | 文件 | 验证 |
|---|---|---|
| SQLCipher 解密 | `scripts/common/sqlcipher_decrypt.py` | macOS 真 key 解 message_0.db **2791 页→明文 sqlite**,读出 267 会话 |
| 消息读取 | `server.py`/`export_chat.py`/`message.py` + contact 真名 join | 演示 **16966 消息 / 活跃排行带真名**(对标 wecom stats) |
| 文档读取 | `scripts/common/read_doc.py` | 验证读出 PDF 实际内容(PDF/docx/xlsx) |
| 媒体导出 | `scripts/common/export_media.py` | 导出明文文档(msg/file)/视频(msg/video mp4)/cache 图(明文PNG/JPEG) |

**路线 Y(改版)**: dump-rs 被封 → 自己实现解密。拿到 raw key → `sqlcipher_decrypt.decrypt_db(raw, src, dst)` → 内置 `sqlite3` 读。

SQLCipher v4 参数(已验证): PBKDF2-HMAC-SHA512 × 256000 → enc_key;AES-256-CBC;HMAC-SHA512 页校验;page 4096,reserve 80 (IV16+HMAC64);page1 前 16 字节 = 明文 salt。

未做: `msg/attach/*.dat` 是 V2 加密原图(头 `07 08 56 32` = "..V2"),需单独解码器;cache 缩略图已是明文够用。

---

## 二、提 key 三重封死(全面诊断)

1. **不在普通内存** — 内存扫 32B + AES 校验 **5800 万候选全空** → key 在 secure memory / mlock。
2. **不经系统 API** — frida hook bcrypt,加载会话 50s 内 **0 次 BCryptDecrypt/PBKDF2** → 微信用 `Weixin.dll` 静态链 OpenSSL,不调系统 CNG。
3. **无符号导出** — `Weixin.dll`(175MB) 仅 **13 个导出、0 个 crypto/sqlite** → SQLCipher+OpenSSL 全静态内联。

排除的路: 内存扫描、frida hook 系统 bcrypt、frida race(spawn 在 ARM 模拟不兼容 + 时机)、枚举导出符号。**剩唯一路 = AOB 逆向 Weixin.dll 内部函数。**

---

## 三、AOB 逆向锚点 + 下一步(供离线 IDA/Ghidra)

SQLCipher 确认在 `Weixin.dll`。锚点用 **RVA**(= 运行时地址 − imagebase,免 ASLR;本次 imagebase=0x7ffa25c70000):

| 符号/常量 | RVA | 用途 |
|---|---|---|
| `kdf_iter` (PRAGMA) | `0x245233d` (×9) | SQLCipher codec pragma 处理 |
| `cipher_compatibility` | `0x2452319` | 同上,相邻字符串表 |
| `cipher_page_size` | `0x2452421` | 同上 |
| `cipher_hmac_algorithm` | `0x245235f` | 同上 |
| `HMAC_SHA512` | `0x2baf434` | HMAC 算法名 |
| const `256000` | `0x842498` (×111) | kdf_iter 默认值 |

**逆向路径:**
1. IDA/Ghidra 加载 `Weixin.dll`,跳到 RVA `0x245233d`(kdf_iter 字符串)。
2. 看 xref → 引用它的函数 = `sqlcipher_codec_pragma`(处理 `PRAGMA cipher_*`)。
3. 顺 codec ctx 调用链找 **key 设置入口**: `sqlite3_key` / `sqlcipher_codec_ctx_set_pass`(接收 raw key 二进制),或 `sqlcipher_derive_key`(调 `PBKDF2(raw, salt, 256000)`)。微信确认走 `sqlite3_key` API + cipher PRAGMA(没搜到 "PRAGMA key" 文本)。
4. 定位该函数 RVA + 确定 raw key 在哪个参数寄存器(x64: rcx/rdx/r8/r9)或栈偏移。
5. frida hook(模板见下)抓 raw key。

**frida hook 模板**(IDA 定到函数 RVA 后):
```javascript
var base = Process.findModuleByName("Weixin.dll").base;
var fn = base.add(0xRVA_FROM_IDA);
Interceptor.attach(fn, { onEnter: function(args){
    // sqlite3_key(db, pKey, nKey): pKey=args[1], nKey=args[2]
    var p = args[1], n = args[2].toInt32();
    if (n >= 16 && n <= 64) {
        var b = new Uint8Array(p.readByteArray(n)), s="";
        for (var i=0;i<b.length;i++) s += ("0"+b[i].toString(16)).slice(-2);
        send("RAWKEY len="+n+" hex="+s);
    }
}});
```
抓到 raw key(64 hex) → 写 `key.txt` → `python sqlcipher_decrypt.py <rawkey> <db> <out>` 解密 → sqlite3 读。

注: hook 要在 db 打开**前** attach(key 在打开时设一次);frida spawn 不兼容,用 attach-race(正常启动微信 + 等主进程 >28MB 立即 attach,见 `scripts/windows/frida_attach_main.py`)。

---

## 四、VM 接入 + 工具链坑

- UTM Windows `192.168.x.x`,user `claude`(admin/SeDebug),key `~/.ssh/utm_win`。重启 VM 后 IP 可能变,扫 192.168.x.x:22。
- 数据: `C:\Users\零九三号虚拟机\Documents\xwechat_files\wxid_..._a254\`(另一用户,admin 可读)。
- **frida spawn 在 ARM 模拟 x64 进程不兼容**(微信卡死 1 进程);**attach 可**。
- **frida 17 API 大变**: `Module.findGlobalExportByName(name)`、`frida.get_local_device().enumerate_processes()`(旧 `Module.findExportByName`/`frida.enumerate_processes` 已删)。
- 装 frida 用清华镜像(PyPI 直连 ConnectionReset): `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple frida-tools`。
- raw key **每设备独立**(4.0): macOS raw key 解不了 Windows 同账号 db。
- 写脚本默认英文(C# here-string 中文被 Win PowerShell GBK 读崩)。

---

## 五、最快备选: dump-rs

`github.com/0xlane/wechat-dump-rs` 被 DMCA 全封(451,Mac/VM/token/镜像全堵)。若从别处搞到 `wechat-dump-rs.exe`,它已离线做好本文第三节的逆向,直接提 key + 解密,整条立刻全通。
