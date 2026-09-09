"""Local archive for existing brief messages. No network or trade side effects."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
SLOTS = {'morning': ('早间简报', '08:00'), 'evening': ('晚间简报', '22:30')}


class BriefError(ValueError):
    pass


def now():
    return datetime.now(TZ)


def valid_day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise BriefError('日期必须为 YYYY-MM-DD')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise BriefError('无效日期') from exc


def data_path():
    return Path(os.environ.get('VR_DATA_DIR', Path.home() / '.vibe-research')) / 'briefs' / 'current.json'


def read_state():
    path = data_path()
    if not path.exists():
        return {'version': 1, 'sources': {}, 'records': {}}
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
        if state['version'] != 1 or not isinstance(state['sources'], dict) or not isinstance(state['records'], dict):
            raise ValueError()
        for slot, source in state['sources'].items():
            if slot not in SLOTS or str(UUID(source['thread_id'])) != source['thread_id']:
                raise ValueError()
        for key, record in state['records'].items():
            valid_day(record['date'])
            if record['slot'] not in SLOTS or key != record['date'] + '/' + record['slot']:
                raise ValueError()
            if hashlib.sha256(record['body'].encode()).hexdigest() != record['sha256']:
                raise ValueError()
        return state
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise BriefError('简报归档损坏，已停止读取或覆盖，请检查本地文件') from exc


@contextmanager
def transaction():
    path = data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_state()
        yield state
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.briefs-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(state, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)


def configure(slot, thread_id, title):
    if slot not in SLOTS or not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        raise BriefError('来源档位或标题无效')
    try:
        thread_id = str(UUID(thread_id))
    except (ValueError, AttributeError) as exc:
        raise BriefError('来源任务 ID 无效') from exc
    with transaction() as state:
        existing = state['sources'].get(slot, {})
        if existing and existing['thread_id'] != thread_id:
            raise BriefError('该档已配置其他来源；请核对，不能静默替换')
        state['sources'][slot] = existing | {'thread_id': thread_id, 'title': title.strip()}
    return {'slot': slot, 'configured': True}


def heading_date(body, slot, year_hint):
    """Only date in the first title, never dates mentioned in the report body."""
    title = next((line.strip().lstrip('#').strip() for line in body.splitlines() if line.strip()), '')
    if len(title) > 200 or not re.search(r'(?:投资|早间|晚间).*简报', title):
        return None
    if slot == 'morning' and '晚间' in title or slot == 'evening' and '晚间' not in title:
        return None
    full = re.search(r'(20\d{2})(?:年|-)(\d{1,2})(?:月|-)(\d{1,2})(?:日)?', title)
    if full:
        parts = map(int, full.groups())
        basis = '标题明确年月日'
    else:
        partial = re.search(r'(\d{1,2})月(\d{1,2})日', title)
        if not partial:
            return None
        if not isinstance(year_hint, int) or not 2000 <= year_hint <= 2100:
            raise BriefError('标题缺少年份，需明确 year_hint，不能从同步日期猜年份')
        parts = (year_hint, *map(int, partial.groups()))
        basis = '标题月日 + 同步时指定年份'
    try:
        day = date(*parts).isoformat()
    except ValueError as exc:
        raise BriefError('简报标题日期无效') from exc
    return day, title, basis


def import_thread(slot, payload, year_hint=None, max_output_chars=16000):
    """Accept the structured read_thread result, not its preview or tool narration."""
    if slot not in SLOTS or not isinstance(payload, dict):
        raise BriefError('无效来源或读取结果')
    if not isinstance(max_output_chars, int) or max_output_chars < 1000:
        raise BriefError('需提供读取时的正文长度上限')
    observed = now()
    stamp = observed.isoformat(timespec='seconds')
    thread = payload.get('thread', {})
    if payload.get('schemaVersion') != 1 or not isinstance(thread, dict) or thread.get('kind') != 'chatgpt' or not isinstance(payload.get('turns'), list):
        raise BriefError('不是受支持的完整任务读取结果')
    try:
        updated = float(thread['updatedAt'])
        if not 0 < updated <= observed.timestamp() + 300:
            raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise BriefError('来源更新时间无效') from exc
    accepted, skipped = {}, {}

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    # read_thread turns are newest first; agent messages inside each turn are chronological.
    for turn in reversed(payload['turns']):
        if not isinstance(turn, dict) or not isinstance(turn.get('items'), list):
            raise BriefError('来源轮次结构无效')
        if turn.get('status') != 'completed':
            skip('轮次未完成')
            continue
        for item in turn.get('items', []):
            if not isinstance(item, dict):
                raise BriefError('来源消息结构无效')
            if item.get('type') != 'agentMessage':
                continue
            body = item.get('text', '')
            if not isinstance(body, str) or not body.strip():
                skip('正文为空')
                continue
            if item.get('truncated') or len(body.encode('utf-16-le')) // 2 >= max_output_chars or re.search(r'\[(?:truncated|截断)[^\]]*\]|…\s*\d+ (?:tokens|characters) truncated', body, re.I):
                skip('正文可能截断')
                continue
            heading = heading_date(body, slot, year_hint)
            if not heading:
                skip('非对应日期简报')
                continue
            day, title, basis = heading
            if valid_day(day) > observed.date():
                skip('未来日期')
                continue
            message_id = item.get('id')
            if not isinstance(message_id, str) or not message_id or len(message_id) > 200:
                skip('缺少来源消息 ID')
                continue
            if len(body.strip()) < 200:
                skip('正文过短')
                continue
            accepted[day + '/' + slot] = {
                'date': day, 'slot': slot, 'title': title, 'body': body,
                'thread_id': thread.get('id'), 'source_title': thread.get('title'),
                'message_id': message_id, 'sha256': hashlib.sha256(body.encode()).hexdigest(),
                'date_basis': basis, 'published_at': None, 'observed_at': stamp,
                'last_seen_at': stamp, 'content_status': '原简报，未独立核验',
            }
    with transaction() as state:
        source = state['sources'].get(slot)
        if not source or thread.get('id') != source['thread_id']:
            raise BriefError('来源任务与本地配置不符')
        if updated < source.get('source_updated_at', 0):
            raise BriefError('拒绝过期来源快照，保留更新内容')
        imported = unchanged = 0
        for key, record in accepted.items():
            old = state['records'].get(key)
            if old and old['message_id'] == record['message_id'] and old['sha256'] == record['sha256']:
                old['last_seen_at'] = stamp
                unchanged += 1
            else:
                if old and updated <= source.get('source_updated_at', 0):
                    raise BriefError('同一来源快照出现冲突正文，保留原有归档')
                state['records'][key] = record
                imported += 1
        source.update(last_checked_at=stamp, last_success_at=stamp, last_error=None,
                      source_updated_at=updated, skipped=skipped, matched=len(accepted))
    return {'slot': slot, 'imported': imported, 'unchanged': unchanged, 'matched': len(accepted), 'skipped': skipped}


def record_failure(slot, message):
    if slot not in SLOTS or not isinstance(message, str) or not message.strip():
        raise BriefError('需填写有效来源和失败原因')
    with transaction() as state:
        if slot not in state['sources']:
            raise BriefError('来源未配置')
        state['sources'][slot].update(last_checked_at=now().isoformat(timespec='seconds'), last_error=message[:500])
    return {'slot': slot, 'failure_recorded': True}


def set_schedule(slot, automation_id, times):
    if slot not in SLOTS or not re.fullmatch(r'[\w-]{1,100}', automation_id):
        raise BriefError('无效同步计划')
    if not times or any(not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', t) for t in times):
        raise BriefError('同步时间必须是 HH:MM')
    with transaction() as state:
        if slot not in state['sources']:
            raise BriefError('来源未配置')
        state['sources'][slot]['schedule'] = {'automation_id': automation_id, 'times': times, 'configured_at': now().isoformat(timespec='seconds')}
    return {'slot': slot, 'schedule_recorded': True}


def sync_deadline(source, current):
    """A check before a scheduled occurrence cannot satisfy that occurrence.

    Ten minutes allows the source read/import to finish. Configuration is not
    evidence of a run; do not require occurrences before initial configuration.
    """
    schedule = source.get('schedule')
    if not schedule:
        return None
    try:
        configured = datetime.fromisoformat(schedule['configured_at'])
        if configured.tzinfo is None:
            raise ValueError()
        due = []
        for day in (current.date() - timedelta(days=1), current.date()):
            for value in schedule['times']:
                occurrence = datetime.combine(day, time.fromisoformat(value), TZ)
                if configured <= occurrence <= current - timedelta(minutes=10):
                    due.append(occurrence)
        return max(due) if due else None
    except (KeyError, TypeError, ValueError) as exc:
        raise BriefError('同步计划时间无效，请检查本地配置') from exc


def day_view(day=None):
    current = now()
    selected = valid_day(day) if day else current.date()
    state = read_state()
    slots = []
    for slot, (label, expected) in SLOTS.items():
        source = copy.deepcopy(state['sources'].get(slot, {}))
        record = state['records'].get(selected.isoformat() + '/' + slot)
        dates = sorted((r['date'] for r in state['records'].values() if r['slot'] == slot), reverse=True)
        due = datetime.combine(selected, time.fromisoformat(expected), TZ)
        status = 'available' if record else ('not_configured' if not source else ('pending' if current < due else 'missing'))
        checked = source.get('last_checked_at')
        checked_at = datetime.fromisoformat(checked).astimezone(TZ) if checked else None
        required = sync_deadline(source, current)
        overdue = bool(required and (not checked_at or checked_at < required))
        slots.append({'slot': slot, 'label': label, 'expected_at': due.isoformat(), 'status': status,
                      'source': source, 'record': record, 'latest_date': dates[0] if dates else None,
                      'sync_due_at': required.isoformat() if required else None,
                      'sync_grace_minutes': 10, 'sync_overdue': overdue})
    return {'date': selected.isoformat(), 'today': current.date().isoformat(), 'timezone': 'Asia/Shanghai',
            'read_at': current.isoformat(timespec='seconds'), 'slots': slots,
            'dates': sorted({r['date'] for r in state['records'].values()}, reverse=True)}
