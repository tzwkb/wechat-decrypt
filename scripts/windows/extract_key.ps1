# WeChat key 提取 + 全库解密（Windows 主路：wechat-dump-rs）
# 前置：微信 4.x 已登录运行；wechat-dump-rs.exe 在 skill 根目录
$ErrorActionPreference = "Stop"
$SKILL_DIR = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
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
