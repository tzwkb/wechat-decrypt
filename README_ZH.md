# wechat-decrypt

[![tests](https://github.com/tzwkb/wechat-decrypt/actions/workflows/tests.yml/badge.svg)](https://github.com/tzwkb/wechat-decrypt/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

[English](README.md) | 中文

一个本地优先的 [Codex Skill](https://developers.openai.com/codex/skills)：在 macOS 和 Windows 上读取、搜索、总结、导出并转写 WeChat 4.x 聊天记录。命令行核心不依赖 MCP；随附服务提供可选的 [Codex MCP](https://developers.openai.com/codex/mcp) 门面。

仅用于你本人拥有或获授权访问的本地数据。

## 能力

- 列出会话，解析备注、昵称、微信号和群名。
- 跨多个数据库分片读取、搜索、总结和统计消息。
- 识别拍一拍、撤回、群/好友变更、红包、转账、通话、置顶及未知系统事件。
- 解析音乐、视频链接、视频号/直播、小程序、文件、引用及未知分享卡片，保留标题、描述、来源和 URL。
- 按联系人和日期范围完整导出，不设人为条数上限。
- 用 Whisper 转写已经下载到本地的 SILK 语音。
- 自检安装状态，但不暴露 raw key。
- 提供已验证的 macOS 与 Windows 密钥/解密流程。

```text
macOS:  微信加密库 ── raw key ── SQLCipher 只读 ───────┐
                                                       ├─ query.py ── CLI / MCP
Windows: 微信加密库 ── raw key ── 私有明文镜像只读 ──┘             └─ 导出 / 语音
```

## 快速开始

克隆仓库后，在仓库根目录运行安装脚本。

### macOS

```bash
bash setup.sh
.venv/bin/python scripts/common/doctor.py --json
```

安装脚本会创建隔离的 `.venv`、安装 SQLCipher 与 Python 依赖、把当前仓库链接到 `$HOME/.agents/skills/wechat-decrypt`，并向 Codex 注册 `wechat` stdio MCP。旧 `$HOME/.codex/skills/wechat-decrypt` 中缺失的密钥和本地缓存会被迁移，但绝不覆盖当前文件。如果用户 Skill 已指向其他仓库，先检查旧目录，再执行 `bash setup.sh --upgrade`；旧路径会保留为带时间戳的备份。

普通安装保持轻量。仅在需要本地语音转写时执行 `bash setup.sh --with-voice`；它会安装较大的 ML 运行库，但不会下载约 3 GB 的模型。

首次提取密钥需要临时 ad-hoc 重签名：

```bash
sudo codesign --force --deep --sign - /Applications/WeChat.app
bash scripts/macos/extract_key.sh
```

脚本会关闭微信，通过 Frida 启动并等待扫码登录。成功后，从 App Store 或微信官网重装微信，恢复腾讯官方签名。提取前先读 [macOS 指南](references/macos.md)。

### Windows

```powershell
powershell -File setup.ps1
$Python = ".\.venv\Scripts\python.exe"
& $Python scripts\windows\extract_raw_key.py
& $Python scripts\windows\decrypt_all.py
& $Python scripts\common\doctor.py --json
```

提取器会关闭微信，并要求你从可见桌面手动重启。随后 `decrypt_all.py` 创建私有的本地明文镜像，查询层只读访问它。详见 [Windows 指南](references/windows.md)。

已有用户 Skill junction 指向其他目录时，使用 `powershell -File setup.ps1 -Upgrade`。私有文件仅在目标缺失时复制；现有 `decrypted/` 明文镜像会建立目录链接，不重复复制。

Windows 可用 `powershell -File setup.ps1 -WithVoice` 安装可选语音栈；普通查询和导出不依赖它。

## 查询

Agent 调用建议使用 `--json`；人工调试可省略。

```bash
.venv/bin/python scripts/common/query.py list --json
.venv/bin/python scripts/common/query.py read "张三" -d 7 -n 50 --json
.venv/bin/python scripts/common/query.py search "截止时间" -d 30 -n 50 --json
.venv/bin/python scripts/common/query.py recent -d 3 -n 100 --json
.venv/bin/python scripts/common/query.py summary -d 3 --json
.venv/bin/python scripts/common/query.py events -e 拍一拍 -d 30 -n 100 --json
```

稳定事件码包括 `pat`、`recall`、`group_join`、`group_remove`、`group_leave`、`group_rename`、`group_notice`、`group_admin`、`group_owner`、`group_disband`、`friend_added`、`red_packet`、`payment`、`call`、`chat_pinned` 和 `system`；也可直接使用中文标签筛选。

类型 49 分享卡片会在读取、搜索、摘要、统计和导出中统一解析。JSON 输出额外包含 `app` 字段，提供稳定类型、标题、描述、来源、URL 及音乐/视频号/小程序等专属元数据；未知子类型保留通用卡片字段，原始本地载荷仍可搜索。

搜索会分批解码全部压缩正文及类型 49 候选，不再受“最近若干条卡片”的固定窗口限制，也不会建立持久化明文搜索索引。

MCP 暴露相同核心能力：

| 工具 | 用途 |
|---|---|
| `wechat_list_chats` | 列出会话 |
| `wechat_read_chat` | 读取联系人或群聊 |
| `wechat_search_messages` | 全文搜索 |
| `wechat_recent_messages` | 查看最近动态 |
| `wechat_chat_summary` | 提供结构化近期聊天上下文 |
| `wechat_system_events` | 拍一拍、撤回、群/好友变更、红包、转账、通话、置顶及未知事件 |

## 导出与语音

```bash
.venv/bin/python scripts/common/export_chat.py "张三" --year 2026 -o ~/Desktop/zhangsan-2026.txt
.venv/bin/python scripts/common/export_chat.py "张三" --start 2026-01-01 --end 2026-06-30
```

平台对应的 Whisper large-v3 模型已缓存时，语音默认自动转写；模型不在时，普通导出保留 `[Audio]`，不会自行下载。只有确认约 3 GB 的首次下载后才使用 `--transcribe`；用 `--no-transcribe` 可明确关闭。详见 [导出与转写指南](references/export-transcription.md)。

## 安全模型

- 查询后端始终只读打开数据库；SQLite 额外启用 `query_only`。
- Raw key 会校验格式、以私有权限保存、被 Git 忽略，提取器和自检均不回显。
- 明文数据库、导出、派生密钥缓存和语音缓存尽可能使用私有权限。
- 项目不上传聊天数据，也不调用云端语音转写服务。
- 严禁提交 `key.txt`、`key_windows.txt`、`decrypted/`、`all_keys.json`、`contacts.json`、`voice_cache.json`。

## 开发

单元测试使用合成数据库，不读取个人微信数据。Windows 提取器测试还会用 Node.js 22 或更新版本，在合成内存上执行内嵌 JavaScript。测试依赖安装命令：`python3 -m pip install pytest pycryptodome 'mcp[cli]>=1,<2'`。

```bash
python3 -m pytest -q
python3 -m compileall -q appmsg.py config.py contacts.py crypto.py db.py message.py server.py scripts/common scripts/windows
bash -n setup.sh scripts/macos/extract_key.sh
.venv/bin/python -c "import asyncio, server; assert len(asyncio.run(server.mcp.list_tools())) == 6"
```

真实数据检查见 [e2e/README.md](e2e/README.md)。Skill 入口是 [SKILL.md](SKILL.md)；平台和导出细节放在 `references/`，减少 Agent 默认上下文。

## License

MIT
