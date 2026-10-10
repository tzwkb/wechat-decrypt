import importlib
import importlib.util
import os
from pathlib import Path


def _script(name):
    path = Path(__file__).parents[1] / 'scripts' / 'windows' / (name + '.py')
    spec = importlib.util.spec_from_file_location('path_test_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_override_is_shared_by_query_extraction_and_decryption(monkeypatch, tmp_path):
    import config, platform
    root = tmp_path / 'Moved 微信 files'
    storage = root / 'synthetic_account' / 'db_storage'
    message = storage / 'message' / 'message_0.db'
    message.parent.mkdir(parents=True)
    message.write_bytes(b'synthetic')
    with monkeypatch.context() as patch:
        patch.setenv('WECHAT_DATA_ROOT', str(root))
        patch.setattr(platform, 'system', lambda: 'Windows')
        importlib.reload(config)
        assert config.WECHAT_DATA_GLOB == os.path.join(str(root), '*', 'db_storage')
        assert _script('extract_raw_key').find_message_dbs() == [str(message)]
        assert _script('decrypt_all').find_storage_roots() == [str(storage)]
    importlib.reload(config)


def test_override_does_not_silently_fall_back_to_another_account(monkeypatch, tmp_path):
    monkeypatch.setenv('WECHAT_DATA_ROOT', str(tmp_path / 'missing'))
    assert _script('extract_raw_key').find_message_dbs() == []
    assert _script('decrypt_all').find_storage_roots() == []


def test_default_query_path_remains_supported(monkeypatch):
    import config, platform
    with monkeypatch.context() as patch:
        patch.delenv('WECHAT_DATA_ROOT', raising=False)
        patch.setattr(platform, 'system', lambda: 'Windows')
        importlib.reload(config)
        assert config.WECHAT_DATA_GLOB == os.path.expanduser('~/Documents/xwechat_files/*/db_storage')
    importlib.reload(config)
