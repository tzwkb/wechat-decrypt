import pytest


def test_windows_attachments_use_matching_original_account(monkeypatch, tmp_path):
    import db, config
    mirror = tmp_path / 'mirror' / 'account-one' / 'db_storage'
    source = tmp_path / 'original' / 'account-one' / 'db_storage'
    other = tmp_path / 'original' / 'account-two' / 'db_storage'
    for path in (mirror, source, other):
        path.mkdir(parents=True)
    monkeypatch.setattr(config, 'DB_BACKEND', 'sqlite3')
    monkeypatch.setattr(config, 'WECHAT_DATA_GLOB', str(tmp_path / 'original' / '*' / 'db_storage'))
    monkeypatch.setattr(db, 'find_data_dir', lambda: str(mirror))
    assert db.get_account_files_dir() == str(source.parent)


def test_missing_source_fails_explicitly(monkeypatch, tmp_path):
    import db, config
    monkeypatch.setattr(config, 'DB_BACKEND', 'sqlite3')
    monkeypatch.setattr(config, 'WECHAT_DATA_GLOB', str(tmp_path / 'missing' / '*' / 'db_storage'))
    monkeypatch.setattr(db, 'find_data_dir', lambda: str(tmp_path / 'mirror' / 'account-one' / 'db_storage'))
    with pytest.raises(FileNotFoundError):
        db.get_account_files_dir()


def test_macos_uses_original_storage_parent(monkeypatch, tmp_path):
    import db, config
    monkeypatch.setattr(config, 'DB_BACKEND', 'sqlcipher')
    monkeypatch.setattr(db, 'find_data_dir', lambda: str(tmp_path / 'account' / 'db_storage'))
    assert db.get_account_files_dir() == str(tmp_path / 'account')


def test_media_entrypoint_uses_original_account(monkeypatch, tmp_path):
    import query, export_media
    source = str(tmp_path / 'original')
    monkeypatch.setattr(query.db, 'get_account_files_dir', lambda: source)
    monkeypatch.setattr(export_media, 'export', lambda base, out: {'source': base})
    assert query.media(str(tmp_path / 'out'))['source'] == source


def test_openfile_entrypoint_reads_original_attachment(monkeypatch, tmp_path):
    import query, read_doc
    source = tmp_path / 'original'
    attachment = source / 'msg' / 'file' / '2026' / 'sample.txt'
    attachment.parent.mkdir(parents=True)
    attachment.write_text('synthetic document', encoding='utf-8')
    monkeypatch.setattr(query.db, 'get_account_files_dir', lambda: str(source))
    monkeypatch.setattr(read_doc, 'read_file', lambda path, limit: 'synthetic document')
    result = query.openfile('sample')
    assert result['path'] == str(attachment)
    assert result['content'] == 'synthetic document'
