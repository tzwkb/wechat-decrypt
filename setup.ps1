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
