import hashlib
import sqlite3
import time
from pathlib import Path

import pytest


def _sender_fixture(root):
    from conftest import SAMPLE_TABLE, SAMPLE_WXID

    owner = 'wxid_test001'
    storage = Path(root) / 'wxid_test001_a2f4/db_storage/message'
    now = int(time.time())
    with sqlite3.connect(storage / 'message_0.db') as con:
        con.execute('DELETE FROM Name2Id')
        con.executemany('INSERT INTO Name2Id(rowid,user_name) VALUES (?,?)', [(1,owner),(2,SAMPLE_WXID)])
        con.execute(f'DELETE FROM {SAMPLE_TABLE}')
        con.executemany(f'INSERT INTO {SAMPLE_TABLE} VALUES (?,?,?,1,?,?)', [
            (1,1001,now-40,1,'direction-self-0'),(2,1002,now-30,2,'direction-peer-0')])
        helper = 'Msg_' + hashlib.md5(b'wxid_helper').hexdigest()
        con.execute(f'CREATE TABLE {helper} AS SELECT * FROM {SAMPLE_TABLE} WHERE local_id=1')
        con.execute(f"UPDATE {helper} SET message_content='seed-owner'")
    with sqlite3.connect(storage / 'message_1.db') as con:
        con.execute('CREATE TABLE Name2Id(user_name TEXT)')
        con.executemany('INSERT INTO Name2Id(rowid,user_name) VALUES (?,?)', [(1,SAMPLE_WXID),(2,owner)])
        con.execute(f'CREATE TABLE {SAMPLE_TABLE}(local_id INTEGER,server_id INTEGER,create_time INTEGER,'
                    'local_type INTEGER,real_sender_id INTEGER,message_content TEXT)')
        con.executemany(f'INSERT INTO {SAMPLE_TABLE} VALUES (?,?,?,1,?,?)', [
            (1,2001,now-20,2,'direction-self-1'),(2,2002,now-10,1,'direction-peer-1')])


@pytest.mark.parametrize('operation', ['read', 'search', 'search-compressed', 'recent', 'summary'])
def test_sender_identity_is_resolved_in_each_shard(win_backend, monkeypatch, operation):
    import db
    import message
    import query
    from conftest import SAMPLE_TABLE, SAMPLE_WXID

    _sender_fixture(win_backend)
    db.reset_caches()
    monkeypatch.setattr(message, '_my_sender_id_cache', None)
    monkeypatch.setattr(message, '_my_sender_id_detected', False)
    if operation == 'search-compressed':
        storage = Path(win_backend) / 'wxid_test001_a2f4/db_storage/message'
        with sqlite3.connect(storage / 'message_1.db') as con:
            con.execute(f'UPDATE {SAMPLE_TABLE} SET message_content=? WHERE local_id=1',
                        (b'\x28\xb5\x2f\xfd' + b'\x00' * 8,))
        monkeypatch.setattr(message, '_decompress_zstd', lambda _blob: b'direction-self-1')
    if operation == 'read':
        result = query.read_chat(SAMPLE_WXID, limit=20, days=1)
        rows = result['chats'][0]['messages']
    elif operation.startswith('search'):
        rows = query.search('direction', days=1, limit=20)['messages']
    else:
        result = query.recent(days=1, limit=20) if operation == 'recent' else query.summary(days=1)
        rows = [row for chat in result['conversations'] for row in chat['messages']]
    actual = {row['content']: row['direction'] for row in rows if row['content'].startswith('direction-')}
    assert actual == {'direction-self-0':'[我]','direction-peer-0':'[对方]',
                      'direction-self-1':'[我]','direction-peer-1':'[对方]'}


@pytest.mark.parametrize('local_type', [1, 49])
def test_unresolved_sender_does_not_guess_a_direction(local_type, monkeypatch):
    import message
    import query

    def no_heuristic(_sender):
        pytest.fail('Formatting must not consult a cross-shard sender-ID heuristic')

    monkeypatch.setattr(message, 'is_my_message', no_heuristic)
    row = {'create_time': 1, 'local_type': local_type, 'real_sender_id': 1,
           'message_content': 'unknown sender'}
    assert query._fmt_msg(row)['direction'] == '[未知]'
    row['sender_wxid'] = None
    assert query._fmt_msg(row)['direction'] == '[未知]'
