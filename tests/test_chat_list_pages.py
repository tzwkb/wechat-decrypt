import pytest


@pytest.fixture
def chats(monkeypatch):
    import query
    values = [{'wxid': f'synthetic_{i:04d}', 'display': f'Contact {i}'} for i in range(205)]
    monkeypatch.setattr(query, 'list_chats', lambda: values)
    return values


def test_pages_cover_all_chats_without_duplicates(chats):
    import query
    results = [query.list_chat_page(100, i) for i in (0, 100, 200)]
    assert [r['next_offset'] for r in results] == [100, 200, None]
    assert [r['count'] for r in results] == [100, 100, 5]
    assert all(r['total'] == 205 for r in results)
    assert [c for r in results for c in r['chats']] == chats


def test_offset_past_end_returns_empty_page(chats):
    import query
    result = query.list_chat_page(100, 999)
    assert result['chats'] == [] and result['next_offset'] is None


@pytest.mark.parametrize('kwargs', [{'limit': 0}, {'limit': -1}, {'limit': 2001}, {'limit': True}, {'offset': -1}, {'offset': True}])
def test_invalid_page_fails_before_discovery(monkeypatch, kwargs):
    import query
    monkeypatch.setattr(query, 'list_chats', lambda: pytest.fail('invalid page must fail before reading'))
    with pytest.raises(ValueError):
        query.list_chat_page(**kwargs)


def test_mcp_default_response_is_bounded_and_has_continuation(chats):
    import server
    response = server.wechat_list_chats()
    assert response.count('(wxid:') == 100
    assert 'offset=100' in response
    assert '(wxid: synthetic_0100)' not in response


def test_empty_page_reports_total_zero(monkeypatch):
    import query
    monkeypatch.setattr(query, 'list_chats', lambda: [])
    result = query.list_chat_page()
    assert result['total'] == result['count'] == 0
    assert result['next_offset'] is None
