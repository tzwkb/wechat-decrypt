#!/usr/bin/env python3
"""AES-CBC 后端 helper —— pycryptodome(Windows/VM ARM64) 优先, cryptography(macOS) 回退.

VENDORED: 两个解密项目(wechat-decrypt / wecom-agent)各一份相同代码, 改一处同步另一处.
解密核心 import 它, 避免 mac/win 因 AES 库不同而分叉.
"""

try:                                    # pycryptodome 优先(Windows / win-arm64 有 wheel)
    from Crypto.Cipher import AES

    def aes_cbc_decrypt(key, iv, ct):
        return AES.new(key, AES.MODE_CBC, iv).decrypt(ct)

    def aes_cbc_encrypt(key, iv, pt):
        return AES.new(key, AES.MODE_CBC, iv).encrypt(pt)
except ImportError:                     # 回退 cryptography(macOS 全局已装)
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    def aes_cbc_decrypt(key, iv, ct):
        d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        return d.update(ct) + d.finalize()

    def aes_cbc_encrypt(key, iv, pt):
        e = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return e.update(pt) + e.finalize()
