# 回退：frida 注入微信抓 sqlite3_key。前置：pip install frida-tools；微信正在运行。
# 注意：若 [miss] export not found，说明微信静态内联了 SQLCipher，符号不可见——
#       此路不通，记录为 ARM/环境局限，改在 x86_64 真机用 wechat-dump-rs。
$ErrorActionPreference = "Stop"
$SKILL_DIR = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$JS = Join-Path $SKILL_DIR "scripts\windows\hook_sqlite3_key_win.js"
$proc = Get-Process -Name "Weixin","WeChat" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $proc) { Write-Error "未找到微信进程（Weixin/WeChat）" }
Write-Host "注入 PID=$($proc.Id)；登录后触发数据库访问以命中 [KEY] ..."
frida -p $proc.Id -l $JS
