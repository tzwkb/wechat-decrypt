import sqlite3
import pytest


def test_sqlite_fallback_executes_one_ordered_scan(monkeypatch, win_backend):
    import config, db, query
    path = win_backend + '/scan.db'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE sample(create_time INTEGER, source_table TEXT, local_id INTEGER, server_id INTEGER)')
        con.executemany('INSERT INTO sample VALUES (?, ?, ?, ?)',
                        [(i // 2, 'Msg_a' if i % 2 else 'Msg_b', i, i) for i in range(1501)])
    calls = []
    original = db.iter_query
    def stream(*args, **kwargs):
        calls.append(args[1])
        yield from original(*args, **kwargs)
    monkeypatch.setattr(db, 'iter_query', stream)
    monkeypatch.setattr(db, 'query', lambda *args: pytest.fail('must not repeat OFFSET scans'))
    rows = list(query._iter_query_pages(path, ['SELECT * FROM sample'], page_size=31))
    assert len(rows) == 1501
    assert len(calls) == 1 and 'OFFSET' not in calls[0]
    assert rows == sorted(rows, key=lambda r: (-r['create_time'], r['source_table'], -r['local_id'], -r['server_id']))


def test_stream_is_read_only(win_backend):
    import db
    path = win_backend + '/readonly.db'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE sample(value INTEGER)')
    with pytest.raises(sqlite3.OperationalError, match='readonly'):
        list(db.iter_query(path, 'INSERT INTO sample VALUES (1)'))
    with sqlite3.connect(path) as con:
        assert con.execute('SELECT COUNT(*) FROM sample').fetchone()[0] == 0


def test_early_close_releases_connection(monkeypatch, win_backend):
    import db
    path = win_backend + '/close.db'
    real_connect = sqlite3.connect
    handles = []
    with real_connect(path) as con:
        con.execute('CREATE TABLE sample(value INTEGER)')
        con.executemany('INSERT INTO sample VALUES (?)', [(1,), (2,)])
    def connect(*args, **kwargs):
        handle = real_connect(*args, **kwargs)
        handles.append(handle)
        return handle
    monkeypatch.setattr(db.sqlite3, 'connect', connect)
    rows = db.iter_query(path, 'SELECT * FROM sample', batch_size=1)
    assert next(rows)['value'] == 1
    rows.close()
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        handles[0].execute('SELECT 1')
