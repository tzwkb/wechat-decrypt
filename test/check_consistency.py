#!/usr/bin/env python3
"""架构一致性校验 —— 改/优化代码后跑它,确认没漂移。

查三类一致性:
  A. skills ↔ langlobal   每个项目: 运行单元(skills) 与 开发仓(langlobal) 同步
  B. wechat ↔ wecom        跨项目 vendored 文件(read_doc/crypto_backend)两份一致
退出码 0=全一致 / 1=有漂移(列出文件)。挂 git pre-commit 可强制。

用法: python3 check_consistency.py
"""
import hashlib
import os
import sys

H = os.path.expanduser("~")
SK_WX = f"{H}/.claude/skills/wechat-decrypt"
LG_WX = f"{H}/Desktop/Langlobal/wechat-decrypt"
SK_WC = f"{H}/.claude/skills/wecom-agent"
LG_WC = f"{H}/Desktop/Langlobal/wecom-agent"

SRC_EXT = (".py", ".md", ".sh", ".ps1", ".js", ".toml")
SKIP_DIR = (".git", "__pycache__", ".pytest_cache", "decrypted", "export", ".venv")
SKIP_FILE = {"key.txt", "key_windows.txt", "contacts.json", "all_keys.json", "wxwork_keys.json"}

drift = []


def md5(p):
    try:
        return hashlib.md5(open(p, "rb").read()).hexdigest()
    except OSError:
        return None


def check_sync(sk, lg, label):
    """遍历 skills 源文件, 比对 langlobal 同名(自动覆盖新增文件)。"""
    if not os.path.isdir(sk) or not os.path.isdir(lg):
        drift.append(f"[{label}] 目录缺失: {sk if not os.path.isdir(sk) else lg}")
        return
    for root, dirs, files in os.walk(sk):
        dirs[:] = [d for d in dirs if d not in SKIP_DIR]
        for f in files:
            if not f.endswith(SRC_EXT) or f in SKIP_FILE:
                continue
            rel = os.path.relpath(os.path.join(root, f), sk)
            a, b = os.path.join(sk, rel), os.path.join(lg, rel)
            if md5(a) != md5(b):
                drift.append(f"[{label}] {rel}" + ("" if os.path.exists(b) else "  (langlobal 缺)"))


def check_vendored(a, b, name):
    if md5(a) != md5(b):
        drift.append(f"[vendored wechat↔wecom] {name}  (两份不一致)")


# A. skills ↔ langlobal (两项目各一遍)
check_sync(SK_WX, LG_WX, "wechat skills↔langlobal")
check_sync(SK_WC, LG_WC, "wecom skills↔langlobal")

# B. wechat ↔ wecom vendored (跨项目共享文件)
check_vendored(f"{SK_WX}/scripts/common/read_doc.py", f"{SK_WC}/decrypt/read_doc.py", "read_doc.py")
check_vendored(f"{SK_WX}/scripts/common/crypto_backend.py", f"{SK_WC}/decrypt/crypto_backend.py", "crypto_backend.py")
check_vendored(f"{SK_WX}/test/check_consistency.py", f"{SK_WC}/decrypt/test/check_consistency.py", "check_consistency.py")

if drift:
    print(f"⚠️ 架构漂移 {len(drift)} 处:")
    for d in drift:
        print("  " + d)
    print("\n修复: 同步漂移文件(skills↔langlobal 用 cp; vendored 改完两边各放一份)。")
    sys.exit(1)
print("✓ 一致性全部通过 (skills↔langlobal 同步 + wechat↔wecom vendored 一致)")
