import json
from datetime import datetime
from zoneinfo import ZoneInfo

import workbench as wb
import workbench_journal as journal
from test_workbench_journal import client, fill, view


def test_card_tasks_boundaries_and_evidence():
    cards = [wb.Card(id=f'{i:032x}', name='演示证券', code='000001', review_date=day,
                     status=status, evidence=[wb.Evidence(title='演示来源', status='未核验'), wb.Evidence(status='部分支持')])
             for i, (day, status) in enumerate([
                 ('2026-09-08', '草稿'), ('2026-09-09', '草稿'),
                 ('2026-09-10', '草稿'), ('2026-09-08', '已撤销'), ('', '草稿')], 1)]
    state = wb.Snapshot(cards=cards)
    items = journal.task_items(state, [], '2026-09-09')
    plans = [t for t in items if t['kind'] == 'plan']
    assert [t['date'] for t in plans] == ['2026-09-08', '2026-09-09']
    assert [t['overdue'] for t in plans] == [True, False]
    assert len([t for t in items if t['kind'] == 'evidence']) == 4
    assert all('有 1 条' in t['detail'] for t in items if t['kind'] == 'evidence')
    assert journal.task_items(state, [], '2026-09-10')[2]['kind'] == 'plan'


def test_tasks_read_only_and_card_completion(client):
    saved = client.post('/api/workbench/save', json={'revision': 0, 'card': {
        'name': '演示证券', 'code': '000001', 'review_date': '2000-01-01',
        'evidence': [{'title': '待核验材料'}]}}).json()
    before = wb.data_path().read_bytes()
    result = client.get('/api/workbench/journal/tasks').json()
    assert result['today'] == datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    assert result['counts'] == {'plan': 1, 'evidence': 1, 'link': 0, 'review': 0}
    assert wb.data_path().read_bytes() == before
    assert not (journal.root() / 'trades.json').exists()
    card = saved['cards'][0]
    card['review_date'] = '2099-01-01'
    card['evidence'][0]['status'] = '已核实'
    assert client.post('/api/workbench/save', json={'revision': saved['revision'], 'card': card}).status_code == 200
    assert client.get('/api/workbench/journal/tasks').json()['items'] == []


def test_cycle_tasks_completion_and_new_fill(client):
    fill(client, 1)
    result = client.get('/api/workbench/journal/tasks').json()
    assert result['counts']['link'] == 1
    assert result['counts']['review'] == 0
    state = view(client)
    assert client.post('/api/workbench/journal/link', json={'revision': state['revision'], 'cycle_id': f'{1:032x}', 'card_id': None}).status_code == 200
    assert client.get('/api/workbench/journal/tasks').json()['items'] == []
    fill(client, 2, 'sell')
    result = client.get('/api/workbench/journal/tasks').json()
    assert result['counts']['link'] == 1
    assert result['counts']['review'] == 1
    state = view(client)
    linked = client.post('/api/workbench/journal/link', json={'revision': state['revision'], 'cycle_id': f'{1:032x}', 'card_id': None}).json()
    assert client.post('/api/workbench/journal/review', json={'revision': linked['revision'], 'cycle_id': f'{1:032x}', 'review': {'execution': '无事前计划', 'lesson': '记录实际判断'}}).status_code == 200
    assert client.get('/api/workbench/journal/tasks').json()['items'] == []


def test_incomplete_cycle_still_needs_review(client):
    cycle = {'id': 'demo', 'name': '演示', 'code': '000001', 'start': '2026-09-01', 'end': '2026-09-02',
             'complete': False, 'review': None, 'link_status': '关联不一致，请重新选择', 'status': '已清仓'}
    items = journal.task_items(wb.Snapshot(), [cycle], '2026-09-09')
    assert [t['kind'] for t in items] == ['link', 'review']
    assert '历史不完整' in items[1]['detail']


def test_corrupt_source_is_not_empty_success(client):
    path = journal.root() / 'trades.json'
    path.write_text('{broken')
    assert client.get('/api/workbench/journal/tasks').status_code == 500
    assert path.read_text() == '{broken'


def test_mixed_explicit_links_require_resolution(client):
    fill(client, 1)
    fill(client, 2, 'sell')
    state = wb.read(wb.data_path())
    card = wb.Card(name='演示', code='000001')
    state.cards.append(card)
    state.trade_links = {f'{1:032x}': wb.TradeLink(card_id=card.id), f'{2:032x}': wb.TradeLink(card_id=None)}
    cycles = journal.build_cycles(journal.trades(), state)
    items = journal.task_items(state, cycles, '2026-09-09')
    assert len([t for t in items if t['kind'] == 'link']) == 1
