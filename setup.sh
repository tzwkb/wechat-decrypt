#!/bin/bash
# WeChat Decrypt Skill + MCP Server — macOS installer
# Usage: bash setup.sh
set -e

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"

# Platform check
if [[ "$(uname)" != "Darwin" ]]; then
    echo "此脚本仅适用于 macOS。Windows 请用: powershell -File setup.ps1"
    exit 1
fi

echo "=== WeChat Decrypt 安装 (macOS) ==="
echo "目录: $SKILL_DIR"
echo ""

PYTHON="/opt/homebrew/bin/python3"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"

# 1. Python 解释器
echo "[1/5] 使用全局 Python: $PYTHON ($("$PYTHON" --version))"

# 2. SQLCipher
echo "[2/5] 检查 sqlcipher..."
if ! command -v sqlcipher &>/dev/null; then
    echo "  通过 Homebrew 安装..."
    brew install sqlcipher
fi
echo "  sqlcipher: $(which sqlcipher)"

# 3. Dependencies（全局安装；Homebrew Python 需 --break-system-packages）
echo "[3/5] 安装 Python 依赖（全局）..."
"$PYTHON" -m pip install --break-system-packages --quiet \
    mcp frida-tools zstd cryptography requests 2>&1 | tail -1
# 语音转写依赖（pilk 解码 SILK + mlx-whisper；mlx 仅 Apple Silicon，装不上不影响其余功能）
"$PYTHON" -m pip install --break-system-packages --quiet pilk mlx-whisper 2>&1 | tail -1

# 4. Verify
echo "[4/5] 检查依赖..."
"$PYTHON" -c "import mcp, frida, zstd, cryptography, pilk; print('  mcp + frida + zstd + pilk OK')" 2>/dev/null || {
    echo "  [!] 安装失败，手动执行:"
    echo "      $PYTHON -m pip install --break-system-packages mcp frida-tools zstd cryptography requests"
}

# 5. MCP registration
echo "[5/5] 注册 MCP Server..."
if command -v claude &>/dev/null; then
    claude mcp remove wechat -s user 2>/dev/null || true
    claude mcp add -s user wechat \
        "$PYTHON" \
        "$SKILL_DIR/server.py" 2>&1
    echo "  MCP 已注册"
else
    echo "  Claude Code 未安装，跳过"
fi

echo ""
echo "=== 安装完成 ==="
echo ""
echo "后续步骤:"
echo "  1. sudo codesign --force --deep --sign - /Applications/WeChat.app"
echo "  2. 重启微信"
echo "  3. 提取密钥: 看 SKILL.md → 密钥提取 → macOS"
echo "  4. 重启 Claude Code"
