#!/usr/bin/env python3
"""导出微信聊天记录，自动按月分片。

Usage:
    python3 export_chat.py <contact> --year 2026 [-o ~/Desktop/out.txt]
    python3 export_chat.py <contact> --start 2026-01-01 --end 2026-06-03
"""

import sys
import os
import argparse
import json
import re
import html
from datetime import datetime, timedelta

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SKILL_DIR)

import db
import contacts
import message

_ZSTD_OK = True
try:
    import zstd as _zstd
    def _decompress(data: bytes) -> bytes:
        return _zstd.decompress(data)
except ImportError:
    try:
        import zstandard as _zstandard
        def _decompress(data: bytes) -> bytes:
            return _zstandard.ZstdDecompressor().decompress(data)
    except ImportError:
        try:
            import pyzstd as _pyzstd
            def _decompress(data: bytes) -> bytes:
                return _pyzstd.decompress(data)
        except ImportError:
            _ZSTD_OK = False
            def _decompress(data: bytes) -> bytes:
                raise RuntimeError("zstd not available")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

WHISPER_MODEL_DIR = os.path.expanduser(
    "~/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-mlx"
)


def model_cached() -> bool:
    """True if whisper is ready (mac: mlx model cached; else faster-whisper downloads on demand)."""
    import platform
    if platform.system() != "Darwin":
        return True
    return os.path.isdir(WHISPER_MODEL_DIR)


# Type 49 subtype labels (fallback for unknown subtypes)
_TYPE49_LABELS = {
    1: "Link", 3: "Music", 4: "Video Link", 5: "File",
    6: "MiniApp", 8: "Location", 17: "Location (Live)",
    21: "MiniApp", 33: "MiniApp", 36: "Link",
}

# Type labels for quoted message types
_REFER_TYPE_LABELS = {
    "3": "[Image]", "34": "[Audio]", "43": "[Video]", "47": "[Sticker]",
}


def chunk_by_month(start_dt, end_dt):
    chunks = []
    cur = start_dt
    while cur < end_dt:
        nxt = cur.replace(year=cur.year + 1, month=1, day=1) if cur.month == 12 \
              else cur.replace(month=cur.month + 1, day=1)
        end_chunk = min(nxt, end_dt)
        chunks.append((cur, end_chunk))
        cur = end_chunk
    return chunks


def _get_my_rowid(db_path: str) -> int | None:
    """Return my Name2Id rowid for this specific DB, or None if not found."""
    my_wxid = db.get_my_wxid()
    rows = db.query(db_path, f"SELECT rowid FROM Name2Id WHERE user_name='{my_wxid}';")
    if rows:
        try:
            return int(rows[0].get("rowid", ""))
        except (ValueError, TypeError):
            pass
    return None


def fetch(table, db_paths, since_dt, until_dt):
    since = int(since_dt.timestamp())
    until = int(until_dt.timestamp())
    rows = []
    for db_path in db_paths:
        tables = db.query_raw(db_path, "SELECT name FROM sqlite_master WHERE type='table';")
        if table not in {t.strip() for t in tables}:
            continue
        my_rowid = _get_my_rowid(db_path)
        is_me_expr = f"CASE WHEN m.real_sender_id={my_rowid} THEN '1' ELSE '0' END" \
                     if my_rowid is not None else "'0'"
        # Resolve sender wxid via this DB's own Name2Id (rowid is DB-local,
        # never share across DBs — see is_me / cross-DB rowid collision).
        batch = db.query(
            db_path,
            f"SELECT m.local_id, m.server_id, m.create_time, m.local_type, m.real_sender_id, "
            f"hex(m.message_content) as msg_hex, "
            f"{is_me_expr} as is_me, "
            f"n.user_name as sender_wxid "
            f"FROM {table} m "
            f"LEFT JOIN Name2Id n ON n.rowid = m.real_sender_id "
            f"WHERE m.create_time >= {since} AND m.create_time < {until} "
            f"ORDER BY m.create_time ASC;",
        )
        for r in batch:
            r["_db"] = db_path
        rows.extend(batch)
    return rows


def _decode_msg(hex_str: str) -> str:
    """Decode hex message_content: decompress zstd if needed, return UTF-8 string."""
    if not hex_str:
        return ""
    raw = bytes.fromhex(hex_str)
    compressed = raw[:4] == b'\x28\xb5\x2f\xfd'
    if compressed:
        raw = _decompress(raw)
    text = raw.decode("utf-8", errors="replace")
    # Strip sender prefix:
    #   compressed: "wxid_xxx:\n<content>"  (colon + newline)
    #   group plain: "wxid_xxx: <content>"  (colon + space)
    # Pattern is always <non-space, no-colon chars>: followed by \n or space
    m = re.match(r'^[^\s:]{1,60}:[\n ]', text)
    if m and (compressed or m.group(0).startswith("wxid_")):
        text = text[m.end():]
    return text


def _extract_refer(xml: str) -> tuple[str, str]:
    """Return (display_name, content_summary) from a <refermsg> block."""
    refer_name = re.search(r'<displayname>([^<]+)</displayname>', xml)
    refer_content = re.search(r'<content>([\s\S]*?)</content>', xml)
    if not refer_name or not refer_content:
        return "", ""
    name = refer_name.group(1).strip()
    rc_raw = html.unescape(refer_content.group(1)).strip()
    # If quoted content is itself XML, extract its title
    inner_title = re.search(r'<title>([^<]+)</title>', rc_raw)
    if inner_title:
        return name, inner_title.group(1).strip()
    # If quoted content is binary/empty, infer from <type> tag
    refer_type = re.search(r'<type>(\d+)</type>', xml[xml.find("<refermsg>"):])
    if not rc_raw or rc_raw.startswith("<"):
        label = _REFER_TYPE_LABELS.get(refer_type.group(1) if refer_type else "", "[Message]")
        return name, label
    return name, rc_raw.replace("\n", " ")


def format_row(row, voice_map=None, is_group=False, my_name="我", peer_name="对方"):
    ts = message.format_time(row.get("create_time", "0"))
    type_key = message.normalize_type(row.get("local_type", ""))
    hex_str = row.get("msg_hex") or ""

    # Determine speaker label (is_me + sender_wxid resolved per-DB in fetch())
    if row.get("is_me") == "1":
        direction = f"[{my_name}]"
    elif is_group:
        wxid = row.get("sender_wxid") or ""
        direction = f"[{contacts.resolve_nickname(wxid)}]" if wxid else "[对方]"
    else:
        direction = f"[{peer_name}]"

    if type_key in ("10000", "10002"):
        return f"[{ts}] [系统] {message.MSG_TYPES.get(type_key, '其他')}"
    if type_key == "3":
        return f"[{ts}] {direction} [Image]"
    if type_key == "43":
        return f"[{ts}] {direction} [Video]"
    if type_key == "47":
        return f"[{ts}] {direction} [Sticker]"

    if type_key == "34":
        sid = str(row.get("server_id", ""))
        if voice_map and sid in voice_map:
            return f"[{ts}] {direction} [Audio] → {voice_map[sid]}"
        dur = ""
        try:
            xml = _decode_msg(hex_str)
            m = re.search(r'length=["\'](\d+)["\']', xml)
            if m:
                ms = int(m.group(1))
                dur = f" {ms // 1000}s" if ms >= 1000 else " <1s"
        except Exception:
            pass
        return f"[{ts}] {direction} [Audio{dur}]"

    if type_key == "49":
        raw_type = int(row.get("local_type", "0") or "0")
        subtype = raw_type >> 32
        try:
            xml = _decode_msg(hex_str)
            title = re.search(r'<title>([^<]+)</title>', xml)
            if subtype == 57:
                text = title.group(1).strip() if title else ""
                ref_name, ref_content = _extract_refer(xml)
                if ref_name:
                    text += f" [↩ {ref_name}: {ref_content[:60]}]"
                return f"[{ts}] {direction} {text}" if text else f"[{ts}] {direction} [Quote]"
            if subtype == 19:
                return f"[{ts}] {direction} [Chat History]"
            label_name = _TYPE49_LABELS.get(subtype, "Link")
            label = f": {title.group(1)[:50]}" if title and title.group(1).strip() else ""
            return f"[{ts}] {direction} [{label_name}{label}]"
        except Exception:
            return f"[{ts}] {direction} [Link]"

    try:
        text = _decode_msg(hex_str)
    except Exception:
        text = ""
    return f"[{ts}] {direction} {text.replace(chr(10), ' ')}"


def transcribe_voices(voice_rows):
    server_ids = [r.get("server_id", "") for r in voice_rows
                  if r.get("server_id") and r.get("server_id") != "0"]
    if not server_ids:
        return {}
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
    try:
        import transcribe_db
        return transcribe_db.transcribe_server_ids(server_ids)
    except Exception as e:
        print(f"语音转写失败（{e}），语音标注为 [Audio]", file=sys.stderr)
        return {}


def main():
    parser = argparse.ArgumentParser(description="导出微信聊天记录")
    parser.add_argument("contact", help="联系人名称/备注/wxid")
    parser.add_argument("--year", type=int, help="导出整年")
    parser.add_argument("--start", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="结束日期 YYYY-MM-DD")
    parser.add_argument("-o", "--output", help="输出路径，默认 ~/Desktop/<contact>_<range>.txt")
    parser.add_argument("--transcribe", action="store_true", help="强制转写语音（即使模型未安装也尝试，触发首次下载）")
    parser.add_argument("--no-transcribe", action="store_true", help="禁用语音转写（即使模型已安装也保留 [Audio]）")
    parser.add_argument("--voice-map", help="复用已有转写 JSON（server_id→文本），跳过重新转写")
    args = parser.parse_args()

    if not _ZSTD_OK:
        print(
            "⚠️  zstd 不可用：压缩消息（引用/链接/部分文本）将全部退化为 [Link]。\n"
            f"    当前解释器: {sys.executable}\n"
            "    安装依赖：\n"
            "      /opt/homebrew/bin/python3 -m pip install --break-system-packages zstd",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.year:
        start_dt = datetime(args.year, 1, 1)
        end_dt = datetime(args.year + 1, 1, 1)
    elif args.start and args.end:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d")
        end_dt = datetime.strptime(args.end, "%Y-%m-%d") + timedelta(days=1)
    else:
        print("请指定 --year 或 --start/--end", file=sys.stderr)
        sys.exit(1)

    name2id = db.get_name2id()
    matched = contacts.find_contact(args.contact, name2id)
    if not matched:
        print(f"未找到匹配 '{args.contact}' 的联系人", file=sys.stderr)
        sys.exit(1)
    if len(matched) > 5:
        print(f"匹配太多 ({len(matched)} 个)，请更精确:", file=sys.stderr)
        for _, wxid, display in matched[:10]:
            print(f"  {display} (wxid: {wxid})", file=sys.stderr)
        sys.exit(1)

    table, wxid, display = matched[0]
    is_group = "@chatroom" in wxid or "@openim" in wxid
    db_paths = db.get_message_dbs()

    my_name = contacts.resolve_nickname(db.get_my_wxid())
    peer_name = contacts.resolve_nickname(wxid) if not is_group else "对方"

    chunks = chunk_by_month(start_dt, end_dt)
    all_rows = []
    for i, (cs, ce) in enumerate(chunks):
        print(f"[{i+1}/{len(chunks)}] {cs.strftime('%Y-%m')} ...", file=sys.stderr)
        batch = fetch(table, db_paths, cs, ce)
        all_rows.extend(batch)
        print(f"  -> {len(batch)} 条", file=sys.stderr)

    seen = set()
    deduped = []
    for r in all_rows:
        key = (r.get("_db"), r.get("local_id"))
        if key[1] and key not in seen:
            seen.add(key)
            deduped.append(r)
    deduped.sort(key=lambda r: int(r.get("create_time", "0") or "0"))

    voice_map = {}
    voice_rows = [r for r in deduped if message.normalize_type(r.get("local_type", "")) == "34"]
    if voice_rows:
        print(f"\n检测到 {len(voice_rows)} 条语音消息", file=sys.stderr)
        if args.voice_map:
            with open(os.path.expanduser(args.voice_map), encoding="utf-8") as f:
                voice_map = json.load(f)
            print(f"复用转写缓存 {len(voice_map)} 条", file=sys.stderr)
        elif args.no_transcribe:
            print("--no-transcribe：跳过转写，语音保留 [Audio]", file=sys.stderr)
        elif args.transcribe or model_cached():
            # 默认：模型已安装即自动转写（--transcribe 强制，--no-transcribe 关闭）
            why = "--transcribe 指定" if args.transcribe else "检测到转写模型，默认开启转写"
            print(f"{why}，从 VoiceInfo 直取并用 whisper 转写...", file=sys.stderr)
            voice_map = transcribe_voices(voice_rows)
        else:
            print(
                "⚠️  未检测到语音转写模型（whisper-large-v3-mlx，约 3GB）。\n"
                "    本次保留 [Audio]。装好后导出会自动转写；\n"
                "    立即安装并转写：重跑并加 --transcribe（首次自动下载模型）。",
                file=sys.stderr,
            )

    if args.output:
        out = os.path.expanduser(args.output)
    else:
        slug = args.contact.replace("/", "_").replace(" ", "_")
        label = str(args.year) if args.year else f"{args.start}_{args.end}"
        out = os.path.expanduser(f"~/Desktop/{slug}_{label}.txt")

    with open(out, "w", encoding="utf-8") as f:
        f.write(f"=== 与 {display} 的对话 ===\n")
        f.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"消息范围: {start_dt.strftime('%Y-%m-%d')} ~ {(end_dt - timedelta(days=1)).strftime('%Y-%m-%d')}\n")
        f.write(f"共 {len(deduped)} 条消息\n\n")
        for row in deduped:
            f.write(format_row(row, voice_map, is_group, my_name, peer_name) + "\n")

    print(f"\n导出完成: {out} ({len(deduped)} 条)", file=sys.stderr)


if __name__ == "__main__":
    main()
