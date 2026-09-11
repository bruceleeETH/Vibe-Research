import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import brief_store as store
import brief_manual_sync as manual
from briefs import router

THREAD = '11111111-1111-4111-8111-111111111111'


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex'))
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 11, 10, tzinfo=store.TZ))
    monkeypatch.setattr(manual.shutil, 'which', lambda name: '/test/codex')
    for slot in store.SLOTS:
        store.configure(slot, THREAD, slot)
        store.set_schedule(slot, 'test-sync', ['09:15'])
    config = tmp_path / 'codex/automations/test-sync/automation.toml'
    config.parent.mkdir(parents=True)
    config.write_text(f'kind = "heartbeat"\ntarget_thread_id = "{THREAD}"\n')


def checked(monkeypatch):
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 11, 10, 1, tzinfo=store.TZ))
    for slot in store.SLOTS:
        raw = {'schemaVersion': 1, 'thread': {'id': THREAD, 'kind': 'chatgpt', 'updatedAt': 1789092000}, 'turns': []}
        store.import_thread(slot, raw, 2026)


def test_duplicate_requests_dispatch_once_and_no_fake_success(monkeypatch):
    job, created = manual.request_sync()
    assert created
    same, created = manual.request_sync()
    assert same['id'] == job['id'] and not created
    monkeypatch.setattr(manual.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0))
    manual.dispatch(job['id'])
    assert manual.status()['job']['status'] == 'queued'
    manual.start(job['id'])
    with pytest.raises(store.BriefError, match='尚未全部检查'):
        manual.finish(job['id'])
    assert store.read_state()['records'] == {}


def test_both_checked_without_today_content_is_success(monkeypatch):
    job, _ = manual.request_sync(); manual.start(job['id']); checked(monkeypatch)
    result = manual.finish(job['id'])
    assert result['status'] == 'completed'
    assert all(not r['today_archived'] for r in result['results'])
    with pytest.raises(store.BriefError):
        manual.start(job['id'])


def test_source_failure_is_visible(monkeypatch):
    job, _ = manual.request_sync(); manual.start(job['id']); checked(monkeypatch)
    store.record_failure('evening', '测试来源不可读')
    result = manual.finish(job['id'])
    assert result['status'] == 'failed'
    assert result['results'][1]['error'] == '测试来源不可读'


def test_expired_request_cannot_run_or_overwrite_new_request(monkeypatch):
    old, _ = manual.request_sync()
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 11, 10, 16, tzinfo=store.TZ))
    assert manual.status()['job']['status'] == 'timed_out'
    with pytest.raises(store.BriefError): manual.start(old['id'])
    new, created = manual.request_sync()
    assert created and new['id'] != old['id']
    manual._update(old['id'], status='failed')
    assert manual.status()['job']['id'] == new['id']


def test_delivery_failure_and_unknown_do_not_claim_completed(monkeypatch):
    job, _ = manual.request_sync()
    def timeout(*a, **k): raise manual.subprocess.TimeoutExpired('codex', 25)
    monkeypatch.setattr(manual.subprocess, 'run', timeout)
    manual.dispatch(job['id'])
    assert manual.status()['job']['status'] == 'delivery_unknown'
    assert not manual.request_sync()[1]
    monkeypatch.setattr(manual.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1))
    manual.dispatch(job['id'])
    assert manual.status()['job']['status'] == 'failed'


def test_dispatch_uses_fixed_local_target_and_argument_array(monkeypatch):
    calls = []
    monkeypatch.setattr(manual.subprocess, 'run', lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(returncode=0))
    job, _ = manual.request_sync(); manual.dispatch(job['id'])
    args, kwargs = calls[0]
    assert args[:5] == ['/test/codex', 'queue', '--thread', THREAD, '--message']
    assert 'start-manual --request-id ' + job['id'] in args[5]
    assert not kwargs.get('shell')
    assert 'dangerously' not in ' '.join(args)


def test_post_rejects_nonlocal_and_missing_header(monkeypatch):
    app = FastAPI(); app.include_router(router)
    client = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 1234))
    monkeypatch.setattr(manual, 'dispatch', lambda request_id: None)
    assert client.post('/api/workbench/briefs/sync').status_code == 403
    assert client.post('/api/workbench/briefs/sync', headers={'X-Brief-Sync': 'manual', 'Origin': 'https://evil.example'}).status_code == 403
    first = client.post('/api/workbench/briefs/sync', headers={'X-Brief-Sync': 'manual', 'Origin': 'http://127.0.0.1:5899'})
    assert first.status_code == 202
    second = client.post('/api/workbench/briefs/sync', headers={'X-Brief-Sync': 'manual'})
    assert second.json()['job']['id'] == first.json()['job']['id']
    assert client.get('/api/workbench/briefs/sync').json()['job']['status'] == 'dispatching'


def test_missing_configuration_does_not_queue(monkeypatch):
    with store.transaction() as state: state['sources']['morning'].pop('schedule')
    assert not manual.status()['available']
    with pytest.raises(store.BriefError): manual.request_sync()
    assert 'manual_sync' not in store.read_state()
