import hashlib
import os
import sqlite3
import pytest

SAMPLE_WXID = "wxid_friend001"
SAMPLE_TABLE = "Msg_" + hashlib.md5(SAMPLE_WXID.encode()).hexdigest()


@pytest.fixture
def decrypted_dir(tmp_path):
    """造一个 wechat-dump-rs 风格的明文解密目录：<root>/<wxid>/db_storage/..."""
    root = tmp_path / "decrypted"
    storage = root / "wxid_test001_a2f4" / "db_storage"
    msg_dir = storage / "message"
    contact_dir = storage / "contact"
    msg_dir.mkdir(parents=True)
    contact_dir.mkdir(parents=True)

    m = sqlite3.connect(msg_dir / "message_0.db")
    m.execute("CREATE TABLE Name2Id (user_name TEXT);")
    m.execute("INSERT INTO Name2Id (user_name) VALUES (?);", (SAMPLE_WXID,))
    m.execute(
        f"CREATE TABLE {SAMPLE_TABLE} "
        "(local_id INTEGER, server_id INTEGER, local_type INTEGER, message_content TEXT);"
    )
    m.execute(
        f"INSERT INTO {SAMPLE_TABLE} (local_id, server_id, local_type, message_content) "
        "VALUES (1, 1001, 1, 'hello'), (2, 1002, 34, '');"
    )
    m.commit(); m.close()

    md = sqlite3.connect(msg_dir / "media_0.db")
    md.execute("CREATE TABLE VoiceInfo (svr_id INTEGER, voice_data BLOB);")
    md.execute("INSERT INTO VoiceInfo (svr_id, voice_data) VALUES (1002, X'0223214653494C4B5F5633');")
    md.commit(); md.close()

    c = sqlite3.connect(contact_dir / "contact.db")
    c.execute(
        "CREATE TABLE contact "
        "(username TEXT, alias TEXT, nick_name TEXT, remark TEXT, local_type INTEGER);"
    )
    c.execute(
        "INSERT INTO contact (username, alias, nick_name, remark, local_type) "
        "VALUES (?, 'alias1', '好友昵称', '备注名', 3);", (SAMPLE_WXID,)
    )
    c.commit(); c.close()

    return str(root)


@pytest.fixture
def win_backend(monkeypatch, decrypted_dir):
    """把进程伪装成 Windows sqlite3 后端，并指向测试解密目录。"""
    import config
    monkeypatch.setattr(config, "DB_BACKEND", "sqlite3", raising=False)
    monkeypatch.setattr(config, "DECRYPTED_DIR", decrypted_dir, raising=False)
    import db
    db._contact_db_path = None
    db._media_db_path = None
    return decrypted_dir
