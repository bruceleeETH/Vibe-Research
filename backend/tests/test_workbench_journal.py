import json
from functools import partial

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from trade_service import TradeService
import workbench as wb
import workbench_journal as journal


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(journal, 'TradeService', partial(TradeService, ledger_path=tmp_path / 'ledger.md'))
    app = FastAPI()
    app.include_router(wb.router)
    app.include_router(journal.router)
    return TestClient(app)


def fill(client, n, side='buy', qty=100, price='10', day='2026-09-01', code='000001'):
    return client.post('/api/workbench/journal/record', json={
        'trade_id': f'{n:032x}', 'side': side, 'code': code, 'name': '演示证券',
        'quantity': qty, 'price': price, 'date': day,
    })


def view(client):
    return client.get('/api/workbench/journal').json()


def test_full_cycle_and_idempotency(client):
    assert fill(client, 1).status_code == 200
    assert fill(client, 1).json()['already_recorded'] is True
    assert fill(client, 2, qty=100, price='12').status_code == 200
    assert fill(client, 3, 'sell', qty=50, price='13').status_code == 200
    assert view(client)['cycles'][0]['remaining'] == 150
    assert fill(client, 4, 'sell', qty=150, price='9').status_code == 200
    assert fill(client, 4, 'sell', qty=150, price='9').json()['already_recorded'] is True
    data = view(client)
    c = data['cycles'][0]
    assert c['status'] == '已清仓' and c['complete']
    assert c['gross_pnl'] == -200
    assert len(c['trades']) == 4
    assert data['holdings'] == []
    assert fill(client, 5).status_code == 200
    assert len(view(client)['cycles']) == 2


def test_oversell_no_holding_and_chronological_guard(client):
    assert fill(client, 1, 'sell').status_code == 400
    assert fill(client, 2, day='2026-09-02').status_code == 200
    assert fill(client, 3, 'sell', qty=101, day='2026-09-02').status_code == 400
    assert fill(client, 4, day='2026-09-01').status_code == 400
    assert len(view(client)['cycles'][0]['trades']) == 1


def test_links_do_not_mutate_positions_and_match_security(client):
    fill(client, 1)
    state = client.post('/api/workbench/save', json={'revision': 0, 'card': {'name': '演示证券', 'code': '000001'}}).json()
    before = (journal.root() / 'portfolio.json').read_bytes()
    payload = {'revision': state['revision'], 'cycle_id': f'{1:032x}', 'card_id': state['cards'][0]['id']}
    assert client.post('/api/workbench/journal/link', json=payload).status_code == 200
    assert (journal.root() / 'portfolio.json').read_bytes() == before
    assert client.post('/api/workbench/journal/link', json=payload).status_code == 409
    assert client.post('/api/workbench/delete/' + state['cards'][0]['id'], json={'revision': 2}).status_code == 409
    fill(client, 2, code='000002')
    payload.update(revision=2, cycle_id=f'{2:032x}')
    assert client.post('/api/workbench/journal/link', json=payload).status_code == 400


def test_reviews_require_closed_and_primary_error(client):
    fill(client, 1)
    payload = {'revision': 0, 'cycle_id': f'{1:032x}', 'review': {'lesson': '遵守条件', 'execution': '按计划执行'}}
    assert client.post('/api/workbench/journal/review', json=payload).status_code == 400
    fill(client, 2, 'sell')
    payload['review']['errors'] = ['E02']
    assert client.post('/api/workbench/journal/review', json=payload).status_code == 422
    payload['review']['primary_error'] = 'E02'
    assert client.post('/api/workbench/journal/review', json=payload).status_code == 200
    assert view(client)['cycles'][0]['review']['primary_error'] == 'E02'
    backup = client.get('/api/workbench').json()
    assert client.post('/api/workbench/restore', json={'revision': 1, 'snapshot': backup}).status_code == 200
    assert view(client)['cycles'][0]['review']['lesson'] == '遵守条件'


def test_opening_position_not_counted_as_complete(client):
    root = journal.root(); root.mkdir(parents=True, exist_ok=True)
    (root / 'portfolio.json').write_text(json.dumps({'holdings': [{'code': '000001', 'shares': 100, 'cost': 9}]}))
    assert fill(client, 1, 'sell').status_code == 200
    data = view(client)
    assert data['cycles'][0]['gross_pnl'] is None
    assert data['stats']['completed'] == 0
    assert data['stats']['incomplete'] == 1


def test_malformed_trade_file_fails_closed(client):
    root = journal.root(); root.mkdir(parents=True, exist_ok=True)
    path = root / 'trades.json'; path.write_text('{broken')
    assert client.get('/api/workbench/journal').status_code == 500
    assert fill(client, 1).status_code == 500
    assert path.read_text() == '{broken'


def test_changed_holdings_flag_reconciliation(client):
    fill(client, 1)
    path = journal.root() / 'portfolio.json'
    data = json.loads(path.read_text())
    data['holdings'][0]['shares'] = 50
    data['holdings'].append({'code': '000002', 'shares': 100, 'cost': 8})
    path.write_text(json.dumps(data))
    result = view(client)
    assert result['cycles'][0]['gross_pnl'] is None
    assert not result['cycles'][0]['complete']
    assert result['untracked_holdings'] == ['000002']


def test_linked_card_cannot_change_security(client):
    fill(client, 1)
    state = client.post('/api/workbench/save', json={'revision': 0, 'card': {'name': '演示证券', 'code': '000001'}}).json()
    card = state['cards'][0]
    client.post('/api/workbench/journal/link', json={'revision': 1, 'cycle_id': f'{1:032x}', 'card_id': card['id']})
    card['code'] = '000002'
    assert client.post('/api/workbench/save', json={'revision': 2, 'card': card}).status_code == 409


def test_analytics_metrics_and_exclusions(client):
    for n, sell_price in [(1, '12'), (3, '9'), (5, '10')]:
        assert fill(client, n).status_code == 200
        assert fill(client, n + 1, 'sell', price=sell_price).status_code == 200
    assert fill(client, 7).status_code == 200
    result = client.get('/api/workbench/journal/analytics').json()
    assert result['total']['count'] == 3
    assert result['total']['gross_pnl'] == 100
    assert result['total']['win_rate'] == pytest.approx(1 / 3)
    assert result['total']['payoff_ratio'] == 2
    assert result['total']['zeros'] == 1
    assert result['excluded_open'] == 1
    assert client.get('/api/workbench/journal/analytics?start=2026-09-01&end=2026-09-01').json()['total']['count'] == 3
    assert client.get('/api/workbench/journal/analytics?start=2026-09-02').json()['total']['count'] == 0
    assert client.get('/api/workbench/journal/analytics?start=2026-09-02&end=2026-09-01').status_code == 400


def test_analytics_primary_loss_and_missing_ratio(client):
    fill(client, 1)
    fill(client, 2, 'sell', price='9')
    state = view(client)
    response = client.post('/api/workbench/journal/review', json={
        'revision': state['revision'], 'cycle_id': state['cycles'][0]['id'],
        'review': {'execution': '偏离计划', 'errors': ['E02', 'E03'], 'primary_error': 'E02', 'lesson': '演示复盘', 'next_action': ''}})
    assert response.status_code == 200
    result = client.get('/api/workbench/journal/analytics').json()
    assert result['total']['payoff_ratio'] is None
    assert [e['count'] for e in result['errors']] == [1, 1]
    assert sum(e['primary_loss'] for e in result['errors']) == 100
    assert result['executions'][0]['label'] == '偏离计划'
    assert result['strategies'][0]['label'] == '未分类'
