import json
from datetime import datetime
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import limitup

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(limitup, 'now', lambda: datetime(2026, 9, 9, 16, tzinfo=limitup.TZ))
    app = FastAPI(); app.include_router(limitup.router)
    return TestClient(app)


def payload(day=20260908, count=2):
    return {'rc': 0, 'data': {'qdate': day, 'tc': count, 'pool': [
        {'c': '000001', 'n': '首板示例', 'lbc': 1, 'p': 12340, 'zdp': 10, 'fbt': 92500, 'lbt': 145959, 'zbc': 2, 'fund': 12345678, 'hs': 3.2},
        {'c': '000002', 'n': '未知示例', 'lbc': '-', 'p': '-', 'fbt': '-', 'lbt': 999999},
    ]}}


def source(monkeypatch, value):
    class Response:
        def raise_for_status(self): pass
        def json(self): return value
    monkeypatch.setattr(limitup.astock, 'em_get', lambda *args, **kwargs: Response())


def test_first_board_and_nulls_saved_raw(client, monkeypatch):
    source(monkeypatch, payload())
    r = client.get('/api/market/limit-up?date=2026-09-08')
    assert r.status_code == 200
    d = r.json()
    assert d['coverage'] == 'source_complete' and d['count'] == 2
    assert d['stocks'][0]['boards'] == 1
    assert d['stocks'][0]['first_seal'] == '09:25:00'
    assert d['stocks'][0]['price'] == 12.34
    assert d['stocks'][1]['boards'] is None
    assert d['stocks'][1]['price'] is None and d['stocks'][1]['last_seal'] is None
    assert d['missing_fields']['boards'] == 1
    assert d['phase'] == 'after_close'
    saved = json.loads((limitup.directory() / '2026-09-08.json').read_text())
    assert saved['raw'] == payload()
    assert 'raw' not in d
    assert client.get('/api/market/limit-up/dates').json()['dates'] == ['2026-09-08']


def test_wrong_date_fails_without_fallback(client, monkeypatch):
    source(monkeypatch, payload(day=20260907))
    assert client.get('/api/market/limit-up?date=2026-09-08').status_code == 502
    assert not (limitup.directory() / '2026-09-08.json').exists()


def test_partial_does_not_replace_complete(client, monkeypatch):
    source(monkeypatch, payload())
    client.get('/api/market/limit-up?date=2026-09-08')
    path = limitup.directory() / '2026-09-08.json'; before = path.read_bytes()
    source(monkeypatch, payload(count=3))
    data = client.get('/api/market/limit-up?date=2026-09-08&refresh=true').json()
    assert data['warning'] and data['coverage'] == 'source_complete'
    assert path.read_bytes() == before


def test_unavailable_retains_saved_sample(client, monkeypatch):
    source(monkeypatch, payload())
    client.get('/api/market/limit-up?date=2026-09-08')
    source(monkeypatch, {'rc': 0, 'data': None})
    data = client.get('/api/market/limit-up?date=2026-09-08&refresh=true').json()
    assert data['origin'] == 'local' and '刷新失败' in data['warning']
    assert data['date'] == '2026-09-08' and data['count'] == 2


def test_partial_flag_and_intraday(client, monkeypatch):
    monkeypatch.setattr(limitup, 'now', lambda: datetime(2026, 9, 9, 10, tzinfo=limitup.TZ))
    source(monkeypatch, payload(day=20260909, count=3))
    data = client.get('/api/market/limit-up?date=2026-09-09').json()
    assert data['coverage'] == 'partial' and data['phase'] == 'intraday'


@pytest.mark.parametrize('day', ['2026-09-10', '2026-02-30', '../bad', '20260908'])
def test_invalid_date(client, day):
    assert client.get('/api/market/limit-up', params={'date': day}).status_code == 400


def test_corrupt_archive_not_overwritten(client, monkeypatch):
    limitup.directory().mkdir(parents=True)
    path = limitup.directory() / '2026-09-08.json'; path.write_text('{bad')
    source(monkeypatch, payload())
    assert client.get('/api/market/limit-up?date=2026-09-08&refresh=true').status_code == 500
    assert path.read_text() == '{bad'


def test_duplicate_and_empty_are_not_complete_samples(client, monkeypatch):
    data = payload(); data['data']['pool'][1]['c'] = '000001'
    source(monkeypatch, data)
    assert client.get('/api/market/limit-up?date=2026-09-08').status_code == 502
    data['data']['pool'] = []; data['data']['tc'] = 0
    assert client.get('/api/market/limit-up?date=2026-09-08').status_code == 502


def test_legacy_pool_rejects_mismatched_source_date(client, monkeypatch):
    source(monkeypatch, payload(day=20260908))
    assert limitup.astock.em_zt_topic_pool('getTopicZTPool', '20260909') == []
    assert len(limitup.astock.em_zt_topic_pool('getTopicZTPool', '20260908')) == 2


def test_intraday_upgrades_to_after_close_and_cache_reads(client, monkeypatch):
    source(monkeypatch, payload(day=20260909))
    monkeypatch.setattr(limitup, 'now', lambda: datetime(2026, 9, 9, 14, tzinfo=limitup.TZ))
    assert limitup.get_day('2026-09-09')['phase'] == 'intraday'
    monkeypatch.setattr(limitup, 'now', lambda: datetime(2026, 9, 9, 15, 15, tzinfo=limitup.TZ))
    assert limitup.get_day('2026-09-09')['phase'] == 'after_close'
    source(monkeypatch, {'rc': 1})
    assert limitup.get_day('2026-09-09')['origin'] == 'local'
