# WeChat Decrypt — Windows 移植 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 skill 的 Windows 支持从未测试占位变为已验证全链路（提 key → 解密 → MCP/导出/语音转写）。

**Architecture:** 路线 Y——`wechat-dump-rs -a` 提 key 并把所有库解密成明文 sqlite（保留原目录结构）到 `SKILL_DIR/decrypted`；`db.py` 增 `sqlite3` 明文后端，用 Python 内置 `sqlite3` 直读；`server/message/contacts/export/voice_decode` 完全复用。Task 0-4 在 macOS 用 pytest TDD（内置 sqlite3 跨平台），Task 5-8 为 Windows 脚本 + VM 验证 gate。

**Tech Stack:** Python 内置 sqlite3、pytest、wechat-dump-rs.exe、faster-whisper、frida(回退)、PowerShell。

参考 spec: `docs/2026-06-05-windows-port-design.md`

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `pyproject.toml` | 加 pytest 配置 | Modify |
| `tests/conftest.py` | 造明文测试库 fixture | Create |
| `tests/test_config.py` | 平台分支断言 | Create |
| `tests/test_db_backend.py` | sqlite3 后端 query/query_raw/test_key/find_data_dir | Create |
| `tests/test_transcribe_backend.py` | 转写后端选择 | Create |
| `config.py` | Windows 增 `DB_BACKEND`/`DECRYPTED_DIR` | Modify |
| `db.py` | `_exec_sql` 抽象 + sqlite3 分派 | Modify |
| `scripts/common/transcribe_db.py` | 转写后端平台分派 | Modify |
| `scripts/windows/extract_key.ps1` | wechat-dump-rs 提 key+解密 | Create |
| `scripts/windows/hook_sqlite3_key_win.js` | frida 回退 hook | Create |
| `scripts/windows/extract_key_frida.ps1` | frida 回退驱动 | Create |
| `setup.ps1` | 完善安装 | Modify |
| `SKILL.md` / `README.md` | 文档回填「已验证」 | Modify |

---

## Task 0: 测试基建 + 明文库 fixture

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/conftest.py`

- [ ] **Step 1: 在 pyproject.toml 末尾加 pytest 配置**

```toml
[tool.pytest.ini_options]
pythonpath = [".", "scripts"]
testpaths = ["tests"]
```

- [ ] **Step 2: 写 conftest.py —— 造一个镜像真实结构的明文测试库**

`tests/conftest.py`:
```python
import hashlib
import os
import sqlite3
import pytest

# 一个样例 wxid 及其 Msg 表名（与 db.get_name2id 的 md5 规则一致）
SAMPLE_WXID = "wxid_friend001"
SAMPLE_TABLE = "Msg_" + hashlib.md5(SAMPLE_WXID.encode()).hexdigest()


@pytest.fixture
def decrypted_dir(tmp_path):
    """造一个 wechat-dump-rs 风格的明文解密目录：<root>/<wxid>/db_storage/..."""
    root = tmp_path / "decrypted"
    storage = root / "acct_a1" / "db_storage"
    msg_dir = storage / "message"
    contact_dir = storage / "contact"
    msg_dir.mkdir(parents=True)
    contact_dir.mkdir(parents=True)

    # message_0.db: Name2Id + 一个会话表 + 媒体库
    m = sqlite3.connect(msg_dir / "message_0.db")
    m.execute("CREATE TABLE Name2Id (user_name TEXT);")
    m.execute("INSERT INTO Name2Id (user_name) VALUES (?);", (SAMPLE_WXID,))
    m.execute(
        f"CREATE TABLE {SAMPLE_TABLE} "
        "(local_id INTEGER, server_id TEXT, local_type INTEGER, message_content TEXT);"
    )
    m.execute(
        f"INSERT INTO {SAMPLE_TABLE} (local_id, server_id, local_type, message_content) "
        "VALUES (1, '1001', 1, 'hello'), (2, '1002', 34, '');"
    )
    m.commit(); m.close()

    # media_0.db: VoiceInfo
    md = sqlite3.connect(msg_dir / "media_0.db")
    md.execute("CREATE TABLE VoiceInfo (svr_id TEXT, voice_data BLOB);")
    md.execute("INSERT INTO VoiceInfo (svr_id, voice_data) VALUES ('1002', X'0223214653494C4B5F5633');")
    md.commit(); md.close()

    # contact.db
    c = sqlite3.connect(contact_dir / "contact.db")
    c.execute(
        "CREATE TABLE contact "
        "(username TEXT, alias TEXT, nick_name TEXT, remark TEXT, local_type INTEGER);"
    )
    c.execute(
        "INSERT INTO contact (username, alias, nick_name, remark, local_type) "
        "VALUES (?, 'alias1', '好友昵称', '备注名', 3);", (SAMPLE_WXID,)
    )
    c.commit(); c.close()

    return str(root)


@pytest.fixture
def win_backend(monkeypatch, decrypted_dir):
    """把进程伪装成 Windows sqlite3 后端，并指向测试解密目录。"""
    import config
    monkeypatch.setattr(config, "DB_BACKEND", "sqlite3", raising=False)
    monkeypatch.setattr(config, "DECRYPTED_DIR", decrypted_dir, raising=False)
    import db
    db._contact_db_path = None
    db._media_db_path = None
    return decrypted_dir
```

- [ ] **Step 3: 运行确认基建可发现测试（暂无测试用例）**

Run: `/opt/homebrew/bin/python3 -m pytest tests/ -q`
Expected: `no tests ran`（无 collection 错误即通过）

- [ ] **Step 4: Commit**

```bash
cd ~/.claude/skills/wechat-decrypt
git add pyproject.toml tests/conftest.py
git commit -m "test: add pytest scaffolding + plaintext db fixture for windows backend"
```

---

## Task 1: config.py — Windows sqlite3 后端配置

**Files:**
- Modify: `config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

`tests/test_config.py`:
```python
import importlib


def test_macos_backend_is_sqlcipher(monkeypatch):
    import platform
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    import config
    importlib.reload(config)
    assert config.DB_BACKEND == "sqlcipher"
    assert config.SQLCIPHER_PATH.endswith("sqlcipher")


def test_windows_backend_is_sqlite3(monkeypatch):
    import platform
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    import config
    importlib.reload(config)
    assert config.DB_BACKEND == "sqlite3"
    assert config.DECRYPTED_DIR.endswith("decrypted")


def test_reload_restores_real_platform():
    import config
    importlib.reload(config)  # 还原真实平台，避免污染后续测试
```

- [ ] **Step 2: 运行确认失败**

Run: `/opt/homebrew/bin/python3 -m pytest tests/test_config.py -v`
Expected: FAIL —— `AttributeError: module 'config' has no attribute 'DB_BACKEND'`

- [ ] **Step 3: 改 config.py**

把 `config.py` 的平台分支替换为：
```python
if IS_MACOS:
    DB_BACKEND = "sqlcipher"
    SQLCIPHER_PATH = "/opt/homebrew/bin/sqlcipher"
    WECHAT_DATA_GLOB = os.path.expanduser(
        "~/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
        "xwechat_files/*/db_storage"
    )
elif IS_WINDOWS:
    DB_BACKEND = "sqlite3"
    # wechat-dump-rs 解密产物根目录（明文库，保留原结构）
    DECRYPTED_DIR = os.path.join(SKILL_DIR, "decrypted")
    # 原始加密库（仅供提 key/解密时定位源）
    WECHAT_DATA_GLOB = os.path.expanduser(
        "~/Documents/xwechat_files/*/db_storage"
    )
else:
    raise RuntimeError(f"Unsupported platform: {platform.system()}")
```

- [ ] **Step 4: 运行确认通过**

Run: `/opt/homebrew/bin/python3 -m pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat(config): add windows sqlite3 backend + decrypted dir"
```

---

## Task 2: db.py — `_exec_sql` 抽象 + sqlite3 query/query_raw

**Files:**
- Modify: `db.py`
- Create: `tests/test_db_backend.py`

- [ ] **Step 1: 写失败测试**

`tests/test_db_backend.py`:
```python
import os


def test_query_reads_plaintext(win_backend):
    import db
    data_dir = db.find_data_dir()
    msg_db = os.path.join(data_dir, "message", "message_0.db")
    rows = db.query(msg_db, "SELECT user_name FROM Name2Id;")
    assert rows == [{"user_name": "wxid_friend001"}]


def test_query_raw_single_column(win_backend):
    import db
    data_dir = db.find_data_dir()
    msg_db = os.path.join(data_dir, "message", "message_0.db")
    names = db.query_raw(msg_db, "SELECT name FROM sqlite_master WHERE type='table';")
    assert "Name2Id" in names


def test_get_name2id_maps_table_to_wxid(win_backend):
    import db
    from conftest import SAMPLE_TABLE
    mapping = db.get_name2id()
    assert mapping.get(SAMPLE_TABLE) == "wxid_friend001"
```

- [ ] **Step 2: 运行确认失败**

Run: `/opt/homebrew/bin/python3 -m pytest tests/test_db_backend.py -v`
Expected: FAIL —— `find_data_dir` 走 sqlcipher 分支报错或找不到目录

- [ ] **Step 3: 在 db.py 顶部新增 `_exec_sql` 并改造 query/query_raw**

在 `db.py` 的 `import` 后、`preamble` 前插入：
```python
def _exec_sqlite3(db_path: str, sql: str) -> list[sqlite3.Row]:
    import sqlite3
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()
```
（并在文件顶部 `import` 区加 `import sqlite3`。）

把现有 `query` 改为顶部分派：
```python
def query(db_path: str, sql: str) -> list[dict]:
    """Execute SQL query and return list of dicts."""
    if config.DB_BACKEND == "sqlite3":
        return [dict(r) for r in _exec_sqlite3(db_path, sql)]
    key = crypto.load_key()
    cmd = preamble(key, db_path) + ".headers on\n.mode csv\n" + sql
    result = subprocess.run(
        [config.SQLCIPHER_PATH, db_path],
        input=cmd.encode(), capture_output=True, timeout=30,
    )
    text = result.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    lines = text.split("\n")
    while lines and lines[0].strip() == "ok":
        lines.pop(0)
    if len(lines) < 2:
        return []
    return list(csv.DictReader(io.StringIO("\n".join(lines))))
```

把现有 `query_raw` 改为顶部分派：
```python
def query_raw(db_path: str, sql: str) -> list[str]:
    """Execute SQL and return raw output lines."""
    if config.DB_BACKEND == "sqlite3":
        rows = _exec_sqlite3(db_path, sql)
        return ["|".join("" if c is None else str(c) for c in tuple(r)) for r in rows]
    key = crypto.load_key()
    cmd = preamble(key, db_path) + sql
    result = subprocess.run(
        [config.SQLCIPHER_PATH, db_path],
        input=cmd.encode(), capture_output=True, timeout=30,
    )
    text = result.stdout.decode("utf-8", errors="replace").strip()
    return [l for l in text.split("\n") if l.strip() and l.strip() != "ok"]
```

（注：本 Task 仅让 query/query_raw 分派；`find_data_dir`/`test_key` 的 sqlite3 分支在 Task 3 加，故 Step 2 仍失败。）

- [ ] **Step 4: 运行——仍失败于 find_data_dir（预期）**

Run: `/opt/homebrew/bin/python3 -m pytest tests/test_db_backend.py -v`
Expected: FAIL（`find_data_dir` 未分派）。进入 Task 3。

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db_backend.py
git commit -m "feat(db): add sqlite3 plaintext backend for query/query_raw"
```

---

## Task 3: db.py — test_key / find_data_dir 的 sqlite3 分派

**Files:**
- Modify: `db.py`

- [ ] **Step 1: 改 test_key 顶部分派**

把 `test_key` 改为：
```python
def test_key(key: str, db_path: str) -> bool:
    """Test if a database is readable (sqlcipher: key works / sqlite3: plaintext opens)."""
    if config.DB_BACKEND == "sqlite3":
        import sqlite3
        try:
            con = sqlite3.connect(db_path)
            con.execute("SELECT count(*) FROM sqlite_master;").fetchone()
            con.close()
            return True
        except Exception:
            return False
    cmd = (
        preamble(key, db_path)
        + "SELECT count(*) FROM sqlite_master;\n"
    )
    try:
        result = subprocess.run(
            [config.SQLCIPHER_PATH, db_path],
            input=cmd.encode(), capture_output=True, timeout=5,
        )
        stdout = result.stdout.decode().strip()
        stderr = result.stderr.decode().strip()
        if "error" in stderr.lower():
            return False
        lines = [l.strip() for l in stdout.split("\n") if l.strip() and l.strip() != "ok"]
        return any(l.isdigit() and int(l) > 0 for l in lines)
    except Exception:
        return False
```

- [ ] **Step 2: 改 find_data_dir 顶部分派**

把 `find_data_dir` 改为：
```python
def find_data_dir() -> str:
    """Find the WeChat db_storage directory (most recent with valid key)."""
    if config.DB_BACKEND == "sqlite3":
        return _find_decrypted_data_dir()
    matches = sorted(glob.glob(config.WECHAT_DATA_GLOB), key=os.path.getmtime, reverse=True)
    if not matches:
        raise FileNotFoundError(f"未找到 WeChat 数据目录: {config.WECHAT_DATA_GLOB}")
    key = crypto.load_key()
    for match in matches:
        msg_db = os.path.join(match, "message", "message_0.db")
        if os.path.exists(msg_db) and test_key(key, msg_db):
            return match
    return matches[0]


def _find_decrypted_data_dir() -> str:
    """Locate the db_storage root inside the decrypted output (layout-robust)."""
    hits = glob.glob(
        os.path.join(config.DECRYPTED_DIR, "**", "message", "message_0.db"),
        recursive=True,
    )
    if not hits:
        raise FileNotFoundError(
            f"未找到解密后的 message_0.db，先运行 scripts/windows/extract_key.ps1。"
            f"查找根: {config.DECRYPTED_DIR}"
        )
    hits.sort(key=os.path.getmtime, reverse=True)
    # message_0.db 的父父级即 db_storage 根
    return os.path.dirname(os.path.dirname(hits[0]))
```

- [ ] **Step 3: 运行 Task 2+3 全部测试通过**

Run: `/opt/homebrew/bin/python3 -m pytest tests/test_db_backend.py -v`
Expected: 3 passed

- [ ] **Step 4: 回归——确认 macOS 真实链路未坏**

Run: `/opt/homebrew/bin/python3 -m pytest tests/ -v`
Expected: all passed（config + db_backend 全绿）

- [ ] **Step 5: Commit**

```bash
git add db.py
git commit -m "feat(db): sqlite3 dispatch for test_key + find_data_dir (decrypted layout)"
```

---

## Task 4: transcribe_db.py — 转写后端平台分派

**Files:**
- Modify: `scripts/common/transcribe_db.py`
- Create: `tests/test_transcribe_backend.py`

- [ ] **Step 1: 写失败测试**

`tests/test_transcribe_backend.py`:
```python
import sys
import types


def test_macos_uses_mlx(monkeypatch):
    import transcribe_db
    monkeypatch.setattr(transcribe_db, "IS_MACOS", True)
    called = {}
    fake = types.ModuleType("mlx_whisper")
    fake.transcribe = lambda wav, path_or_hf_repo, language: called.update({"mlx": True}) or {"text": "你好"}
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)
    assert transcribe_db._transcribe_wav("/tmp/x.wav") == "你好"
    assert called.get("mlx") is True


def test_windows_uses_faster_whisper(monkeypatch):
    import transcribe_db
    monkeypatch.setattr(transcribe_db, "IS_MACOS", False)
    monkeypatch.setattr(transcribe_db, "_fw_model", None, raising=False)

    class _Seg:
        def __init__(self, t): self.text = t

    class _Model:
        def __init__(self, *a, **k): pass
        def transcribe(self, wav, language): return ([_Seg("你"), _Seg("好")], None)

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = _Model
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    assert transcribe_db._transcribe_wav("/tmp/x.wav") == "你好"
```

- [ ] **Step 2: 运行确认失败**

Run: `/opt/homebrew/bin/python3 -m pytest tests/test_transcribe_backend.py -v`
Expected: FAIL —— `module 'transcribe_db' has no attribute '_transcribe_wav'`

- [ ] **Step 3: 改 transcribe_db.py**

把顶部 `DEFAULT_MODEL = "mlx-community/whisper-large-v3-mlx"` 替换为：
```python
import platform
IS_MACOS = platform.system() == "Darwin"
DEFAULT_MODEL = "mlx-community/whisper-large-v3-mlx" if IS_MACOS else "large-v3"
_fw_model = None


def _transcribe_wav(wav: str, lang: str = "zh", model: str = DEFAULT_MODEL) -> str:
    """Transcribe one wav with the platform's whisper backend."""
    if IS_MACOS:
        import mlx_whisper
        r = mlx_whisper.transcribe(wav, path_or_hf_repo=model, language=lang)
        return (r.get("text") or "").strip()
    from faster_whisper import WhisperModel
    global _fw_model
    if _fw_model is None:
        _fw_model = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _ = _fw_model.transcribe(wav, language=lang)
    return "".join(s.text for s in segments).strip()
```

在 `transcribe_server_ids` 里，把这段：
```python
    import mlx_whisper

    result: dict[str, str] = {}
```
改为：
```python
    result: dict[str, str] = {}
```
并把循环内：
```python
                voice_decode.decode_voice_blob(blob, wav)
                r = mlx_whisper.transcribe(wav, path_or_hf_repo=model, language="zh")
                text = (r.get("text") or "").strip()
```
改为：
```python
                voice_decode.decode_voice_blob(blob, wav)
                text = _transcribe_wav(wav, lang="zh", model=model)
```

- [ ] **Step 4: 运行确认通过**

Run: `/opt/homebrew/bin/python3 -m pytest tests/test_transcribe_backend.py -v`
Expected: 2 passed

- [ ] **Step 5: 全量回归**

Run: `/opt/homebrew/bin/python3 -m pytest tests/ -q`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add scripts/common/transcribe_db.py tests/test_transcribe_backend.py
git commit -m "feat(transcribe): platform-dispatch whisper backend (mlx/faster-whisper)"
```

---

## Task 5: scripts/windows/extract_key.ps1 —— wechat-dump-rs 主路（VM gate）

**Files:**
- Create: `scripts/windows/extract_key.ps1`

> 本 Task 起为 Windows 脚本，**在 UTM Windows VM 内执行验证**，非 pytest。

- [ ] **Step 1: 写 extract_key.ps1**

`scripts/windows/extract_key.ps1`:
```powershell
# WeChat key 提取 + 全库解密（Windows 主路：wechat-dump-rs）
# 前置：微信 4.x 已登录运行；wechat-dump-rs.exe 在 skill 根目录
$ErrorActionPreference = "Stop"
$SKILL_DIR = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DUMP = Join-Path $SKILL_DIR "wechat-dump-rs.exe"
$OUT  = Join-Path $SKILL_DIR "decrypted"

if (-not (Test-Path $DUMP)) {
    Write-Error "缺少 $DUMP —— 从 https://github.com/0xlane/wechat-dump-rs/releases 下载放此处"
}
New-Item -ItemType Directory -Force -Path $OUT | Out-Null

Write-Host "[1/3] 运行 wechat-dump-rs（dump key + 解密全部 -> decrypted/）..."
$raw = & $DUMP -a -o $OUT 2>&1 | Out-String
Write-Host $raw

Write-Host "[2/3] 提取 key 写入 key.txt（路线 Y 下仅作记录，读取不依赖）..."
$m = [regex]::Match($raw, '[0-9a-fA-F]{64}')
if ($m.Success) {
    Set-Content -Path (Join-Path $SKILL_DIR "key.txt") -Value $m.Value.ToLower() -NoNewline
    Write-Host "  key.txt 已写入"
} else {
    Write-Warning "  未在输出中匹配到 64-hex key（不影响明文读取；若解密为空才需排查）"
}

Write-Host "[3/3] 校验解密产物..."
$msg = Get-ChildItem -Path $OUT -Recurse -Filter "message_0.db" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($msg) {
    Write-Host "  OK -> $($msg.FullName)"
} else {
    Write-Error "  decrypted/ 下未找到 message_0.db —— 主路失败，改走 frida 回退 (extract_key_frida.ps1)"
}
```

- [ ] **Step 2: VM 验证 gate**

在 VM PowerShell（微信已登录）执行：
```powershell
powershell -ExecutionPolicy Bypass -File $env:USERPROFILE\.claude\skills\wechat-decrypt\scripts\windows\extract_key.ps1
```
Expected:
- 输出含 `OK -> ...\decrypted\...\message\message_0.db`
- `decrypted\` 下出现 message/contact 等明文库

**失败处理**：若 `-a` 报错或 decrypted 为空 → 记录现象（含 ARM/x64 架构、CPU 占用、错误文本）→ 转 Task 6 frida 回退。

- [ ] **Step 3: 解密库可读性 gate（Python 内置 sqlite3）**

VM 内执行：
```powershell
python -c "import sqlite3,glob; p=glob.glob(r'%USERPROFILE%\.claude\skills\wechat-decrypt\decrypted\**\message_0.db',recursive=True)[0]; c=sqlite3.connect(p); print(c.execute('SELECT count(*) FROM Name2Id').fetchone())"
```
Expected: 打印一个 `(N,)`，N≥1（明文可读、有会话）。

- [ ] **Step 4: Commit**

```bash
git add scripts/windows/extract_key.ps1
git commit -m "feat(win): extract_key.ps1 via wechat-dump-rs (key dump + full decrypt)"
```

---

## Task 6: frida 回退（VM gate，仅主路失败时启用）

**Files:**
- Create: `scripts/windows/hook_sqlite3_key_win.js`
- Create: `scripts/windows/extract_key_frida.ps1`

- [ ] **Step 1: 写 frida hook 脚本**

`scripts/windows/hook_sqlite3_key_win.js`:
```javascript
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
```

- [ ] **Step 2: 写 frida 驱动脚本**

`scripts/windows/extract_key_frida.ps1`:
```powershell
# 回退：frida 注入微信抓 sqlite3_key。前置：pip install frida-tools；微信正在运行。
# 注意：若 [miss] export not found，说明微信静态内联了 SQLCipher，符号不可见——
#       此路不通，记录为 ARM/环境局限，改在 x86_64 真机用 wechat-dump-rs。
$ErrorActionPreference = "Stop"
$SKILL_DIR = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$JS = Join-Path $SKILL_DIR "scripts\windows\hook_sqlite3_key_win.js"
$proc = Get-Process -Name "Weixin","WeChat" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $proc) { Write-Error "未找到微信进程（Weixin/WeChat）" }
Write-Host "注入 PID=$($proc.Id)；登录后触发数据库访问以命中 [KEY] ..."
frida -p $proc.Id -l $JS
```

- [ ] **Step 3: VM 验证 gate（仅当 Task 5 失败）**

```powershell
pip install frida-tools
powershell -ExecutionPolicy Bypass -File $env:USERPROFILE\.claude\skills\wechat-decrypt\scripts\windows\extract_key_frida.ps1
```
Expected（成功）：输出 `[KEY] sqlite3_key len=32 hex=<64hex>` → 手动写入 `key.txt`，再用 `wechat-dump-rs -k <key> -d <原始db目录> -o decrypted` 离线解密。
Expected（不通）：`[miss] export not found` → 记录环境局限，转 x86_64 真机。

- [ ] **Step 4: Commit**

```bash
git add scripts/windows/hook_sqlite3_key_win.js scripts/windows/extract_key_frida.ps1
git commit -m "feat(win): frida fallback for key extraction (sqlite3_key hook)"
```

---

## Task 7: setup.ps1 完善（VM gate）

**Files:**
- Modify: `setup.ps1`

- [ ] **Step 1: 重写 setup.ps1**

`setup.ps1`:
```powershell
# WeChat Decrypt — Windows 安装
$ErrorActionPreference = "Stop"
$SKILL_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "=== WeChat Decrypt 安装 (Windows) ==="

Write-Host "[1/4] 安装 Python 依赖 (mcp pilk faster-whisper)..."
python -m pip install --quiet mcp pilk faster-whisper

$DUMP = Join-Path $SKILL_DIR "wechat-dump-rs.exe"
if (-not (Test-Path $DUMP)) {
    Write-Host "[2/4] 缺少 wechat-dump-rs.exe"
    Write-Host "  下载: https://github.com/0xlane/wechat-dump-rs/releases -> 放到 $DUMP"
} else {
    Write-Host "[2/4] wechat-dump-rs.exe 已就位"
}

Write-Host "[3/4] 注册 MCP Server..."
$SERVER = Join-Path $SKILL_DIR "server.py"
claude mcp remove wechat -s user 2>$null
claude mcp add -s user wechat python $SERVER

Write-Host "[4/4] 完成。后续：登录微信 -> scripts\windows\extract_key.ps1 -> 重启 Claude Code"
```

- [ ] **Step 2: VM 验证 gate**

```powershell
powershell -ExecutionPolicy Bypass -File $env:USERPROFILE\.claude\skills\wechat-decrypt\setup.ps1
claude mcp list
```
Expected: 依赖装好；`claude mcp list` 含 `wechat`（重启 CC 后 Connected）。

- [ ] **Step 3: MCP 工具 gate（重启 Claude Code 后）**

在 VM 的 Claude Code 内逐一验证 5 工具返回数据：
`wechat_list_chats` / `wechat_recent_messages` / `wechat_chat_summary` / `wechat_read_chat` / `wechat_search_messages`。
Expected: 至少 `wechat_list_chats` 列出 ≥1 会话。

- [ ] **Step 4: 导出 gate**

```powershell
python $env:USERPROFILE\.claude\skills\wechat-decrypt\scripts\common\export_chat.py <某联系人> --year 2026 -o $env:USERPROFILE\Desktop\out.txt
```
Expected: 桌面生成 out.txt，内容为该对话消息。

- [ ] **Step 5: 语音转写 gate**

```powershell
python $env:USERPROFILE\.claude\skills\wechat-decrypt\scripts\common\transcribe_db.py <某联系人> --limit 1
```
Expected: 首次下载 faster-whisper large-v3 模型，转出 ≥1 条中文文本（慢属正常，可改 `--model medium`）。

- [ ] **Step 6: Commit**

```bash
git add setup.ps1
git commit -m "feat(win): finalize setup.ps1 (deps + mcp registration)"
```

---

## Task 8: 文档回填（VM 全 gate 通过后）

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`

- [ ] **Step 1: SKILL.md —— Windows 段从「未测试」改「已验证」**

把 `## Windows（⚠️ 未经测试）` 整段替换为已验证流程：路线 Y（wechat-dump-rs `-a` 解密→`decrypted/`→内置 sqlite3 读）、setup.ps1、extract_key.ps1、frida 回退条件；并记录**实测架构（ARM64/x86_64）**与坑（dump-rs 在该架构是否成功、CPU 占用、faster-whisper 速度）。

- [ ] **Step 2: README.md 同步**

更新平台支持表：Windows 标「已验证（架构: <实测>）」，补 setup/提 key/读库/语音转写差异说明。

- [ ] **Step 3: Commit**

```bash
git add SKILL.md README.md
git commit -m "docs(win): mark windows verified, record arch findings + pitfalls"
```

---

## Self-Review 结果

- **Spec 覆盖**：提 key(T5/T6)、路线 Y 读库(T1-T3)、语音分派(T4)、setup(T7)、文档(T8)、风险回退(T6 frida + T5 gate)——全覆盖。
- **占位扫描**：无 TBD/TODO；脚本与测试均含完整代码。VM gate 的「实测架构」是运行时填入的真实数据，非占位。
- **类型一致**：`DB_BACKEND`/`DECRYPTED_DIR`/`_exec_sqlite3`/`_find_decrypted_data_dir`/`_transcribe_wav`/`_fw_model` 在定义与调用处签名一致；`query→list[dict]`、`query_raw→list[str]`、`_transcribe_wav→str` 贯穿一致。
- **macOS 零回归**：所有改动以 `if config.DB_BACKEND == "sqlite3"` / `if IS_MACOS` 顶部分派，sqlcipher 原路径字节不变；Task 3 Step 4 全量回归 gate 兜底。

## 跨环境执行约定

- Task 0-4：macOS 本地 pytest（写代码=我，跑测试需你授权）。
- Task 5-8：UTM Windows VM 内执行（代码经 git 同步进 VM：VM 内 `git clone`/`pull` 本 skill 仓库）。
- 架构确认（`$env:PROCESSOR_ARCHITECTURE`）结果回填 Task 8 文档。

---

## 实现记录（2026-06-05，Task 0-4 完成）

**测试环境**：pytest 装入 `/opt/homebrew/bin/python3`(3.14，含 skill 运行时依赖)，统一 `/opt/homebrew/bin/python3 -m pytest`。Task 0-4 全部 macOS 本地 TDD，**13 passing**。

**执行偏差**：Task 2+3 合并为单次 db.py 改造（原子提交，测试只有两者都完成才全绿）。

**Final review 修复**（commit `cf86886`，两处被 macOS-only 测试掩盖的真实 Windows 缺陷）：
1. `db.get_message_dbs` 加 `DB_BACKEND=="sqlite3"` guard——否则 Windows 仍需 gitignored 的 `key.txt`（破坏 frida 回退/预解密场景）。
2. **后端契约差异（根因）**：sqlite3 后端返回**原生类型**（`server_id`/`svr_id` 是 INTEGER），sqlcipher CSV 返回**全字符串**。语音路径 `",".join(int_sids)` 直接 TypeError。已在 `transcribe_db.py`(`_fetch_blobs`/`transcribe_contact`) + `export_chat.py`(`format_row` voice 对齐) 的 server_id/svr_id 边界 `str()` 化。核心读路径靠 `message.py` 的 `int()` 包裹自然吸收，无需改。**不要全局 str 化 `db.query`**（BLOB 列须保持 bytes）。
3. faster-whisper 分段 `.text` 带前导空格 → `s.text.strip()`。
新增测试：get_message_dbs 无 key、int server_id、get_my_wxid。

## VM 验证清单（macOS 无法证明，Task 5-8 在 VM 重点核对）
1. **get_my_wxid 目录名假设（最高风险）**：依赖解密产物保留 `<wxid>_<device>` 账户目录名。VM 确认布局为 `decrypted/<wxid>_<device>/db_storage/message/message_0.db`，且 `get_my_wxid()` 返回真实 wxid（非 fixture 的占位）。若 wechat-dump-rs 扁平化/重命名账户目录，`get_my_wxid` 与 export 的「自己发的」判定会错。
2. `_find_decrypted_data_dir` 的 dirname^2 + 递归 glob 命中正确 `db_storage`，无杂散 `message_0.db`。
3. wechat-dump-rs 输出确为明文 sqlite（内置 `sqlite3` 直开，无需 cipher）。
4. #1/#2 修复在 VM 生效：`get_message_dbs` 无需 `key.txt`；`--transcribe` 不 TypeError。
5. faster-whisper large-v3 CPU 实转 ≥1 条中文（慢则降 `medium`）。
6. `export_chat.py` zstd-missing 错误串硬编码 `/opt/homebrew/bin/python3`（仅打印不执行，Task 8 docs 顺带修）。
