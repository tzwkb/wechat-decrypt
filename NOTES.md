# Notes

## 语音转写架构（2026-06 重构）

语音音频存于 `media_0.db` 的 `VoiceInfo.voice_data`（SILK v3，首字节 0x02 私有前缀），按 `svr_id == message.server_id` 精确对齐。链路：VoiceInfo 直取 → pilk 解码 → mlx-whisper large-v3。全自动、批量、纯离线，取代旧 BlackHole+Swift 方案（移至 `scripts/legacy/`）。

## 已实测（2026-06，某联系人 45/60）

- 端到端通过：VoiceInfo→pilk→mlx-whisper large-v3，中文流畅带标点，质量可用。
- 能否转写取决于音频是否已下载本地，由 message 表 `download_status` 标记：
  `1/5`=已下载（VoiceInfo 有音频，可转），`0/4`=未下载（无音频，自动跳过）。
  实测某联系人 60 条 100% 对应：dl∈{1,5} 的 45 条全有音频，dl∈{0,4} 的 15 条全无。
  播放语音才触发下载——对方发来的（你会听）几乎都能转，自己发的（一般不回听）常缺。
  「没听过 = 没下载 = 没音频」，发送方只是表象。
- large-v3 偶输出繁体（繁简混合）。如需统一简体可接 `opencc` t2s。
