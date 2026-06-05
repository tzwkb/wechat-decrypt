#!/usr/bin/env python3
"""Export WeChat attachments (documents, videos, cache images) to a folder. Plaintext, no key needed.

Mirrors wecom 'media'. Document/video/cache files are stored plaintext under the account data dir.
msg/attach/*.dat are V2-encrypted original images (header 07 08 56 32 = "..V2") and need a separate
decoder; they are counted but skipped here. Usage: python export_media.py <wxid_data_dir> <out_dir>
"""
import os
import shutil
import sys


def export(base, out):
    os.makedirs(out, exist_ok=True)
    c = {"docs": 0, "videos": 0, "images": 0, "enc_dat": 0}
    for sub, key, dstsub in [("msg/file", "docs", "docs"), ("msg/video", "videos", "videos")]:
        src = os.path.join(base, sub)
        if not os.path.isdir(src):
            continue
        d = os.path.join(out, dstsub)
        os.makedirs(d, exist_ok=True)
        for root, _, files in os.walk(src):
            for f in files:
                try:
                    shutil.copy2(os.path.join(root, f), os.path.join(d, f))
                    c[key] += 1
                except OSError:
                    pass
    cache = os.path.join(base, "cache")
    if os.path.isdir(cache):
        d = os.path.join(out, "images")
        os.makedirs(d, exist_ok=True)
        for root, _, files in os.walk(cache):
            for f in files:
                p = os.path.join(root, f)
                try:
                    with open(p, "rb") as fh:
                        hdr = fh.read(4)
                except OSError:
                    continue
                if hdr[:3] == b"\xff\xd8\xff":
                    ext = ".jpg"
                elif hdr[:4] == b"\x89PNG":
                    ext = ".png"
                else:
                    continue
                try:
                    shutil.copy2(p, os.path.join(d, f + ext))
                    c["images"] += 1
                except OSError:
                    pass
    attach = os.path.join(base, "msg", "attach")
    if os.path.isdir(attach):
        for _, _, files in os.walk(attach):
            c["enc_dat"] += sum(1 for f in files if f.endswith(".dat"))
    return c


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: export_media.py <wxid_data_dir> <out_dir>")
    c = export(sys.argv[1], sys.argv[2])
    print(f"exported -> {sys.argv[2]}: {c['docs']} docs, {c['videos']} videos, {c['images']} cache images")
    print(f"skipped {c['enc_dat']} msg/attach/.dat (V2-encrypted originals -- need separate decoder)")
