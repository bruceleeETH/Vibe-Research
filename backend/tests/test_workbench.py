import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from workbench import router, data_path

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)

def draft():
    return {'name': '测试证券', 'code': '000001'}

def test_save_overwrites_and_detects_conflict(client):
    saved = client.post('/api/workbench/save', json={'revision': 0, 'card': draft()}).json()
    card = saved['cards'][0]
    card['thesis'] = '更新后的逻辑'
    updated = client.post('/api/workbench/save', json={'revision': 1, 'card': card})
    assert updated.status_code == 200
    assert len(updated.json()['cards']) == 1
    assert client.get('/api/workbench').json()['cards'][0]['thesis'] == '更新后的逻辑'
    assert client.post('/api/workbench/save', json={'revision': 1, 'card': card}).status_code == 409
    assert not (data_path().parents[1] / 'portfolio.json').exists()

def test_confirmation_validation_and_server_time(client):
    card = draft() | {'status': '已确认'}
    assert client.post('/api/workbench/save', json={'revision': 0, 'card': card}).status_code == 422
    card.update(strategy='产业趋势', strategy_ack='产业趋势', return_type='业绩增长', subject='测试业务', basis='测试依据', thesis='逻辑', entry='条件', exit='退出', review_date='2026-09-09', confirmed_at='1900-01-01')
    r = client.post('/api/workbench/save', json={'revision': 0, 'card': card})
    assert r.status_code == 200
    assert not r.json()['cards'][0]['confirmed_at'].startswith('1900')

def test_restore_delete_and_bad_backup(client):
    backup = client.post('/api/workbench/save', json={'revision': 0, 'card': draft()}).json()
    card = backup['cards'][0]
    assert client.post('/api/workbench/delete/' + card['id'], json={'revision': 1}).json()['cards'] == []
    assert client.post('/api/workbench/restore', json={'revision': 2, 'snapshot': backup}).json()['cards'] == backup['cards']
    bad = {'revision': 0, 'cards': [card, card]}
    assert client.post('/api/workbench/restore', json={'revision': 3, 'snapshot': bad}).status_code == 422
    assert len(client.get('/api/workbench').json()['cards']) == 1

def test_corrupt_file_not_overwritten(client):
    path = data_path(); path.parent.mkdir(parents=True); path.write_text('{broken')
    assert client.get('/api/workbench').status_code == 500
    assert client.post('/api/workbench/save', json={'revision': 0, 'card': draft()}).status_code == 500
    assert path.read_text() == '{broken'


def guided():
    return draft() | {
        'strategy': '产业趋势', 'strategy_ack': '产业趋势', 'return_type': '业绩增长',
        'subject': '测试业务订单', 'basis': '演示公告，尚待核验', 'logic_ids': ['orders'],
        'risk_ids': ['delay'], 'review_date': '2026-09-10', 'status': '已确认',
        'entry_conditions': [{'id': 'price_above', 'value': '12.5'}],
        'exit_conditions': [{'id': 'deadline', 'value': '2026-10-01', 'detail': '指定订单'}],
        'evidence': [{'title': '演示公告'}],
    }


def test_structured_roundtrip_does_not_verify_evidence(client):
    r = client.post('/api/workbench/save', json={'revision': 0, 'card': guided()})
    assert r.status_code == 200
    card = r.json()['cards'][0]
    assert card['evidence'][0]['status'] == '未核验'
    assert card['logic_ids'] == ['orders']
    assert card['entry_conditions'][0]['value'] == '12.5'
    backup = client.get('/api/workbench').json()
    restored = client.post('/api/workbench/restore', json={'revision': 1, 'snapshot': backup})
    assert restored.json()['cards'] == backup['cards']


@pytest.mark.parametrize('condition', [
    {'id': 'price_above', 'value': ''}, {'id': 'price_above', 'value': '-1'},
    {'id': 'price_above', 'value': 'NaN'}, {'id': 'price_above', 'value': 'Infinity'},
    {'id': 'ma_above', 'value': '1.5'}, {'id': 'ma_above', 'value': '1001'},
])
def test_missing_or_invalid_parameters_block_confirmation(client, condition):
    card = guided() | {'entry_conditions': [condition]}
    assert client.post('/api/workbench/save', json={'revision': 0, 'card': card}).status_code == 422
    card['status'] = '草稿'
    assert client.post('/api/workbench/save', json={'revision': 0, 'card': card}).status_code == 200


def test_strategy_switch_requires_reconfirmation(client):
    card = guided() | {'strategy': '事件驱动'}
    assert client.post('/api/workbench/save', json={'revision': 0, 'card': card}).status_code == 422
    card['strategy_ack'] = '事件驱动'
    assert client.post('/api/workbench/save', json={'revision': 0, 'card': card}).status_code == 200


@pytest.mark.parametrize('patch', [
    {'subject': ''}, {'basis': ''}, {'return_type': '自定义', 'return_custom': ''},
    {'exit_conditions': [{'id': 'deadline', 'value': '2026-02-30', 'detail': '订单'}]},
    {'exit_conditions': [{'id': 'deadline', 'value': '2026-10-01', 'detail': ''}]},
    {'logic_ids': ['made_up']}, {'entry_conditions': [{'id': 'made_up', 'value': '1'}]},
])
def test_guided_confirmation_rejects_incomplete_claims(client, patch):
    assert client.post('/api/workbench/save', json={'revision': 0, 'card': guided() | patch}).status_code == 422


def test_catalog_and_empty_strategy(client):
    assert client.get('/api/workbench/catalog').json()['strategies'] == ['产业趋势', '事件驱动', '情绪资金']
    saved = client.post('/api/workbench/save', json={'revision': 0, 'card': draft()}).json()
    assert saved['cards'][0]['strategy'] == ''
