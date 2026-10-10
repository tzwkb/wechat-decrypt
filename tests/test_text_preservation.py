import pytest


@pytest.mark.parametrize('text', [
    '中文段落' * 200 + '\nlast line',
    'x' * 499 + '\n' + 'end',
    'first\n\nsecond\t😀',
])
def test_query_preserves_full_plain_text(text):
    import query
    row = {'create_time': 1767225600, 'local_type': 1, 'real_sender_id': 2,
           'message_hex': text.encode('utf-8').hex()}
    formatted = query._fmt_msg(row)
    assert formatted['is_text']
    assert formatted['content'] == text
