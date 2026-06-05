"""WeChat voice transcription.

VoiceInfo SILK BLOB -> wav (pilk) -> mlx-whisper -> {server_id: text}.
Aligned to messages by server_id == VoiceInfo.svr_id (exact, no playback ordering).
"""
import argparse
import json
import os
import sys
import tempfile

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, SCRIPT_DIR)

import db
import contacts
import voice_decode

import platform
IS_MACOS = platform.system() == "Darwin"
DEFAULT_MODEL = "mlx-community/whisper-large-v3-mlx" if IS_MACOS else "large-v3"
_fw_model = None


def _transcribe_wav(wav: str, lang: str = "zh", model: str = DEFAULT_MODEL) -> str:
    """Transcribe one wav with the platform's whisper backend."""
    if IS_MACOS:
        import mlx_whisper
        r = mlx_whisper.transcribe(wav, path_or_hf_repo=model, language=lang)
        return (r.get("text") or "").strip()
    from faster_whisper import WhisperModel
    global _fw_model
    if _fw_model is None:
        _fw_model = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _ = _fw_model.transcribe(wav, language=lang)
    return "".join(s.text.strip() for s in segments)


def _fetch_blobs(server_ids: list[str]) -> dict[str, bytes]:
    sids = [str(s) for s in server_ids if s and str(s) != "0"]
    if not sids:
        return {}
    media = db.get_media_db()
    out: dict[str, bytes] = {}
    for i in range(0, len(sids), 400):
        inlist = ",".join(sids[i:i + 400])
        rows = db.query(media, f"SELECT svr_id, hex(voice_data) h FROM VoiceInfo WHERE svr_id IN ({inlist});")
        for r in rows:
            if r.get("h"):
                out[str(r.get("svr_id", ""))] = bytes.fromhex(r["h"])
    return out


def transcribe_server_ids(server_ids: list[str], model: str = DEFAULT_MODEL) -> dict[str, str]:
    blobs = _fetch_blobs(server_ids)
    if not blobs:
        return {}
    result: dict[str, str] = {}
    total = len(blobs)
    print(f"转写 {total} 条语音（模型 {model}）...", file=sys.stderr)
    with tempfile.TemporaryDirectory() as td:
        for i, (sid, blob) in enumerate(blobs.items(), 1):
            wav = os.path.join(td, f"{sid}.wav")
            try:
                voice_decode.decode_voice_blob(blob, wav)
                text = _transcribe_wav(wav, lang="zh", model=model)
                if text:
                    result[sid] = text
                print(f"  [{i}/{total}] {text[:40]}", file=sys.stderr)
            except Exception as e:
                print(f"  [{i}/{total}] svr_id={sid} 失败: {e}", file=sys.stderr)
    return result


def transcribe_contact(contact: str, model: str = DEFAULT_MODEL, limit: int | None = None) -> dict[str, str]:
    name2id = db.get_name2id()
    matched = contacts.find_contact(contact, name2id)
    if not matched:
        raise SystemExit(f"未找到联系人: {contact}")
    table = matched[0][0]
    sids: list[str] = []
    for dbp in db.get_message_dbs():
        tbls = {t.strip() for t in db.query_raw(dbp, "SELECT name FROM sqlite_master WHERE type='table';")}
        if table not in tbls:
            continue
        rows = db.query(dbp, f"SELECT server_id FROM {table} WHERE local_type=34 AND server_id!=0;")
        sids += [str(r.get("server_id")) for r in rows if r.get("server_id")]
    if limit:
        sids = sids[:limit]
    return transcribe_server_ids(sids, model=model)


def main():
    ap = argparse.ArgumentParser(description="转写微信语音消息（VoiceInfo + mlx-whisper）")
    ap.add_argument("contact", help="联系人名称/备注/wxid")
    ap.add_argument("-o", "--output", help="输出 JSON 路径，默认打印到 stdout")
    ap.add_argument("--limit", type=int, help="只转写前 N 条")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="mlx-whisper 模型 repo")
    a = ap.parse_args()
    m = transcribe_contact(a.contact, model=a.model, limit=a.limit)
    payload = json.dumps(m, ensure_ascii=False, indent=2)
    if a.output:
        out_path = os.path.expanduser(a.output)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"完成: {len(m)} 条 -> {out_path}", file=sys.stderr)
    else:
        print(payload)


if __name__ == "__main__":
    main()
