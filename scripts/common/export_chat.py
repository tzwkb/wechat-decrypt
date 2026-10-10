#!/usr/bin/env python3
"""导出微信聊天记录。

Usage:
    python3 export_chat.py <contact>                              # 全部历史
    python3 export_chat.py <contact> --year 2026 [-o ~/Desktop/out.txt]
    python3 export_chat.py <contact> --start 2026-01-01 --end 2026-06-03
"""

import sys
import os
import argparse
import json
import re
import platform
from datetime import datetime, timedelta

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SKILL_DIR)

import db
import appmsg
import contacts
import message

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _hf_hub_cache() -> str:
    if os.environ.get("HF_HUB_CACHE"):
        return os.path.expanduser(os.environ["HF_HUB_CACHE"])
    if os.environ.get("HF_HOME"):
        return os.path.join(os.path.expanduser(os.environ["HF_HOME"]), "hub")
    return os.path.expanduser("~/.cache/huggingface/hub")


def model_cached(system: str | None = None) -> bool:
    """Return whether the platform's large-v3 model is already local."""
    system = system or platform.system()
    folder = (
        "models--mlx-community--whisper-large-v3-mlx"
        if system == "Darwin"
        else "models--Systran--faster-whisper-large-v3"
    )
    return os.path.isdir(os.path.join(_hf_hub_cache(), folder))


def _open_private_text(path: str):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return os.fdopen(fd, "w", encoding="utf-8")


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
    n = len(db_paths)
    for i, db_path in enumerate(db_paths, 1):
        tag = os.path.basename(db_path)
        tables = db.query_raw(db_path, "SELECT name FROM sqlite_master WHERE type='table';")
        if table not in {t.strip() for t in tables}:
            print(f"[{i}/{n}] {tag}: 无此会话", file=sys.stderr)
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
        print(f"[{i}/{n}] {tag}: {len(batch)} 条", file=sys.stderr)
    return rows


def _decode_msg(hex_str: str) -> str:
    return message.decode_message_hex(hex_str)


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
        try:
            content = _decode_msg(hex_str)
        except Exception:
            content = ""
        system = message.parse_system_message(
            content,
            default_event="recall" if type_key == "10002" else "",
        )
        suffix = f" {system['text']}" if system["text"] else ""
        return f"[{ts}] [系统·{system['label']}]{suffix}"
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
        try:
            xml = _decode_msg(hex_str)
            parsed = appmsg.parse_app_message(xml, row.get("local_type", ""))
            details = parsed["summary"].replace("\n", " ")
            suffix = f" {details}" if details else ""
            return f"[{ts}] {direction} [{parsed['label']}]{suffix}"
        except Exception:
            return f"[{ts}] {direction} [分享卡片]"

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
    parser.add_argument("--start", help="开始日期 YYYY-MM-DD（默认不限）")
    parser.add_argument("--end", help="结束日期 YYYY-MM-DD，含当天（默认今天）")
    parser.add_argument("-o", "--output", help="输出路径，默认 ~/Desktop/<contact>_<range>.txt")
    parser.add_argument("--transcribe", action="store_true", help="强制转写语音（即使模型未安装也尝试，触发首次下载）")
    parser.add_argument("--no-transcribe", action="store_true", help="禁用语音转写（即使模型已安装也保留 [Audio]）")
    parser.add_argument("--voice-map", help="复用已有转写 JSON（server_id→文本），跳过重新转写")
    args = parser.parse_args()

    if not message.has_zstd_decoder():
        print(
            "⚠️  zstd 不可用：压缩消息（引用/链接/部分文本）将全部退化为 [Link]。\n"
            f"    当前解释器: {sys.executable}\n"
            "    安装依赖：\n"
            f"      {sys.executable} -m pip install zstandard",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.year:
        start_dt = datetime(args.year, 1, 1)
        end_dt = datetime(args.year + 1, 1, 1)
    else:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d") if args.start \
                   else datetime(2010, 1, 1)
        end_dt = (datetime.strptime(args.end, "%Y-%m-%d") if args.end
                  else datetime.now()) + timedelta(days=1)

    name2id = db.get_name2id()
    matched = contacts.find_contact(args.contact, name2id)
    if not matched:
        print(f"未找到匹配 '{args.contact}' 的联系人", file=sys.stderr)
        sys.exit(1)
    if len(matched) > 1:
        print(f"匹配不唯一 ({len(matched)} 个)，请使用具体 wxid 选择:", file=sys.stderr)
        for _, wxid, display in matched[:10]:
            print(f"  {display} (wxid: {wxid})", file=sys.stderr)
        sys.exit(1)

    table, wxid, display = matched[0]
    is_group = "@chatroom" in wxid or "@openim" in wxid
    db_paths = db.get_message_dbs()

    my_name = contacts.resolve_nickname(db.get_my_wxid())
    peer_name = contacts.resolve_nickname(wxid) if not is_group else "对方"

    all_rows = fetch(table, db_paths, start_dt, end_dt)

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
        if args.year:
            label = str(args.year)
        elif args.start or args.end:
            label = f"{args.start or 'begin'}_{args.end or 'now'}"
        else:
            label = "all"
        out = os.path.expanduser(f"~/Desktop/{slug}_{label}.txt")

    with _open_private_text(out) as f:
        f.write(f"=== 与 {display} 的对话 ===\n")
        f.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"消息范围: {start_dt.strftime('%Y-%m-%d')} ~ {(end_dt - timedelta(days=1)).strftime('%Y-%m-%d')}\n")
        f.write(f"共 {len(deduped)} 条消息\n\n")
        for row in deduped:
            f.write(format_row(row, voice_map, is_group, my_name, peer_name) + "\n")

    print(f"\n导出完成: {out} ({len(deduped)} 条)", file=sys.stderr)


if __name__ == "__main__":
    main()
