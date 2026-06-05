"""Message formatting, type mapping, and sender detection."""
from datetime import datetime

import db

MSG_TYPES = {
    "1": "文本", "3": "图片", "34": "语音", "42": "名片",
    "43": "视频", "47": "表情", "48": "位置", "49": "链接/文件",
    "50": "通话", "10000": "系统消息", "10002": "撤回",
}

_my_sender_id_cache: int | None = None
_my_sender_id_detected: bool = False


def detect_my_sender_id(db_path: str) -> int | None:
    """Detect the real_sender_id that represents 'me' (the account owner).

    The 'me' sender_id appears in the majority of chat tables — it's the sender
    that shows up most consistently across tables, not necessarily all tables
    (some chats may be receive-only).
    """
    tables_raw = db.query_raw(
        db_path, "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%';"
    )
    msg_tables = [t.strip() for t in tables_raw if t.strip().startswith("Msg_")]

    if not msg_tables:
        return None

    # Count how many tables each sender_id appears in
    from collections import Counter
    sender_table_count = Counter()
    for table in msg_tables:
        rows = db.query(
            db_path,
            f"SELECT DISTINCT real_sender_id FROM {table} "
            f"WHERE local_type NOT IN (10000, 10002) LIMIT 20;",
        )
        ids = {int(r.get("real_sender_id", 0)) for r in rows if r.get("real_sender_id")}
        ids.discard(0)
        for sid in ids:
            sender_table_count[sid] += 1

    if not sender_table_count:
        return None

    # The 'me' sender is the one appearing in the most tables
    top = sender_table_count.most_common(1)
    if not top:
        return None

    winner_id, winner_count = top[0]
    threshold = max(len(msg_tables) * 0.4, 2)
    if winner_count >= threshold:
        return winner_id

    return None


def get_my_sender_id() -> int | None:
    """Get the cached 'my' sender_id, detecting on first call."""
    global _my_sender_id_cache, _my_sender_id_detected
    if _my_sender_id_detected:
        return _my_sender_id_cache
    dbs = db.get_message_dbs()
    if dbs:
        _my_sender_id_cache = detect_my_sender_id(dbs[0])
    _my_sender_id_detected = True
    return _my_sender_id_cache


def is_my_message(real_sender_id: str | int) -> bool:
    """Check if a message was sent by 'me' based on real_sender_id."""
    my_id = get_my_sender_id()
    if my_id is None:
        return False
    try:
        return int(real_sender_id) == my_id
    except (ValueError, TypeError):
        return False


def format_time(ts: str | int) -> str:
    """Format unix timestamp to readable string."""
    try:
        t = int(ts)
        if t > 0:
            return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OSError):
        pass
    return "未知时间"


def normalize_type(raw_type: str) -> str:
    """Normalize local_type for MSG_TYPES lookup.

    WeChat Mac uses high bits for subtypes; extract low 16 bits.
    """
    try:
        return str(int(raw_type) & 0xFFFF) if raw_type else ""
    except (ValueError, TypeError):
        return raw_type
