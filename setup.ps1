param(
    [switch]$Upgrade,
    [switch]$WithVoice
)

$ErrorActionPreference = "Stop"
$SkillDir = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$VenvDir = Join-Path $SkillDir ".venv"
$UserSkillDir = Join-Path $HOME ".agents\skills\wechat-decrypt"
$LegacySkillDir = Join-Path $HOME ".codex\skills\wechat-decrypt"
$BackupRoot = Join-Path $HOME ".agents\backups"
Write-Host "=== WeChat Decrypt 安装（Windows / Codex）==="

$BootstrapPython = (Get-Command python -ErrorAction Stop).Source
& $BootstrapPython -c "import sys; raise SystemExit(sys.version_info < (3, 10))"
if ($LASTEXITCODE -ne 0) { throw "需要 Python 3.10+" }

$SameInstall = $false
if (Test-Path $UserSkillDir) {
    & $BootstrapPython -c "import os,sys; raise SystemExit(0 if os.path.samefile(sys.argv[1], sys.argv[2]) else 1)" $UserSkillDir $SkillDir
    $SameInstall = $LASTEXITCODE -eq 0
    if (-not $SameInstall -and -not $Upgrade) {
        throw "$UserSkillDir 指向另一个安装。确认切换后运行: powershell -File setup.ps1 -Upgrade"
    }
}

Write-Host "[1/5] 创建隔离 Python 环境..."
& $BootstrapPython -m venv $VenvDir
$Python = Join-Path $VenvDir "Scripts\python.exe"
& $Python -m pip install --upgrade pip

Write-Host "[2/5] 安装 Python 依赖..."
& $Python -m pip install -r (Join-Path $SkillDir "requirements-windows.txt")
if ($LASTEXITCODE -ne 0) { throw "Windows 依赖安装失败" }
if ($WithVoice) {
    & $Python -m pip install pilk faster-whisper
} else {
    Write-Host "  已跳过可选语音依赖；需要时运行: powershell -File setup.ps1 -WithVoice"
}

Write-Host "[3/5] 迁移私有状态并注册用户 Skill..."
$Parent = Split-Path -Parent $UserSkillDir
New-Item -ItemType Directory -Force -Path $Parent | Out-Null
$BackupSkillDir = $null
$NewLinkCreated = $false
if (Test-Path $UserSkillDir) {
    if ($SameInstall) {
        Write-Host "  已链接: $UserSkillDir"
    } else {
        $Stamp = Get-Date -Format "yyyyMMddHHmmss"
        New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
        $BackupSkillDir = Join-Path $BackupRoot "wechat-decrypt.$Stamp.$PID"
        Move-Item -LiteralPath $UserSkillDir -Destination $BackupSkillDir
        New-Item -ItemType Junction -Path $UserSkillDir -Target $SkillDir | Out-Null
        $NewLinkCreated = $true
        Write-Host "  旧安装已备份: $BackupSkillDir"
        Write-Host "  已链接: $UserSkillDir -> $SkillDir"
    }
} else {
    New-Item -ItemType Junction -Path $UserSkillDir -Target $SkillDir | Out-Null
    $NewLinkCreated = $true
    Write-Host "  已链接: $UserSkillDir -> $SkillDir"
}

$MigrationScript = Join-Path $SkillDir "scripts\common\migrate_private_state.py"
$MigrationArgs = @($MigrationScript, "--target", $SkillDir)
if ($BackupSkillDir) {
    $MigrationArgs += @("--source", $BackupSkillDir)
}
$MigrationArgs += @("--source", $LegacySkillDir)
& $Python @MigrationArgs
if ($LASTEXITCODE -ne 0) {
    Write-Warning "私有状态迁移失败，正在恢复用户 Skill 链接。"
    if ($NewLinkCreated -and (Test-Path $UserSkillDir)) {
        Remove-Item -LiteralPath $UserSkillDir -Force
    }
    if ($BackupSkillDir -and -not (Test-Path $UserSkillDir)) {
        Move-Item -LiteralPath $BackupSkillDir -Destination $UserSkillDir
    }
    throw "私有状态迁移失败"
}

Write-Host "[4/5] 验证基础依赖..."
& $Python -c "import mcp, frida, Crypto, zstandard; print('core dependencies OK')"
if ($WithVoice) {
    & $Python -c "import pilk, faster_whisper; print('voice dependencies OK')"
}

Write-Host "[5/5] 注册 Codex MCP Server..."
$Server = Join-Path $SkillDir "server.py"
if (Get-Command codex -ErrorAction SilentlyContinue) {
    codex mcp remove wechat 2>$null
    codex mcp add wechat -- $Python $Server
    if ($LASTEXITCODE -ne 0) { throw "Codex MCP 注册失败" }
} else {
    Write-Warning "未找到 Codex CLI；可先用 query.py，安装 Codex 后重跑 setup.ps1。"
}

Write-Host ""
Write-Host "=== 安装完成 ==="
$KeyPath = Join-Path $SkillDir "key_windows.txt"
$DecryptedPath = Join-Path $SkillDir "decrypted"
if ((Test-Path $KeyPath) -and (Test-Path $DecryptedPath)) {
    Write-Host "已保留现有密钥和明文镜像。运行自检后重启 Codex:"
    Write-Host "  & '$Python' scripts\common\doctor.py"
} else {
    Write-Host "首次提取流程:"
    Write-Host "  1. 登录微信"
    Write-Host "  2. & '$Python' scripts\windows\extract_raw_key.py"
    Write-Host "  3. & '$Python' scripts\windows\decrypt_all.py"
    Write-Host "  4. & '$Python' scripts\common\doctor.py"
    Write-Host "  5. 重启 Codex"
}
