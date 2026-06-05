#!/bin/bash
# ============================================================
# WeChat Voice Transcriber — lazy dependency check + capture + transcribe
#
# Called by export_chat.py when voice messages are detected.
# Agent just runs this script; all logic is self-contained.
#
# Usage:
#   bash transcribe_voice.sh <contact_wxid> <output_json>
#   bash transcribe_voice.sh --check-deps   # check & install deps only
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
FFMPEG="/opt/homebrew/bin/ffmpeg"
BLACKHOLE_DRIVER="/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver"
TRANSCRIBE_SWIFT="$SCRIPT_DIR/transcribe.swift"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[transcribe]${NC} $*"; }
warn() { echo -e "${YELLOW}[transcribe]${NC} $*"; }
err()  { echo -e "${RED}[transcribe]${NC} $*" >&2; }

# ── Dependency check ──────────────────────────────────────

check_deps() {
    local missing=()

    if [ ! -x "$FFMPEG" ]; then
        warn "ffmpeg 未安装，正在通过 Homebrew 安装..."
        brew install ffmpeg || { err "ffmpeg 安装失败"; return 1; }
    fi

    if [ ! -d "$BLACKHOLE_DRIVER" ]; then
        warn "BlackHole 未安装，正在安装..."
        brew install --cask blackhole-2ch || { err "BlackHole 安装失败"; return 1; }
        warn "⚠️  需要重启才能使用 BlackHole。请重启后重新导出。"
        return 1
    fi

    # Verify BlackHole is loaded.
    # ffmpeg -list_devices always exits non-zero; under `set -o pipefail`
    # that masks grep's match, so capture output first then grep separately.
    local devices
    devices="$("$FFMPEG" -f avfoundation -list_devices true -i "" 2>&1 || true)"
    if ! grep -qi "BlackHole" <<< "$devices"; then
        warn "BlackHole 驱动未加载，可能需要重启系统"
        return 1
    fi

    if [ ! -f "$TRANSCRIBE_SWIFT" ]; then
        err "transcribe.swift 未找到"
        return 1
    fi

    log "所有依赖就绪 ✓"
    return 0
}

# ── Capture from BlackHole ────────────────────────────────

capture_voices() {
    local output_dir="$1"
    local voice_count="$2"

    mkdir -p "$output_dir"

    echo ""
    log "══════════════════════════════════════════"
    log " 请在微信中依次播放 ${voice_count} 条语音消息"
    log " 每播完一条，等待 2 秒停顿再播下一条"
    log " 全部播完后按 Ctrl+C 结束录音"
    log "══════════════════════════════════════════"
    echo ""

    # Record from BlackHole, split by silence
    # -af silencedetect detects silence gaps
    # We record as WAV then split with a Python helper
    local raw_file="$output_dir/raw_recording.wav"

    log "开始录音..."
    "$FFMPEG" -y \
        -f avfoundation \
        -i ":BlackHole 2ch" \
        -ac 1 -ar 16000 -sample_fmt s16 \
        -f segment -segment_time 60 \
        "$output_dir/seg_%03d.wav" \
        2>&1 &
    local FFMPEG_PID=$!

    echo ""
    warn "录音中... 播完所有语音后按 Enter 停止"
    read -r

    kill "$FFMPEG_PID" 2>/dev/null || true
    wait "$FFMPEG_PID" 2>/dev/null || true

    log "录音已停止"
    log "找到 $(find "$output_dir" -name 'seg_*.wav' | wc -l) 个音频片段"
}

# ── Split by silence ──────────────────────────────────────

split_by_silence() {
    local work_dir="$1"

    # Use ffmpeg silencedetect to split the raw audio by silence gaps
    # Then use Python to parse the timestamps and split

    log "按静音分割音频..."

    python3 - "$work_dir" << 'PYEOF'
import sys, os, subprocess

work_dir = sys.argv[1]
# Find all segments
import glob
segs = sorted(glob.glob(os.path.join(work_dir, "seg_*.wav")))

if not segs:
    print("No segments found", file=sys.stderr)
    sys.exit(0)

# Concatenate into one file
concat_list = os.path.join(work_dir, "concat.txt")
with open(concat_list, "w") as f:
    for s in segs:
        f.write(f"file '{os.path.basename(s)}'\n")

raw = os.path.join(work_dir, "raw.wav")
subprocess.run([
    "/opt/homebrew/bin/ffmpeg", "-y",
    "-f", "concat", "-safe", "0", "-i", concat_list,
    "-ac", "1", "-ar", "16000", raw
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

# Detect silence
result = subprocess.run([
    "/opt/homebrew/bin/ffmpeg",
    "-i", raw,
    "-af", "silencedetect=noise=-30dB:d=1.5",
    "-f", "null", "-"
], capture_output=True, text=True)

# Parse silence_end and silence_start timestamps
import re
ends = [0.0]
starts = []
for line in result.stderr.split("\n"):
    m = re.search(r"silence_start: ([\d.]+)", line)
    if m:
        starts.append(float(m.group(1)))
    m = re.search(r"silence_end: ([\d.]+)", line)
    if m:
        ends.append(float(m.group(1)))

# Keep only gaps >= 1.5s (real pauses between messages)
gaps = []
for i, (end, start) in enumerate(list(zip(ends, starts))[:]):
    if start - end >= 1.5:
        gaps.append((end, start))

# Split audio at gap midpoints
clips_dir = os.path.join(work_dir, "clips")
os.makedirs(clips_dir, exist_ok=True)

import shutil
if not gaps:
    # Single clip
    shutil.copy(raw, os.path.join(clips_dir, "clip_000.wav"))
    print(f"1 clips created (no silence gaps detected)")
else:
    split_points = [(gaps[i-1][1] + gaps[i][0]) / 2 for i in range(1, len(gaps))]
    split_points = [0.0] + split_points + [999999.0]

    # Actually extract segments using the gap-detected regions
    for i, gap in enumerate(gaps):
        start_time = gap[0]
        duration = gap[1] - gap[0]
        if duration > 0.5:  # Only keep clips with actual content
            out = os.path.join(clips_dir, f"clip_{i:03d}.wav")
            subprocess.run([
                "/opt/homebrew/bin/ffmpeg", "-y",
                "-ss", str(start_time),
                "-t", str(duration),
                "-i", raw,
                "-ac", "1", "-ar", "16000",
                out
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    print(f"{len(gaps)} clips created")

PYEOF

    local clip_count=$(find "$work_dir/clips" -name 'clip_*.wav' 2>/dev/null | wc -l)
    echo "$clip_count"
}

# ── Transcribe ────────────────────────────────────────────

run_transcription() {
    local work_dir="$1"
    local clips_dir="$work_dir/clips"

    if [ ! -d "$clips_dir" ] || [ -z "$(ls -A "$clips_dir" 2>/dev/null)" ]; then
        err "没有音频片段可转写"
        return 1
    fi

    log "转写中（使用 macOS 内置语音识别）..."

    # Build file list for Swift transcriber
    local filelist="$work_dir/filelist.txt"
    find "$clips_dir" -name 'clip_*.wav' | sort > "$filelist"

    # Run Swift transcriber
    local count=$(wc -l < "$filelist" | tr -d ' ')
    log "共 $count 个片段，预计需要 $((count * 3)) 秒..."

    # Pass files via stdin to Swift script
    swift "$TRANSCRIBE_SWIFT" < "$filelist" > "$work_dir/transcriptions.tsv" 2>&1 || {
        err "转写失败"
        return 1
    }

    # Build JSON output: { "index": "text", ... }
    python3 - "$work_dir" << 'PYEOF'
import sys, os, json

work_dir = sys.argv[1]
tsv_file = os.path.join(work_dir, "transcriptions.tsv")

results = {}
if os.path.exists(tsv_file):
    with open(tsv_file) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            parts = line.split("\t", 2)
            if len(parts) >= 3:
                idx = int(parts[0])
                text = parts[2].strip()
                if text:
                    results[str(idx)] = text

out_file = os.path.join(work_dir, "transcription_map.json")
with open(out_file, "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(json.dumps(results, ensure_ascii=False))
PYEOF
}

# ── Main ──────────────────────────────────────────────────

if [ "${1:-}" = "--check-deps" ]; then
    check_deps
    exit $?
fi

CONTACT="${1:-}"
OUTPUT_JSON="${2:-/dev/stdout}"

if [ -z "$CONTACT" ]; then
    err "Usage: transcribe_voice.sh <contact_wxid> [output_json]"
    exit 1
fi

# Lazy check
if ! check_deps; then
    err "依赖未就绪，无法转写语音"
    exit 1
fi

# Get voice message count from the DB
VOICE_COUNT=$(python3 - "$CONTACT" << 'PYEOF'
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db, contacts
contact = sys.argv[1]
name2id = db.get_name2id()
matched = contacts.find_contact(contact, name2id)
if not matched:
    print(0)
    sys.exit()
table = matched[0][0]
dbs = db.get_message_dbs()
count = 0
for db_path in dbs:
    tables = [t.strip() for t in db.query_raw(db_path, "SELECT name FROM sqlite_master WHERE type='table';")]
    if table not in tables: continue
    rows = db.query(db_path, f"SELECT COUNT(*) as cnt FROM {table} WHERE local_type=34;")
    if rows:
        count += int(rows[0].get("cnt", 0))
print(count)
PYEOF
)

if [ "$VOICE_COUNT" -eq 0 ]; then
    log "该对话没有语音消息"
    echo "{}" > "$OUTPUT_JSON"
    exit 0
fi

log "检测到 ${VOICE_COUNT} 条语音消息"

WORK_DIR="$(mktemp -d)"
trap "rm -rf $WORK_DIR" EXIT

capture_voices "$WORK_DIR" "$VOICE_COUNT"

CLIP_COUNT=$(split_by_silence "$WORK_DIR")

log "分割出 ${CLIP_COUNT} 个片段"

TRANS_JSON=$(run_transcription "$WORK_DIR")
echo "$TRANS_JSON" > "$OUTPUT_JSON"

log "转写完成 → $OUTPUT_JSON"
