import importlib.util
import sqlite3
import struct
from pathlib import Path
import pytest
import wal_snapshot

PAGE = 4096


def _wal(frames, byteorder='<', salts=b'abcdefgh'):
    magic = 0x377f0682 if byteorder == '<' else 0x377f0683
    header = struct.pack('>IIII', magic, 3007000, PAGE, 0) + salts
    state = wal_snapshot._checksum(header, byteorder)
    result = header + struct.pack('>II', *state)
    for number, size, page in frames:
        prefix = struct.pack('>II', number, size)
        state = wal_snapshot._checksum(prefix + page, byteorder, state)
        result += prefix + salts + struct.pack('>II', *state) + page
    return result


@pytest.mark.parametrize('byteorder', ['<', '>'])
def test_only_committed_frames_are_applied(byteorder):
    main = b'a' * PAGE + b'b' * PAGE
    wal = _wal([(2, 2, b'c' * PAGE), (1, 0, b'd' * PAGE)], byteorder)
    assert wal_snapshot.merge_committed_pages(main, wal) == b'a' * PAGE + b'c' * PAGE


def test_last_committed_update_wins_and_partial_tail_is_ignored():
    main = b'a' * PAGE + b'b' * PAGE
    wal = _wal([(2, 2, b'c' * PAGE), (2, 2, b'd' * PAGE)]) + b'partial frame'
    assert wal_snapshot.merge_committed_pages(main, wal) == b'a' * PAGE + b'd' * PAGE


def test_previous_generation_tail_is_not_applied():
    main = b'a' * PAGE + b'b' * PAGE
    valid = _wal([(2, 2, b'c' * PAGE)])
    stale = _wal([(2, 2, b'd' * PAGE)], salts=b'old-salt')[32:]
    assert wal_snapshot.merge_committed_pages(main, valid + stale) == b'a' * PAGE + b'c' * PAGE


def test_uncommitted_wal_retains_main():
    main = b'a' * PAGE
    assert wal_snapshot.merge_committed_pages(main, _wal([(1, 0, b'b' * PAGE)])) == main


def test_commit_can_grow_and_shrink_database():
    main = b'a' * PAGE + b'b' * PAGE
    assert wal_snapshot.merge_committed_pages(main, _wal([(3, 3, b'c' * PAGE)])) == main + b'c' * PAGE
    assert wal_snapshot.merge_committed_pages(main, _wal([(1, 1, b'd' * PAGE)])) == b'd' * PAGE


@pytest.mark.parametrize('offset', [24, 32 + 16, 32 + 24 + 100])
def test_corrupt_wal_is_rejected(offset):
    wal = bytearray(_wal([(1, 1, b'b' * PAGE)]))
    wal[offset] ^= 1
    with pytest.raises(ValueError, match='checksum'):
        wal_snapshot.merge_committed_pages(b'a' * PAGE, bytes(wal))


def test_impossible_growth_is_rejected():
    with pytest.raises(ValueError, match='missing'):
        wal_snapshot.merge_committed_pages(b'a' * PAGE, _wal([(999999, 999999, b'b' * PAGE)]))


def test_growth_after_truncation_cannot_restore_stale_main_pages():
    main = b'a' * PAGE + b'b' * PAGE + b'c' * PAGE
    wal = _wal([(1, 1, b'd' * PAGE), (3, 3, b'e' * PAGE)])
    with pytest.raises(ValueError, match='missing'):
        wal_snapshot.merge_committed_pages(main, wal)
    valid = _wal([(1, 1, b'd' * PAGE), (2, 0, b'f' * PAGE), (3, 3, b'e' * PAGE)])
    assert wal_snapshot.merge_committed_pages(main, valid) == b'd' * PAGE + b'f' * PAGE + b'e' * PAGE


def test_changing_pair_retries_and_fails_explicitly(monkeypatch, tmp_path):
    source = tmp_path / 'source.db'
    source.write_bytes(b'a' * PAGE)
    counter = iter(range(20))
    monkeypatch.setattr(wal_snapshot, '_metadata', lambda _: next(counter))
    with pytest.raises(ValueError, match='changed'):
        wal_snapshot.read_snapshot(str(source))


def test_real_sqlite_commit_not_present_in_main_is_recovered(tmp_path):
    source = tmp_path / 'source.db'
    con = sqlite3.connect(source)
    try:
        con.execute('PRAGMA page_size=4096')
        con.execute('CREATE TABLE sample(value TEXT)')
        con.commit()
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA wal_autocheckpoint=0')
        before = source.read_bytes()
        con.execute("INSERT INTO sample VALUES ('committed in WAL')")
        con.commit()
        con.execute("INSERT INTO sample VALUES ('not committed')")
        merged = wal_snapshot.read_snapshot(str(source))
        assert source.read_bytes() == before
        main_copy = tmp_path / 'main-only.db'
        main_copy.write_bytes(before)
        output = tmp_path / 'snapshot.db'
        output.write_bytes(merged)
        with sqlite3.connect(main_copy) as old:
            assert old.execute('SELECT COUNT(*) FROM sample').fetchone()[0] == 0
        with sqlite3.connect(output) as snap:
            assert snap.execute('SELECT value FROM sample').fetchall() == [('committed in WAL',)]
            assert snap.execute('PRAGMA quick_check').fetchall() == [('ok',)]
    finally:
        con.rollback()
        con.close()


def test_native_decrypt_consumes_encrypted_committed_wal(tmp_path):
    import hashlib
    from crypto_backend import aes_cbc_encrypt
    path = Path(__file__).parents[1] / 'scripts' / 'windows' / 'decrypt_all.py'
    spec = importlib.util.spec_from_file_location('wal_decrypt', path)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    raw, salt = bytes(range(32)), bytes(range(16))
    key = hashlib.pbkdf2_hmac('sha512', raw, salt, 256000, 32)
    # Build pages with real SQLCipher reserve/header layouts and an opaque page2.
    import hmac
    mac_key = hashlib.pbkdf2_hmac('sha512', key, bytes(v ^ 0x3a for v in salt), 2, 32)
    def encrypted(number, marker):
        offset = 16 if number == 1 else 0
        plaintext = bytearray(4016 - offset)
        if number == 1:
            plaintext[:8] = bytes([0x10, 0, 1, 1, 0x50, 0x40, 0x20, 0x20])
        plaintext[100:100 + len(marker)] = marker
        iv = bytes([number]) * 16
        page = (salt if number == 1 else b'') + aes_cbc_encrypt(key, iv, bytes(plaintext)) + iv
        return page + hmac.new(mac_key, page[offset:] + struct.pack('<I', number), hashlib.sha512).digest()
    source = tmp_path / 'encrypted.db'
    source.write_bytes(encrypted(1, b'header') + encrypted(2, b'old'))
    (tmp_path / 'encrypted.db-wal').write_bytes(_wal([(2, 2, encrypted(2, b'new-committed')),
                                                    (2, 0, encrypted(2, b'not-committed'))]))
    output = tmp_path / 'plain.db'
    assert native.decrypt_db(raw, str(source), str(output))
    assert output.read_bytes()[PAGE + 100:PAGE + 113] == b'new-committed'


def test_bad_wal_keeps_existing_output(tmp_path):
    path = Path(__file__).parents[1] / 'scripts' / 'windows' / 'decrypt_all.py'
    spec = importlib.util.spec_from_file_location('bad_wal_decrypt', path)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    source = tmp_path / 'encrypted.db'
    source.write_bytes(b'x' * PAGE)
    (tmp_path / 'encrypted.db-wal').write_bytes(b'invalid')
    output = tmp_path / 'existing.db'
    output.write_bytes(b'keep previous snapshot')
    assert native.decrypt_db(bytes(32), str(source), str(output)) is False
    assert output.read_bytes() == b'keep previous snapshot'
