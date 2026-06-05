# WeChat Decrypt — Windows 安装
$ErrorActionPreference = "Stop"
$SKILL_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "=== WeChat Decrypt 安装 (Windows) ==="

Write-Host "[1/2] 安装 Python 依赖 (mcp frida pycryptodome pilk faster-whisper zstandard)..."
python -m pip install --quiet mcp frida pycryptodome pilk faster-whisper zstandard

Write-Host "[2/2] 注册 MCP Server..."
$SERVER = Join-Path $SKILL_DIR "server.py"
claude mcp remove wechat -s user 2>$null
claude mcp add -s user wechat python $SERVER

Write-Host ""
Write-Host "=== 完成。提取流程 ==="
Write-Host "  1. 登录微信"
Write-Host "  2. python scripts\windows\extract_raw_key.py   # 按提示重启微信，抓 raw key 写入 key_windows.txt"
Write-Host "  3. python scripts\windows\decrypt_all.py <raw_key>   # 解密所有库到 decrypted\"
Write-Host "  4. 重启 Claude Code，MCP 工具(wechat_*)即可用；导出/语音转写同 Mac"
