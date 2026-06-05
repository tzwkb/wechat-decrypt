import sys
import types


def test_macos_uses_mlx(monkeypatch):
    import transcribe_db
    monkeypatch.setattr(transcribe_db, "IS_MACOS", True)
    called = {}
    fake = types.ModuleType("mlx_whisper")
    fake.transcribe = lambda wav, path_or_hf_repo, language: called.update({"mlx": True}) or {"text": "你好"}
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)
    assert transcribe_db._transcribe_wav("/tmp/x.wav") == "你好"
    assert called.get("mlx") is True


def test_windows_uses_faster_whisper(monkeypatch):
    import transcribe_db
    monkeypatch.setattr(transcribe_db, "IS_MACOS", False)
    monkeypatch.setattr(transcribe_db, "_fw_model", None, raising=False)

    class _Seg:
        def __init__(self, t): self.text = t

    class _Model:
        def __init__(self, *a, **k): pass
        def transcribe(self, wav, language): return ([_Seg("你"), _Seg("好")], None)

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = _Model
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    assert transcribe_db._transcribe_wav("/tmp/x.wav") == "你好"


def test_fetch_blobs_handles_int_ids(win_backend):
    import transcribe_db
    out = transcribe_db._fetch_blobs([1002])   # native int, like real Windows query output
    assert "1002" in out                        # str-keyed, blob fetched without TypeError
