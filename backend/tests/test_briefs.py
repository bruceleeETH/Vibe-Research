import copy
import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import brief_store as store
from briefs import router

THREAD = '11111111-1111-4111-8111-111111111111'


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 10, 8, 20, tzinfo=store.TZ))
    store.configure('morning', THREAD, '测试早间来源')
    store.configure('evening', THREAD, '测试晚间来源')


def payload(title='# 每日早间投资简报｜2026年9月9日', status='completed'):
    return {'schemaVersion': 1, 'thread': {'id': THREAD, 'kind': 'chatgpt', 'title': '测试来源', 'updatedAt': 1788912000},
            'turns': [{'status': status, 'items': [{'type': 'agentMessage', 'id': 'message-1', 'text': title + '\n\n' + '示例研究正文，不是市场数据。' * 30}]}]}


def test_archive_preserves_raw_provenance_and_is_idempotent():
    raw = payload()
    result = store.import_thread('morning', raw)
    assert result['imported'] == 1
    assert store.import_thread('morning', raw)['unchanged'] == 1
    entry = store.day_view('2026-09-09')['slots'][0]
    assert entry['status'] == 'available'
    record = entry['record']
    assert record['body'] == raw['turns'][0]['items'][0]['text']
    assert record['published_at'] is None
    assert record['observed_at'].startswith('2026-09-10')
    assert record['date'] == '2026-09-09'
    assert len(store.read_state()['records']) == 1
    assert not (store.data_path().parents[1] / 'portfolio.json').exists()


def test_source_mismatch_cannot_write_or_replace_configuration():
    raw = payload(); raw['thread']['id'] = 'other-thread'
    with pytest.raises(store.BriefError, match='配置不符'):
        store.import_thread('morning', raw)
    with pytest.raises(store.BriefError, match='不能静默替换'):
        store.configure('morning', '22222222-2222-4222-8222-222222222222', '别的任务')
    assert not store.read_state()['records']


def test_yearless_heading_requires_explicit_year():
    raw = payload('# 🌙 9月9日晚间投资简报')
    with pytest.raises(store.BriefError, match='年份'):
        store.import_thread('evening', raw)
    store.import_thread('evening', raw, year_hint=2026)
    assert store.day_view('2026-09-09')['slots'][1]['record']['date_basis'] == '标题月日 + 同步时指定年份'


@pytest.mark.parametrize('title', ['提醒：是否继续运行？', '# 2026年9月9日投资问答', '# 2026年9月9日晚间投资简报'])
def test_filters_non_briefs_and_wrong_slot(title):
    assert store.import_thread('morning', payload(title))['matched'] == 0


def test_incomplete_truncated_empty_future_items_are_not_archived():
    assert store.import_thread('morning', payload(status='inProgress'))['matched'] == 0
    for change in ({'truncated': True}, {'text': ''}, {'text': '# 2026年9月11日早间投资简报\n' + '未来内容' * 100}, {'text': '# 2026年9月9日早间投资简报\n很短'}):
        raw = payload(); raw['turns'][0]['items'][0].update(change)
        assert store.import_thread('morning', raw)['matched'] == 0
    raw = payload(); raw['turns'][0]['items'][0]['text'] += '补充正文' * 1000
    assert store.import_thread('morning', raw, max_output_chars=1000)['skipped']['正文可能截断'] == 1


def test_failure_and_missing_day_preserve_previous_body(monkeypatch):
    store.set_schedule('morning', 'sync-morning', ['08:15', '09:15'])
    store.import_thread('morning', payload())
    store.record_failure('morning', '来源暂不可读')
    assert store.day_view('2026-09-09')['slots'][0]['record']
    today = store.day_view()
    assert today['slots'][0]['status'] == 'missing'
    assert today['slots'][1]['status'] == 'pending'
    assert today['slots'][0]['source']['last_error'] == '来源暂不可读'
    assert today['slots'][0]['latest_date'] == '2026-09-09'
    raw = payload(); raw['turns'] = []
    store.import_thread('morning', raw)
    assert store.day_view()['slots'][0]['source']['last_error'] is None
    assert store.day_view()['slots'][0]['status'] == 'missing'
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 11, 1, tzinfo=store.TZ))
    assert store.day_view()['slots'][0]['sync_overdue']


def test_older_snapshot_cannot_roll_back_updated_message():
    raw = payload(); store.import_thread('morning', raw)
    newer = copy.deepcopy(raw); newer['thread']['updatedAt'] += 60
    newer['turns'][0]['items'][0]['text'] += '\n来源修订'
    store.import_thread('morning', newer)
    with pytest.raises(store.BriefError, match='过期来源快照'):
        store.import_thread('morning', raw)
    assert store.day_view('2026-09-09')['slots'][0]['record']['body'].endswith('来源修订')


def test_newest_turn_and_last_reply_win_for_same_day():
    raw = payload()
    newer_turn = copy.deepcopy(raw['turns'][0])
    newer_turn['items'][0]['text'] += '\n新版'
    newer_turn['items'][0]['id'] = 'message-2'
    raw['turns'].insert(0, newer_turn)
    store.import_thread('morning', raw)
    assert store.day_view('2026-09-09')['slots'][0]['record']['message_id'] == 'message-2'


def test_equal_snapshot_with_different_body_does_not_overwrite():
    raw = payload(); store.import_thread('morning', raw)
    raw['turns'][0]['items'][0]['text'] += '\n不同正文但没有更新来源时间'
    with pytest.raises(store.BriefError, match='冲突正文'):
        store.import_thread('morning', raw)
    assert not store.day_view('2026-09-09')['slots'][0]['record']['body'].endswith('没有更新来源时间')


@pytest.mark.parametrize('change', [{'thread': None}, {'turns': [None]}, {'turns': [{'status': 'completed', 'items': [None]}]}])
def test_malformed_source_is_rejected_without_partial_write(change):
    with pytest.raises(store.BriefError):
        store.import_thread('morning', payload() | change)
    assert not store.read_state()['records']


def test_december_import_in_january_does_not_guess_current_year(monkeypatch):
    monkeypatch.setattr(store, 'now', lambda: datetime(2027, 1, 1, 9, tzinfo=store.TZ))
    raw = payload('# 12月31日晚间投资简报')
    store.import_thread('evening', raw, year_hint=2026)
    assert store.day_view('2026-12-31')['slots'][1]['record']
    assert store.import_thread('evening', raw, year_hint=2027)['matched'] == 0


@pytest.mark.parametrize('content', ['{broken', '{"version":1,"sources":[],"records":{}}'])
def test_corrupt_archive_never_overwritten(content):
    store.data_path().write_text(content)
    with pytest.raises(store.BriefError, match='损坏'):
        store.import_thread('morning', payload())
    assert store.data_path().read_text() == content


def test_content_hash_detects_tampered_record():
    store.import_thread('morning', payload())
    state = store.read_state(); state['records']['2026-09-09/morning']['body'] += 'tampered'
    store.data_path().write_text(json.dumps(state))
    with pytest.raises(store.BriefError, match='损坏'):
        store.read_state()


def test_readonly_api_bad_date_and_archive_errors():
    app = FastAPI(); app.include_router(router)
    client = TestClient(app)
    assert client.get('/api/workbench/briefs?date=2026-09-09').status_code == 200
    assert client.get('/api/workbench/briefs?date=../x').status_code == 422
    assert client.get('/api/workbench/briefs?date=2026-02-30').status_code == 422
    assert client.post('/api/workbench/briefs', json={}).status_code == 405
    store.data_path().write_text('broken')
    assert client.get('/api/workbench/briefs').status_code == 500


def test_schedule_configuration_does_not_claim_a_run():
    store.set_schedule('morning', 'sync-morning', ['08:15', '09:15'])
    source = store.day_view()['slots'][0]['source']
    assert source['schedule']['times'] == ['08:15', '09:15']
    assert not source.get('last_checked_at')


def test_early_manual_check_does_not_mask_missed_scheduled_run(monkeypatch):
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 10, 6, tzinfo=store.TZ))
    store.set_schedule('morning', 'sync', ['08:15', '09:15'])
    store.import_thread('morning', payload())
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 10, 8, 24, tzinfo=store.TZ))
    assert not store.day_view()['slots'][0]['sync_overdue']
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 10, 8, 25, tzinfo=store.TZ))
    missed = store.day_view()['slots'][0]
    assert missed['sync_overdue']
    assert missed['sync_due_at'] == '2026-09-10T08:15:00+08:00'
    store.import_thread('morning', payload())
    assert not store.day_view()['slots'][0]['sync_overdue']
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 10, 9, 25, tzinfo=store.TZ))
    assert store.day_view()['slots'][0]['sync_overdue']


def test_new_configuration_has_no_retroactive_missed_runs(monkeypatch):
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 10, 10, tzinfo=store.TZ))
    store.set_schedule('morning', 'sync', ['08:15', '09:15'])
    assert not store.day_view()['slots'][0]['sync_overdue']
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 11, 8, 25, tzinfo=store.TZ))
    assert store.day_view()['slots'][0]['sync_overdue']


def test_yesterday_missed_evening_run_remains_overdue_after_midnight(monkeypatch):
    store.set_schedule('evening', 'sync', ['22:45', '23:45'])
    store.import_thread('evening', payload('# 9月9日晚间投资简报'), year_hint=2026)
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 11, 0, 10, tzinfo=store.TZ))
    result = store.day_view()['slots'][1]
    assert result['sync_overdue']
    assert result['sync_due_at'] == '2026-09-10T23:45:00+08:00'
