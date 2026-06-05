import os


def test_query_reads_plaintext(win_backend):
    import db
    data_dir = db.find_data_dir()
    msg_db = os.path.join(data_dir, "message", "message_0.db")
    rows = db.query(msg_db, "SELECT user_name FROM Name2Id;")
    assert rows == [{"user_name": "wxid_friend001"}]


def test_query_raw_single_column(win_backend):
    import db
    data_dir = db.find_data_dir()
    msg_db = os.path.join(data_dir, "message", "message_0.db")
    names = db.query_raw(msg_db, "SELECT name FROM sqlite_master WHERE type='table';")
    assert "Name2Id" in names


def test_get_name2id_maps_table_to_wxid(win_backend):
    import db
    from conftest import SAMPLE_TABLE
    mapping = db.get_name2id()
    assert mapping.get(SAMPLE_TABLE) == "wxid_friend001"


def test_query_raw_multi_column_and_null(win_backend):
    import db
    from conftest import SAMPLE_TABLE
    data_dir = db.find_data_dir()
    msg_db = os.path.join(data_dir, "message", "message_0.db")
    rows = db.query_raw(
        msg_db,
        f"SELECT local_id, NULL, message_content FROM {SAMPLE_TABLE} WHERE local_id=1;",
    )
    assert rows == ["1||hello"]


def test_get_message_dbs_no_key_on_windows(win_backend, monkeypatch):
    import crypto, db
    def _boom():
        raise FileNotFoundError("key.txt missing")
    monkeypatch.setattr(crypto, "load_key", _boom)
    dbs = db.get_message_dbs()
    assert len(dbs) == 1 and dbs[0].endswith("message_0.db")


def test_get_my_wxid_strips_device_suffix(win_backend):
    import db
    assert db.get_my_wxid() == "wxid_test001"


def test_find_data_dir_missing_raises(monkeypatch, tmp_path):
    import pytest
    import config
    import db
    monkeypatch.setattr(config, "DB_BACKEND", "sqlite3", raising=False)
    monkeypatch.setattr(config, "DECRYPTED_DIR", str(tmp_path / "empty"), raising=False)
    with pytest.raises(FileNotFoundError):
        db.find_data_dir()
