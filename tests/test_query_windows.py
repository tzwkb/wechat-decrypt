import pytest


@pytest.mark.parametrize('operation', ['read_chat', 'search', 'recent', 'system_events'])
@pytest.mark.parametrize('limit', [-1, 0, 2001, True, 1.5, '2'])
def test_invalid_limits_fail_before_database_discovery(monkeypatch, operation, limit):
    import query
    monkeypatch.setattr(query.db, 'get_name2id', lambda: pytest.fail('must validate before reading'))
    args = ('filehelper',) if operation == 'read_chat' else ('term',) if operation == 'search' else ()
    with pytest.raises(ValueError, match='limit'):
        getattr(query, operation)(*args, limit=limit)


@pytest.mark.parametrize('operation', ['read_chat', 'search', 'recent', 'summary', 'system_events', 'stats'])
@pytest.mark.parametrize('days', [-1, 0, True, 1.5, '7'])
def test_invalid_days_fail_before_database_discovery(monkeypatch, operation, days):
    import query
    monkeypatch.setattr(query.db, 'get_name2id', lambda: pytest.fail('must validate before reading'))
    args = ('filehelper',) if operation == 'read_chat' else ('term',) if operation == 'search' else ()
    with pytest.raises(ValueError, match='days'):
        getattr(query, operation)(*args, days=days)


@pytest.mark.parametrize('limit', [1, 50, 2000])
def test_valid_limit_boundaries(limit):
    import query
    query._validate_window(1, limit)
