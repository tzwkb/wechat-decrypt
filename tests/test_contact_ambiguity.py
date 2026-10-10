import os
import sqlite3
import sys

import pytest


@pytest.fixture(autouse=True)
def _clear_contact_cache():
    import contacts

    contacts.invalidate_cache()
    yield
    contacts.invalidate_cache()


@pytest.fixture
def export_cli(monkeypatch):
    import export_chat

    # These fixtures contain no compressed messages. Exercise contact selection
    # independently of the optional zstd decoder's availability on CI hosts.
    monkeypatch.setattr(export_chat.message, 'has_zstd_decoder', lambda: True)
    return export_chat


def _same_named_contacts(root, count):
    import contacts
    import db
    from conftest import SAMPLE_WXID

    storage = os.path.join(root, 'wxid_test001_a2f4', 'db_storage')
    with sqlite3.connect(os.path.join(storage, 'contact', 'contact.db')) as con:
        con.execute("UPDATE contact SET nick_name='Synthetic Alex', remark='' WHERE username=?", (SAMPLE_WXID,))
        con.executemany('INSERT INTO contact VALUES (?, ?, ?, ?, ?)', [
            (f'wxid_peer{index}', '', 'Synthetic Alex', '', 3) for index in range(1, count)
        ])
    with sqlite3.connect(os.path.join(storage, 'message', 'message_0.db')) as con:
        con.executemany('INSERT INTO Name2Id VALUES (?)', [(f'wxid_peer{i}',) for i in range(1, count)])
    db.reset_caches()
    contacts.invalidate_cache()


@pytest.mark.parametrize('count', [2, 5, 6])
def test_read_requires_selection_before_message_reads(win_backend, monkeypatch, count):
    import query

    _same_named_contacts(win_backend, count)
    monkeypatch.setattr(query, '_msg_dbs_tables', lambda: pytest.fail('Ambiguous reads must not fetch messages'))
    result = query.read_chat('Synthetic Alex')
    assert 'error' in result
    assert len(result['candidates']) == count
    assert 'chats' not in result


@pytest.mark.parametrize('count', [2, 5, 6])
def test_export_requires_selection_before_fetch_or_file_write(win_backend, tmp_path, monkeypatch, capsys, count, export_cli):
    export_chat = export_cli

    _same_named_contacts(win_backend, count)
    output = tmp_path / 'existing.txt'
    output.write_text('leave this file unchanged')
    monkeypatch.setattr(sys, 'argv', ['export_chat.py', 'Synthetic Alex', '--no-transcribe', '-o', str(output)])
    monkeypatch.setattr(export_chat, 'fetch', lambda *_: pytest.fail('Ambiguous exports must not fetch messages'))
    with pytest.raises(SystemExit) as exc:
        export_chat.main()
    assert exc.value.code == 1
    assert output.read_text() == 'leave this file unchanged'
    assert 'wxid_peer1' in capsys.readouterr().err


def test_read_exact_identifier_selects_one_of_the_candidates(win_backend):
    import query
    from conftest import SAMPLE_WXID

    _same_named_contacts(win_backend, 2)
    result = query.read_chat(SAMPLE_WXID, days=100000)
    assert len(result['chats']) == 1
    assert result['chats'][0]['wxid'] == SAMPLE_WXID
    assert len(result['chats'][0]['messages']) == 2
    assert query.read_chat('does-not-exist')['candidates'] == []


def test_export_exact_identifier_still_works(win_backend, tmp_path, monkeypatch, export_cli):
    export_chat = export_cli
    import db
    from conftest import SAMPLE_TABLE, SAMPLE_WXID

    _same_named_contacts(win_backend, 2)
    with sqlite3.connect(os.path.join(db.find_data_dir(), 'message', 'message_0.db')) as con:
        # Use modern synthetic timestamps: naive epoch-boundary timestamps are
        # outside the supported range of Windows' local-time conversion.
        con.execute(f'UPDATE {SAMPLE_TABLE} SET create_time=1767225600+local_id')
    output = tmp_path / 'selected.txt'
    monkeypatch.setattr(sys, 'argv', ['export_chat.py', SAMPLE_WXID, '--start', '2025-01-01',
                                     '--no-transcribe', '-o', str(output)])
    export_chat.main()
    assert 'hello' in output.read_text()
