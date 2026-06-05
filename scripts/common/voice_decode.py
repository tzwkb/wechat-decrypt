"""SILK v3 voice decode.

WeChat VoiceInfo.voice_data is standard #!SILK_V3 prefixed with one 0x02 byte.
"""
import os
import tempfile

import pilk

_MAGIC = b"#!SILK_V3"


def decode_voice_blob(blob: bytes, out_wav: str) -> None:
    """Decode a WeChat voice BLOB to 24kHz mono WAV."""
    if not blob:
        raise ValueError("empty voice blob")
    data = blob[1:] if blob[:1] == b"\x02" else blob
    if not data.startswith(_MAGIC):
        raise ValueError(f"not SILK v3: {data[:10]!r}")
    with tempfile.NamedTemporaryFile(suffix=".silk", delete=False) as tf:
        tf.write(data)
        silk = tf.name
    try:
        pilk.silk_to_wav(silk, out_wav)
    finally:
        os.unlink(silk)
