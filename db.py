"""Database discovery, query execution, and Name2Id mapping."""
import csv
import glob
import hashlib
import io
import os
import sqlite3
import subprocess

import config
import crypto


def _exec_sqlite3(db_path: str, sql: str) -> list[sqlite3.Row]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def preamble(key: str, db_path: str | None = None) -> str:
    """Build SQLCipher PRAGMA preamble for a database."""
    derived = crypto.derive_key(key, db_path) if db_path else key
    return (
        f"PRAGMA key = \"x'{derived}'\";\n"
        "PRAGMA kdf_iter = 1;\n"
        "PRAGMA cipher_compatibility = 4;\n"
        "PRAGMA cipher_page_size = 4096;\n"
    )


def test_key(key: str, db_path: str) -> bool:
    """Test if a database is readable (sqlcipher: key works / sqlite3: plaintext opens)."""
    if config.DB_BACKEND == "sqlite3":
        try:
            con = sqlite3.connect(db_path)
            con.execute("SELECT count(*) FROM sqlite_master;").fetchone()
            con.close()
            return True
        except Exception:
            return False
    cmd = (
        preamble(key, db_path)
        + "SELECT count(*) FROM sqlite_master;\n"
    )
    try:
        result = subprocess.run(
            [config.SQLCIPHER_PATH, db_path],
            input=cmd.encode(), capture_output=True, timeout=5,
        )
        stdout = result.stdout.decode().strip()
        stderr = result.stderr.decode().strip()
        if "error" in stderr.lower():
            return False
        lines = [l.strip() for l in stdout.split("\n") if l.strip() and l.strip() != "ok"]
        return any(l.isdigit() and int(l) > 0 for l in lines)
    except Exception:
        return False


def query(db_path: str, sql: str) -> list[dict]:
    """Execute SQL query and return list of dicts."""
    if config.DB_BACKEND == "sqlite3":
        return [dict(r) for r in _exec_sqlite3(db_path, sql)]
    key = crypto.load_key()
    cmd = preamble(key, db_path) + ".headers on\n.mode csv\n" + sql
    result = subprocess.run(
        [config.SQLCIPHER_PATH, db_path],
        input=cmd.encode(), capture_output=True, timeout=30,
    )
    text = result.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    lines = text.split("\n")
    while lines and lines[0].strip() == "ok":
        lines.pop(0)
    if len(lines) < 2:
        return []
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def query_raw(db_path: str, sql: str) -> list[str]:
    """Execute SQL and return raw output lines."""
    if config.DB_BACKEND == "sqlite3":
        rows = _exec_sqlite3(db_path, sql)
        return ["|".join("" if c is None else str(c) for c in tuple(r)) for r in rows]
    key = crypto.load_key()
    cmd = preamble(key, db_path) + sql
    result = subprocess.run(
        [config.SQLCIPHER_PATH, db_path],
        input=cmd.encode(), capture_output=True, timeout=30,
    )
    text = result.stdout.decode("utf-8", errors="replace").strip()
    return [l for l in text.split("\n") if l.strip() and l.strip() != "ok"]


def get_my_wxid() -> str:
    """Extract the account wxid from the data directory path."""
    data_dir = find_data_dir()
    # path: .../xwechat_files/<wxid>_<device>/db_storage
    account = os.path.basename(os.path.dirname(data_dir))
    # strip trailing device suffix (e.g. _a254)
    import re as _re
    return _re.sub(r'_[^_]+$', '', account)


_data_dir_cache: str | None = None


def find_data_dir() -> str:
    """Find the WeChat db_storage directory (most recent with valid key). Cached per process."""
    global _data_dir_cache
    if _data_dir_cache:
        return _data_dir_cache
    if config.DB_BACKEND == "sqlite3":
        _data_dir_cache = _find_decrypted_data_dir()
        return _data_dir_cache
    matches = sorted(glob.glob(config.WECHAT_DATA_GLOB), key=os.path.getmtime, reverse=True)
    if not matches:
        raise FileNotFoundError(f"未找到 WeChat 数据目录: {config.WECHAT_DATA_GLOB}")
    key = crypto.load_key()
    for match in matches:
        msg_db = os.path.join(match, "message", "message_0.db")
        if os.path.exists(msg_db) and test_key(key, msg_db):
            _data_dir_cache = match
            return match
    _data_dir_cache = matches[0]
    return _data_dir_cache


def _find_decrypted_data_dir() -> str:
    """Locate the db_storage root inside the decrypted output.

    Assumes layout .../db_storage/message/message_0.db (two levels up from the hit).
    Picks the most-recent message_0.db and assumes a single account under DECRYPTED_DIR.
    """
    hits = glob.glob(
        os.path.join(config.DECRYPTED_DIR, "**", "message", "message_0.db"),
        recursive=True,
    )
    if not hits:
        raise FileNotFoundError(
            f"未找到解密后的 message_0.db，先运行 scripts/windows/extract_raw_key.py 提 key，"
            f"再 scripts/windows/decrypt_all.py 解密。查找根: {config.DECRYPTED_DIR}"
        )
    hits.sort(key=os.path.getmtime, reverse=True)
    return os.path.dirname(os.path.dirname(hits[0]))


_message_dbs_cache: list[str] | None = None


def get_message_dbs() -> list[str]:
    """Get paths to all message database files that our key can access. Cached per process."""
    global _message_dbs_cache
    if _message_dbs_cache is not None:
        return _message_dbs_cache
    data_dir = find_data_dir()
    pattern = os.path.join(data_dir, "message", "message_[0-9].db")
    dbs = sorted(glob.glob(pattern))
    if config.DB_BACKEND == "sqlite3":
        _message_dbs_cache = [db for db in dbs if test_key("", db)]
    else:
        key = crypto.load_key()
        _message_dbs_cache = [db for db in dbs if test_key(key, db)]
    return _message_dbs_cache


def get_name2id() -> dict[str, str]:
    """Build mapping from Msg_ table name to username/wxid.

    Merge Name2Id across ALL message DBs: after a WCDB factory rebuild the newest
    active shard (e.g. message_5) holds sessions absent from message_0/1, so reading
    only the first DB would miss them. Mapping is table->user_name (md5 of wxid),
    rowid-independent, so cross-DB merge is safe.
    """
    mapping = {}
    for dbp in get_message_dbs():
        try:
            rows = query(dbp, "SELECT user_name FROM Name2Id;")
        except Exception:
            continue
        for row in rows:
            un = row.get("user_name", "")
            if un:
                mapping[f"Msg_{hashlib.md5(un.encode()).hexdigest()}"] = un
    return mapping


_contact_db_path: str | None = None


def get_contact_db_path() -> str:
    """Find the contact.db path under the active db_storage directory."""
    global _contact_db_path
    if _contact_db_path and os.path.exists(_contact_db_path):
        return _contact_db_path
    data_dir = find_data_dir()
    path = os.path.join(data_dir, "contact", "contact.db")
    if os.path.exists(path):
        _contact_db_path = path
        return path
    raise FileNotFoundError("未找到 contact.db")


_media_db_path: str | None = None


def get_media_db() -> str:
    """Find media_0.db (voice/media BLOBs) under the active db_storage."""
    global _media_db_path
    if _media_db_path and os.path.exists(_media_db_path):
        return _media_db_path
    path = os.path.join(find_data_dir(), "message", "media_0.db")
    if os.path.exists(path):
        _media_db_path = path
        return path
    raise FileNotFoundError("未找到 media_0.db")


def load_contacts_from_db() -> dict[str, dict]:
    """Load all contacts from contact.db.

    Returns {username: {alias, nick_name, remark, local_type}} dict.
    Fields may be empty strings. Contact.db is authoritative for current nicknames.
    """
    path = get_contact_db_path()
    rows = query(
        path,
        "SELECT username, alias, nick_name, remark, local_type FROM contact;",
    )
    result = {}
    for r in rows:
        un = r.get("username", "")
        if un:
            result[un] = {
                "alias": (r.get("alias") or "").strip(),
                "nick_name": (r.get("nick_name") or "").strip(),
                "remark": (r.get("remark") or "").strip(),
                "local_type": r.get("local_type", "0"),
            }
    return result
