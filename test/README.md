# wechat-decrypt 测试

## 文件
| 文件 | 作用 |
|---|---|
| `test_e2e.py` | 端到端测试(双端 platform 自动分派, 8 子命令 + `--json`) |
| `check_consistency.py` | 架构一致性校验(skills↔langlobal 同步 + wechat↔wecom vendored 一致) |

> 另有单元测试(pytest, **无需真实数据**)在 `tests/`(langlobal):`python3 -m pytest tests/ -v`

## 跑法
```bash
python3 test/test_e2e.py            # 端到端 12 项(轻量)
python3 test/test_e2e.py --full     # + media/export(慢)
python3 test/check_consistency.py   # 一致性校验
```
退出码 0=全过 / 1=有失败,可接 CI。

## 端到端前提(不满足必挂)
先提 key + 解密:
- **macOS**: `scripts/macos/extract_key.sh`(扫码登录)
- **Windows**: `scripts/windows/extract_raw_key.py`(重启微信)→ `scripts/windows/decrypt_all.py`

## 改代码后 —— 确保一致性三步
```
改代码 → check_consistency.py(查漂移) → test_e2e.py(查功能) → 都绿才 commit
```
跨项目总指南见 `Langlobal/TESTING.md`;架构目标骨架见 `Langlobal/decrypt-modules-alignment.md`。
