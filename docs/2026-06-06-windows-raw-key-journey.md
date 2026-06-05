# Windows 微信 4.0 提 key 全流程攻关记录（从 0 到端到端跑通）

日期：2026-06-05 ~ 06-06
环境：Apple Silicon Mac + UTM Windows VM（**ARM 模拟 x64**，xtajit64se.dll 翻译执行）
目标：在 Windows 微信 4.0 上实现 提 raw key → 解密 db → 读取消息 的完整链路
最终结果：**message_0.db 解出 99 会话 / 27 个 Msg 表 / 1384 条消息，端到端跑通**
最终 raw key：`***REMOVED-RAW-KEY***`

---

## 第〇章：起点与环境约束

- 原计划用 `wechat-dump-rs` 提 key + 解密。开工即发现它**被 GitHub DMCA 全封**（HTTP 451，Mac/VM/带 token/crates.io/镜像全堵），彻底不可用。
- 唯一测试环境是一台 ARM Mac 上的 UTM Windows VM。**这台 VM 用 xtajit 把 x64 指令翻译成 ARM 执行**——这个"模拟"属性后面贯穿始终，既是最大的坑，也最终被证明没挡住 hook。
- VM 接入：SSH `192.168.x.x`，user `claude`(admin)，key `~/.ssh/utm_win`。微信数据在 `C:\Users\<中文用户名>\Documents\xwechat_files\wxid_xxxxxxxxxxxx\db_storage\`。

---

## 第一章：解密/读取侧先打通（不依赖提 key）

dump-rs 没了，先把"拿到 raw key 之后"的全部代码自己实现并验证，这样提 key 一旦成功就能立刻跑通。

- **`sqlcipher_decrypt.py`**：纯 Python 实现 SQLCipher v4 解密。参数：PBKDF2-HMAC-SHA512 × **256000** 轮 → 32B enc_key(K1)；AES-256-CBC 逐页；HMAC-SHA512 页校验；page 4096，reserve 80（IV16+HMAC64）；page1 前 16 字节是明文 salt。
- **macOS 真 key 验证**：解 message_0.db **2791 页 → 明文 sqlite**，内置 sqlite3 读出 **267 会话**；join contact 真名后统计 **16966 条消息**、活跃排行（用户A 3950、某群组 2767…）。
- **文档/媒体**：探明 `msg/file/` 是明文 PDF（1034 个）、`msg/video/` 明文 mp4、`cache/` 明文 PNG/JPEG，`msg/attach/*.dat` 是 V2 加密原图（头 `07 08 56 32`）。写了 `read_doc.py`（PDF/docx/xlsx 解析，实测读出 PDF 内容）、`export_media.py`（明文附件导出）。

**这一章的意义**：把战线缩短到只剩 raw key 一个值——后面所有功夫都为这 64 个 hex 字符。

---

## 第二章：提 key 的漫长试错（按时间顺序，每个都失败，但每个都缩小了范围）

### 2.1 内存扫描裸 K1（外部 ReadProcessMemory）—— 失败
- `find_key.ps1`：OpenProcess + VirtualQueryEx + ReadProcessMemory，扫私有/只读/exec/mapped 内存，对每个 8 字节对齐的 32B 候选做 AES 校验（用 K1 解 page1[16:32]，验 SQLite 头 `10 00 .. 50 40 .. 20`）。
- 结果：**约 5800 万候选，0 命中**。
- 错误结论（当时）：K1 在 secure memory，外部读不到。**（后来证明真因是另一个，见 4.3）**

### 2.2 frida hook 系统 bcrypt —— 失败
- 假设微信用 Windows CNG（bcrypt.dll）做 PBKDF2/AES。hook `BCryptDeriveKeyPBKDF2`/`BCryptGenerateSymmetricKey`/`BCryptDecrypt`。
- 诊断：微信加载会话 **50 秒内 0 次** BCryptDecrypt/PBKDF2，只有 1 次 BCryptHashData。
- 结论（正确）：微信用 **`Weixin.dll` 内静态链的 OpenSSL** 自己算 crypto，**完全不碰系统 CNG**。hook 系统 bcrypt 这条路死。

### 2.3 frida spawn / race-attach —— 部分失败（暴露环境约束）
- **spawn 在 ARM 模拟 x64 上不兼容**：frida spawn 微信后卡死 1 个进程、110 秒起不来。这是 xtajit 的"创建暂停进程再注入"机制冲突。**→ 此后所有 hook 只能用 attach。**
- attach-race（正常启动微信 + 抢在开 db 前 attach）：抓到的是短命的**启动器**进程（11380），还干扰了微信启动（退到 0 进程）。改抓主进程（>80MB 的 `Weixin.dll` 加载者），但 attach 时 db 已开、PBKDF2 已过 → 抓不到。

### 2.4 枚举导出找 sqlite3_key —— 失败
- 枚举 `Weixin.dll` 导出：**13 个，0 个 crypto/sqlite**。枚举全部 **123 个模块**：没有单独的 `wcdb.dll`/`sqlite3.dll`/`sqlcipher.dll`（连 owl/mmmojo_64 等微信自有 dll 也没导出 sqlite）。
- 结论：SQLCipher + OpenSSL **全部静态内联进 Weixin.dll，零符号**。hook 导出符号这条路死。

### 2.5 AOB 锚点定位 —— 进展但未直达
- 扫到 SQLCipher 字符串：`kdf_iter`@rva `0x845233d`、`cipher_compatibility`/`cipher_page_size`/`HMAC_SHA512`、常量 256000(`0x3E800`)×111。证明 SQLCipher 确在 dll 内。
- 但 `kdf_iter` 的 lea 交叉引用 = **0**（字符串被特殊处理），顺藤摸瓜走不通。

---

## 第三章：决定性的 bug 与两个"不可能"

### 3.1 `Memory.readByteArray` 根本不是函数（贯穿前期所有失败的隐藏 bug）
- salt 定位法：salt（page1[0:16]）一定在 codec_ctx 里。扫内存找已知 salt，命中 **5~15 处**，dump 旁边找 K1——结果 K1=0、`pages_read=0`、`candidates=0`。
- 诊断脚本同时测两种读 API，真相大白：
  - **`Memory.readByteArray` → TypeError: not a function**（这个 frida 版本没有！）
  - `ptr.readByteArray` → 正常返回 64 字节
- **前期所有 dump/brute 的"读到 0 数据"全是这个 API 用错造成的假象**，完全不是"key 不在内存"。改用 `ptr.readByteArray` 后真能读了。

### 3.2 修好 API 后：K1 和 raw key 仍 brute 不到（但原因彻底清楚了）
- rpc 分批全扫所有 rw- range（无 size 过滤，真覆盖）：**268 万**高熵候选，K1=**0**。
  → 结论：K1 不是裸 32 字节——**OpenSSL 用 AES-NI 把它打包成轮密钥**（经 InvMixColumns 变换），内存里没有连续 32 字节等于裸 K1。brute 原理上找不到。
- salt 周围 + 跟指针 2 跳收集 **8870** 候选做 raw key 的 PBKDF2 校验：raw key=**0**。
  → 结论：**raw key 派生完 K1 后被 SQLCipher 清除**（cipher_memory_security）。
- **两个"不可能"叠加**：K1 是轮密钥、raw key 已清除——内存里都没有可直接用的明文 key。盲扫这条路从物理上堵死。

---

## 第四章：突破口——HMAC 的 ipad 是 key 的明文

### 4.1 核心洞察
PBKDF2-HMAC-SHA512(key, salt, 256000) 在 HMAC 初始化时，会构造一个 **ipad block**（128 字节）：
```
ipad_block = (key XOR 0x36)[keylen]  ||  0x36 × (128-keylen)
```
key 是 32 字节时，就是 `(key XOR 0x36)[32] || 0x36×96`。**这个 block 是 key 的明文 XOR 形式**——不是轮密钥、没被清除（构造的瞬间在），它直接被喂给 sha512。
→ **只要 hook 到 sha512、看到一个"后 96 字节全是 0x36"的输入，前 32 字节 XOR 0x36 就是 key。** 绕过轮密钥变换和清除这两道保护。

### 4.2 定位内置 sha512
- 搜 SHA512 round 常量 `K[0]=0x428a2f98d728ae22`（LE `22 ae 28 d7 98 2f 8a 42`）：命中 K 表 @ rva **`0x512b200`**，初始 H[0] @ `0x3266f98`。证明软件 SHA512 在 dll 内。
- xref K 表（lea 引用 `0x512b200`）：唯一命中 lea @ rva `0x512a053`。
- 反汇编往前找函数入口：**sha512_block 入口 @ rva `0x5129f80`**（`mov rsi,rdx` → rsi=in=input block；入口处 `rdx` = 第二参数 = input block）。注意入口内部有 CPU feature 跳转到 AVX2/SSE/标量多版本，所以早期 hook 标量路径的 lea `0x512a053` 命中 0——微信走的是 AVX 路径，但**入口是所有版本的公共必经点**。

### 4.3 最关键的一个验证：frida 在 xtajit 下到底能不能 hook 微信内部 x64 函数？
- 一度怀疑 ARM 模拟层让 hook 失效（早期 hook 入口 calls=0）。专门做诊断：attach 一个**正常运行**的微信，hook 入口 `0x5129f80` 数调用。
- 结果：**entry_calls = 11,270,455（1127 万次）**。
- 结论：**frida 完全能 hook 微信内部 x64 函数**，xtajit 不挡。早期 calls=0 的真因是——**那个微信根本没正常运行**（见第五章）。

---

## 第五章：差点翻车的坑——微信"假启动"

拿到方法后，连续栽在"微信没真正运行"上，浪费了好几轮：

1. **SSH 是 session 0（非交互后台会话），起不了需要桌面的微信 GUI**。SSH `Start-Process` 启的微信要么不显示、要么直接退（`NO Weixin`）。这解释了之前 race 老抓不到、Weixin 老是只有 1 个进程。
2. 改用 **schtasks `/it` interactive** 能把微信塞进桌面 session（Weixin=5 进程、277MB），但——**它是"空壳"**：hook 入口 50 秒 `entry_calls=0`，根本不读 db、不联网，没进入工作状态。
3. 对比实锤：**用户桌面手动双击启动**的微信，hook 入口 25 秒就 1127 万次调用。
→ 死结解开：**必须是用户桌面手动启动的活跃微信**，schtasks/SSH 起的都不行。

---

## 第六章：成功的临门一脚

### 6.1 第一次抓到 key（但是 mac_key，没用）
- 用户手动启动活跃微信，attach + hook 入口 + 检测 ipad，用户点对话。
- 抓到 **2 个 key**（每个 ipad+opad 一致互证）：`e9f67d03…` 和 `6f36c8cf…`。
- 验证：都不是 raw key 也不是 K1。**它们是 page-MAC 的 mac_key**——用户点**已打开**的对话只触发逐页 HMAC(mac_key)，mac_key 单向、不能解密。
→ 教训：要 raw key 必须触发**开新 db**（那一刻才有 `PBKDF2(raw,salt)` 的 HMAC）。

### 6.2 一击命中
- 写 `frida_entry_verify_race.py`：杀微信 → race-poll 等用户重启 → 主进程 >20MB 立即 attach（**赶在开 db 之前**）→ hook 入口 → 抓 ipad → 在 Python 端**自动用 PBKDF2/AES 验证**是 raw key 还是 K1。
- 用户**重启微信**。微信启动时开所有 db、跑启动 PBKDF2，race 赶上了：
```
attached pid: 10160
*** RAW KEY CONFIRMED: ***REMOVED-RAW-KEY***
*** K1 CONFIRMED:      ***REMOVED-K1***
```
- raw key 当场被 `PBKDF2(raw,salt,256000)→AES page1` 验证通过（出 SQLite 头）；K1 是 message_0 的派生 key，直接 AES 验证通过。

### 6.3 端到端跑通
- `decrypt_read.py`（VM 上用 pycryptodome，因为 VM 没装 cryptography）：raw key → 解密 message_0.db → 内置 sqlite3 读：
```
会话数(Name2Id) 99 · Msg 表 27 · 消息总数 1384
>>> WINDOWS DECRYPT + READ VERIFIED <<<
```
- **提 key → 解密 → 读取 完整链路验证成功。**

---

## 关键经验（给后人/未来的自己）

1. **方法对错先靠工具自证**：`Memory.readByteArray` not a function 这个 bug 让我误判了好几轮"key 不在内存"。任何"读到 0/扫到 0"，先怀疑读 API 本身，写最小诊断同时测两种 API。
2. **别跟内存里的密文/轮密钥死磕**：被保护的是"用后的形态"（轮密钥、清除）。抓"构造那一刻的明文"——HMAC 的 ipad/opad block 是 key XOR 0x36/0x5c，这是 SQLCipher 这类用 PBKDF2-HMAC 的通用突破口。
3. **环境假设要实测**：以为 ARM 模拟挡 hook（其实 1127 万次没问题），以为 schtasks 能起微信（其实是空壳）。每个"应该能/应该不能"都用一个计数/诊断坐实。
4. **GUI 应用必须在用户桌面 session**：SSH session 0 起不了、schtasks 起空壳。提 key 这一步绕不开"用户手动启动 + 我 race-attach"。
5. **raw key vs K1 vs mac_key 要当场验证**：抓到 HMAC key 别急着高兴——PBKDF2 验证=raw key（通用），AES 验证=K1（单库），都不过=mac_key（没用）。
6. **数据对照**：5800万→268万(K1)→8870(raw)候选全灭，最终靠 hook ipad 一击命中；hook 入口 1127万次/25s 证明 hook 可用；raw key 64 hex 一个值，解出 99 会话/1384 消息。

## 产出脚本（scripts/windows/）
- `frida_entry_verify_race.py` —— **最终一击必中**：race-attach + hook sha512 入口 + ipad + 自动验证
- `frida_find_sha512.py` / `frida_disasm.py` —— 定位 sha512 入口（K 常量 → xref → 反汇编）
- `frida_entry_listen.py` / `frida_entry_verify.py` —— attach 现有微信监听 ipad（运行时只能抓 mac_key）
- `decrypt_read.py` —— VM 端 pycryptodome 解密 + sqlite3 读
- `verify_keys.py` —— 验证候选 key 是 raw key / K1
- （失败但有价值的）`find_key.ps1`/`frida_brute_rpc.py`/`find_rawkey_*.py` —— 内存 brute 系列，记录"此路不通"
