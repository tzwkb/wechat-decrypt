"""Local synthetic encrypted-page validation, without personal data."""
import hashlib, hmac, importlib.util, struct
from pathlib import Path
import pytest

SPEC=importlib.util.spec_from_file_location('native_decrypt',Path(__file__).parents[1]/'scripts'/'windows'/'decrypt_all.py')
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

def encrypted_pages():
    from Crypto.Cipher import AES
    raw=bytes(range(32))
    salt=bytes(range(16))
    key=hashlib.pbkdf2_hmac('sha512',raw,salt,256000,32)
    mac_key=hashlib.pbkdf2_hmac('sha512',key,bytes(x^0x3a for x in salt),2,32)
    pages=[]
    for number in (1,2):
        offset=16 if number==1 else 0
        payload=bytearray(4016-offset)
        if number==1:
            payload[:8]=bytes([0x10,0x00,1,1,0x50,0x40,0x20,0x20])
        iv=bytes([number])*16
        page=(salt if number==1 else b'')+AES.new(key,AES.MODE_CBC,iv).encrypt(bytes(payload))+iv
        page+=hmac.new(mac_key,page[offset:]+struct.pack('<I',number),hashlib.sha512).digest()
        pages.append(page)
    return raw,b''.join(pages)

def test_native_correct_key(tmp_path):
    raw,pages=encrypted_pages()
    source=tmp_path/'encrypted.db';source.write_bytes(pages)
    destination=tmp_path/'plain.db'
    assert MODULE.decrypt_db(raw,str(source),str(destination)) is True
    assert destination.read_bytes()[:16]==b'SQLite format 3\x00'

def test_native_wrong_key_does_not_write(tmp_path):
    _,pages=encrypted_pages()
    source=tmp_path/'encrypted.db';source.write_bytes(pages)
    destination=tmp_path/'plain.db'
    assert MODULE.decrypt_db(bytes([255])*32,str(source),str(destination)) is False
    assert not destination.exists()

def test_native_truncation_does_not_write(tmp_path):
    raw,pages=encrypted_pages()
    source=tmp_path/'encrypted.db';source.write_bytes(pages[:-1])
    destination=tmp_path/'plain.db'
    assert MODULE.decrypt_db(raw,str(source),str(destination)) is False
    assert not destination.exists()

@pytest.mark.parametrize('offset', [4096 + 128, 4096 + 4016, 4096 + 4032, 4032])
def test_native_page_corruption_rejected(tmp_path, offset):
    raw,pages=encrypted_pages()
    corrupt=bytearray(pages);corrupt[offset]^=1
    source=tmp_path/'encrypted.db';source.write_bytes(corrupt)
    destination=tmp_path/'plain.db'
    assert MODULE.decrypt_db(raw,str(source),str(destination)) is False
    assert not destination.exists()


def test_native_page_number_is_authenticated(tmp_path):
    raw, pages = encrypted_pages()
    source = tmp_path / 'encrypted.db'
    source.write_bytes(pages + pages[4096:])
    destination = tmp_path / 'plain.db'
    assert MODULE.decrypt_db(raw, str(source), str(destination)) is False
    assert not destination.exists()


def test_corruption_preserves_existing_output(tmp_path):
    raw, pages = encrypted_pages()
    corrupt = bytearray(pages)
    corrupt[4096 + 128] ^= 1
    source = tmp_path / 'encrypted.db'
    source.write_bytes(corrupt)
    destination = tmp_path / 'plain.db'
    destination.write_bytes(b'previous verified snapshot')
    assert MODULE.decrypt_db(raw, str(source), str(destination)) is False
    assert destination.read_bytes() == b'previous verified snapshot'
