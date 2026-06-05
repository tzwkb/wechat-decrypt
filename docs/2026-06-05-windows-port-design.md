# WeChat Decrypt Skill — Windows 移植设计

日期: 2026-06-05
状态: 待实现
验证环境: Apple Silicon Mac + UTM Windows VM（架构待确认，预期 ARM64）

## 1. 目标与范围

把 skill 的 Windows 支持从「未经测试的占位」变成「已验证可用」，覆盖完整链路：
微信 4.x → 提 key → 解密 → MCP 查询 / 导出 / **语音转写**。

代码**面向标准 x86_64 Windows** 编写（真实用户环境）。UTM ARM64 Windows 仅作验证环境；其成败的解读见 §6。

非目标：不改动 macOS 既有行为；不做 GUI。

## 2. 现状复用分析（基于实际代码核实）

| 文件 | 平台无关? | Windows 处理 |
|---|---|---|
| `server.py` (MCP 5 工具) | 是 | 直接复用 |
| `message.py` (格式化/sender) | 是 | 直接复用 |
| `contacts.py` (名称解析) | 是 | 直接复用 |
| `voice_decode.py` (SILK→wav, pilk) | 是 | 直接复用 |
| `export_chat.py` (zstd 三后端 fallback) | 是 | 直接复用 |
| `crypto.py` (PBKDF2 派生) | 是 | 路线 Y 下**不再调用**（明文库无需派生）|
| `config.py` | 部分 | 改：Windows 增解密产物目录、后端标志 |
| `db.py` | 否 | 改：抽象 `_exec_sql`，加明文后端 |
| `transcribe_db.py:43` 硬编码 `mlx_whisper` | 否 | 改：转写后端平台分派 |
| key 提取 (frida/extract_key.sh) | 否 | 新增 Windows 提 key 脚本 |
| `setup.ps1` (占位) | 否 | 完善 |

## 3. 架构决策

### 3.1 提 key 路线：先 wechat-dump-rs，败了回退 Frida
- 主路：`wechat-dump-rs.exe`（x64）从活微信进程内存暴力扫描出 64 hex raw key，并**自动解密所有库到明文 sqlite**。
- 回退：frida hook（Windows 微信 4.x 静态链 SQLCipher，`sqlite3_key` 是真函数）。仅当主路在该 VM 失败时启用。

### 3.2 读库路线 Y：解密成明文 + Python 内置 sqlite3
- wechat-dump-rs 解密产物是去加密的标准 sqlite，落到 `DECRYPTED_DIR`。
- `server/export/transcribe` 经 `db._exec_sql` 读明文库，Windows 用 **Python 内置 `sqlite3`**。
- 收益：Windows **零额外二进制**（除 dump-rs），不找 sqlcipher.exe、不派生 key。
- 代价：`db.py` 读取层按平台分叉，用 `_exec_sql(db_path, sql) -> list[dict]` 抽象统一：
  - macOS：现有 `sqlcipher` 二进制 + `preamble` 派生（不变）
  - Windows：`sqlite3.connect(明文库)` 直读
- `config.SQLCIPHER_PATH`（Windows 分支）废弃。

### 3.3 语音转写：转写后端平台分派
- 链路拆为「解码(共用) + 转写(平台分派)」：
  - 解码：`voice_decode.py`（pilk）跨平台，不变。
  - 转写后端：macOS=`mlx-whisper`（large-v3-mlx）；Windows=**`faster-whisper`**（CPU，large-v3）。
- `transcribe_db.py` 抽象 `_transcribe_wav(wav, lang) -> str` + 平台选择 `DEFAULT_MODEL`。
- ⚠️ VM 无 GPU，faster-whisper large-v3 在 CPU 上慢；可在 setup 提示按需降到 `medium`。

### 3.4 其他默认
- Python：装 **x64 版**（wheel 兼容最稳；faster-whisper/ctranslate2 有 x64 wheel）。
- Claude Code：装 **Windows 版**（全栈跑 MCP 必需）。
- 代码进 VM：skill 是 git 仓库 → VM 内 `git clone`/`pull`（或 UTM 共享目录）。

## 4. 组件改动清单

1. **config.py**：`IS_WINDOWS` 增 `DECRYPTED_DIR = SKILL_DIR/decrypted`（解密产物根）、`DB_BACKEND = "sqlite3"|"sqlcipher"`；废弃 Windows 的 `SQLCIPHER_PATH`。Windows 的 `WECHAT_DATA_GLOB` 仍指原始库（提 key/解密源），读取走 `DECRYPTED_DIR`。
2. **db.py**：
   - 新增 `_exec_sql(db_path, sql)`：按 `config.DB_BACKEND` 分派。
   - `query/query_raw` 改为调 `_exec_sql`。
   - `test_key`/`find_data_dir`/`get_message_dbs`/`get_contact_db_path`/`get_media_db`：Windows 指向 `DECRYPTED_DIR` 下结构（与原始库同结构，仅明文）。
   - `preamble/derive_key` 仅 macOS 路径调用。
3. **scripts/extract_key.ps1**（新）：跑 wechat-dump-rs → 写 `key.txt` + 解密全库到 `DECRYPTED_DIR`。
4. **scripts/hook_pbkdf_win.js + extract_key_frida.ps1**（新，回退）：frida hook `sqlite3_key` 抓 key；仅主路失败时用。
5. **transcribe_db.py**：`import mlx_whisper` → `_transcribe_wav` 后端分派；`DEFAULT_MODEL` 按平台。
6. **setup.ps1**：装 Python 依赖（`mcp pilk faster-whisper`）、检查/提示放 `wechat-dump-rs.exe`、注册 MCP。
7. **文档**：`SKILL.md` Windows 段「未测试」→「已验证」+ ARM/x64 坑；`README.md` 同步。

## 5. 全栈搭建顺序（VM 内，每阶段带验证 gate）

| 阶段 | 动作 | Gate |
|---|---|---|
| 0 环境 | 确认架构(`$env:PROCESSOR_ARCHITECTURE`)；装 x64 Python；装 Claude Code Win | `python --version` / `claude --version` OK |
| 1 微信 | 装微信 4.x、登录、产生聊天数据 | 有会话与消息 |
| 2 依赖 | git clone skill；`setup.ps1` 装依赖；放 `wechat-dump-rs.exe` | 依赖导入无错 |
| 3 提 key | `extract_key.ps1` → key.txt + 解密全库 | key 64 hex；明文库 `sqlite_master` 可读。**失败→走 frida 回退** |
| 4 读取 | MCP 工具 / `export_chat.py` 验证 | 列会话、读消息、导出成功 |
| 5 集成 | `setup.ps1` 注册 MCP；Claude Code 内测 5 工具 | 5 工具均返回数据 |
| 6 语音 | `transcribe_db.py --transcribe` faster-whisper | ≥1 条语音转出中文文本 |
| 7 固化 | 回填文档、记录 ARM/x64 差异与坑 | SKILL.md/README 更新 |

## 6. 风险与回退

- **R1 dump-rs 在 ARM 模拟层提 key 失败/极慢**（最大未知）：暴力扫描在模拟层可能 CPU 100% 且慢。回退 frida(§3.1)。ARM VM 失败**不代表** x64 真机失败（模拟层差异）；x64 VM 上成功才是对真实用户的有力证据。
- **R2 faster-whisper CPU 慢**：提示降模型档（medium）或 `--limit`。
- **R3 明文库占额外磁盘**：解密产物是副本；提示可清理 `DECRYPTED_DIR`。
- **R4 frida attach 模拟进程**：同属未验证；若 R1 回退也失败，记录为 ARM 环境局限，转 x64 VM 验证。

## 7. 完成定义（DoD）

VM 内全部通过：提 key(64 hex) → 解密全库 → 5 个 MCP 工具返回数据 → `export_chat` 导出成功 → faster-whisper 转出 ≥1 条语音文本 → 文档回填「已验证」并记录架构差异。macOS 行为零回归。
