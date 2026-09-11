import json
from datetime import datetime
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import limitup as seeds
import limitup_outcomes as o

DAY = '2026-09-04'
TARGET = '2026-09-07'
STOCK = {'code': '000001', 'name': '测试', 'price': 10, 'boards': 1, 'market': '沪深主板'}
BAR = [[TARGET, '10.2', '11', '11', '10', '100']]
OLD = {'000001': {'p': 11000, 'zdp': 10, 'amount': 100}}
SEALED = {'000001': {'lbc': 2}}

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(seeds, 'now', lambda: datetime(2026, 9, 8, 16, tzinfo=seeds.TZ))
    seed = {'schema_version': 1, 'date': DAY, 'phase': 'after_close', 'coverage': 'source_complete', 'stocks': [STOCK]}
    seeds.directory().mkdir(parents=True)
    seeds.atomic_save(seeds.directory() / f'{DAY}.json', seed)
    app = FastAPI(); app.include_router(o.router)
    return TestClient(app), seed


def test_weekend_not_calendar_day():
    assert o.next_session(DAY, [[DAY, 1, 1, 1, 1, 10], [TARGET, 1, 1, 1, 1, 10]]) == TARGET
    assert o.next_session(DAY, [[DAY, 1, 1, 1, 1, 10]]) is None
    with pytest.raises(ValueError): o.next_session(DAY, [])


def test_promotion_and_prices():
    r = o.classify(STOCK, TARGET, BAR, OLD, SEALED, {})
    assert r['close_pct'] == 10 and r['open_pct'] == pytest.approx(2)
    assert r['promoted'] is True and r['touched'] is True


@pytest.mark.parametrize('rows,old', [([], OLD), ([[TARGET, 10, 11, 11, 10, 0]], OLD), (BAR, {}), (BAR, None)])
def test_missing_or_suspended_not_negative(rows, old):
    r = o.classify(STOCK, TARGET, rows, old, {}, {})
    assert all(r[k] is None for k in ('close_pct', 'promoted', 'touched'))


def test_failed_seal_not_promotion():
    r = o.classify(STOCK, TARGET, BAR, OLD, {}, {'000001': {}})
    assert r['promoted'] is False and r['touched'] is True


def test_missing_pool_no_negative_inference():
    r = o.classify(STOCK, TARGET, BAR, OLD, None, {})
    assert r['promoted'] is None and r['touched'] is None


def test_mismatched_boards_unknown():
    assert o.classify(STOCK, TARGET, BAR, OLD, {'000001': {'lbc': 4}}, {})['promoted'] is None


def test_negative_return_and_reference_change():
    old = {'000001': {'p': 9000, 'zdp': -10, 'amount': 100}}
    rows = [[TARGET, 9.1, 9, 9.2, 9, 100]]
    r = o.classify(STOCK, TARGET, rows, old, {}, {})
    assert r['close_pct'] == -10 and r['touched'] is False
    r = o.classify(STOCK | {'price': 20}, TARGET, rows, old, {}, {})
    assert r['close_pct'] == -10 and r['open_pct'] is None


@pytest.mark.parametrize('tc,qdate', [(2,20260907),(1,20260908)])
def test_pool_rejects_incomplete_or_wrong_date(monkeypatch, tc, qdate):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'rc': 0, 'data': {'tc': tc, 'qdate': qdate, 'pool': [{'c': '000001'}]}}
    monkeypatch.setattr(o.astock, 'em_get', lambda *a, **k: Response())
    with pytest.raises(ValueError): o.pool('getTopicZTPool', TARGET)


def test_process_api_and_stats(env, monkeypatch):
    client, seed = env
    monkeypatch.setattr(o, 'bars', lambda symbol, day: [[DAY,10,10,10,10,100]] + BAR)
    monkeypatch.setattr(o, 'pool', lambda endpoint, day: ({'getYesterdayZTPool': OLD, 'getTopicZTPool': SEALED, 'getTopicZBPool': {}}[endpoint], {'source': endpoint}))
    o.process(DAY)
    r = client.get('/api/market/limit-up-outcomes/day', params={'date': DAY}).json()
    assert r['state'] == 'complete' and r['target_date'] == TARGET and 'raw' not in r
    g = o.statistics()['groups'][0]
    assert g['promotion_n'] == g['promoted'] == g['returns_n'] == 1
    assert not o.statistics(market='创业板')['groups']
    assert not o.statistics(start='2026-09-05')['groups']
    seed['stocks'][0] = STOCK | {'boards': 2}
    seeds.atomic_save(seeds.directory() / f'{DAY}.json', seed)
    assert o.statistics()['excluded_dates'] == [DAY]


def test_wait_until_close(env, monkeypatch):
    monkeypatch.setattr(seeds, 'now', lambda: datetime(2026, 9, 7, 14, tzinfo=seeds.TZ))
    monkeypatch.setattr(o, 'bars', lambda *a: [[DAY,10,10,10,10,100]] + BAR)
    monkeypatch.setattr(o, 'pool', lambda *a: pytest.fail('must not fetch future outcome'))
    o.process(DAY)
    assert o.read_result(DAY)['state'] == 'pending'


def test_field_denominators(env):
    _, seed = env
    r = o.classify(STOCK, TARGET, BAR, OLD, None, None)
    seeds.atomic_save(o.path_for(DAY), {'date': DAY, 'seed_hash': o.fingerprint(seed), 'state': 'partial', 'rows': [r]})
    g = o.statistics()['groups'][0]
    assert g['returns_n'] == 1 and g['promotion_n'] == g['touch_n'] == 0


def test_complete_retained_on_retry_failure(env, monkeypatch):
    _, seed = env
    original = {'date': DAY, 'seed_hash': o.fingerprint(seed), 'state': 'complete', 'rows': [o.classify(STOCK, TARGET, BAR, OLD, SEALED, {})]}
    seeds.atomic_save(o.path_for(DAY), original)
    monkeypatch.setattr(o, 'bars', lambda *a: (_ for _ in ()).throw(ValueError('offline')))
    o.process(DAY)
    assert o.read_result(DAY)['rows'] == original['rows'] and o.read_result(DAY)['state'] == 'complete'


def test_bad_date_and_missing_sample(env):
    client, _ = env
    assert client.post('/api/market/limit-up-outcomes/day?date=../../x').status_code == 400
    assert client.post('/api/market/limit-up-outcomes/day?date=2026-09-01').status_code == 404


def test_stats_rejects_reversed_dates(env):
    client, _ = env
    assert client.get('/api/market/limit-up-outcomes/stats?start=2026-09-08&end=2026-09-01').status_code == 400
    assert client.get('/api/market/limit-up-outcomes/stats?start=invalid').status_code == 400
