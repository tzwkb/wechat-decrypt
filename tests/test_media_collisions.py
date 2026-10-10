import pytest


@pytest.mark.parametrize('source_dir,category,suffix,header', [
    ('msg/file', 'docs', '', b'document:'),
    ('msg/video', 'videos', '', b'video:'),
    ('cache', 'images', '.png', b'\x89PNG'),
])
def test_media_export_preserves_same_basename_in_different_directories(tmp_path, source_dir, category, suffix, header):
    import export_media

    base = tmp_path / 'account'
    out = tmp_path / 'export'
    expected = []
    for folder, payload in [('a', b'first'), ('b', b'second')]:
        path = base / source_dir / folder / 'same-name'
        path.parent.mkdir(parents=True)
        path.write_bytes(header + payload)
        expected.append(header + payload)

    result = export_media.export(str(base), str(out))
    files = [p for p in (out / category).rglob('*') if p.is_file()]
    assert result[category] == len(files) == 2
    assert sorted(p.read_bytes() for p in files) == sorted(expected)
    assert (out / category / 'a' / ('same-name' + suffix)).is_file()
    assert (out / category / 'b' / ('same-name' + suffix)).is_file()


def test_root_level_files_keep_their_paths_and_encrypted_images_are_skipped(tmp_path):
    import export_media

    base = tmp_path / 'account'
    for folder, name, content in [('msg/file', 'root.pdf', b'synthetic doc'),
                                   ('cache', 'root-cache', b'\xff\xd8\xffsynthetic jpeg'),
                                   ('msg/attach', 'encrypted.dat', b'\x07\x08V2')]:
        path = base / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    out = tmp_path / 'export'
    result = export_media.export(str(base), str(out))
    assert (out / 'docs/root.pdf').read_bytes() == b'synthetic doc'
    assert (out / 'images/root-cache.jpg').is_file()
    assert result['enc_dat'] == 1
    assert not list(out.rglob('*.dat'))
