"""Dated limit-up observations. Source-pool coverage, not an asserted all-market universe."""
from __future__ import annotations

import fcntl
import json
import logging
import math
import os
import re
import tempfile
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
import astock

TZ = ZoneInfo('Asia/Shanghai')
router = APIRouter(prefix='/api/market/limit-up', tags=['limit-up'])
SCOPE = '东方财富涨停池；已校验来源内条数，尚未与全市场逐只核对，ST/北交所等覆盖不作保证。行业不是涨停原因。'


def now():
    return datetime.now(TZ)


def directory():
    return Path(os.environ.get('VR_DATA_DIR', str(Path.home() / '.vibe-research'))) / 'limit-nextday' / 'daily'


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def integer(value, minimum=0):
    n = number(value)
    return int(n) if n is not None and n.is_integer() and n >= minimum else None


def clock(value):
    n = integer(value)
    if n is None:
        return None
    s = str(n).zfill(6)
    try:
        return datetime.strptime(s, '%H%M%S').strftime('%H:%M:%S') if len(s) == 6 else None
    except ValueError:
        return None


def normalize(row):
    code = str(row.get('c', ''))
    if not re.fullmatch(r'\d{6}', code):
        raise ValueError('来源包含无效证券代码')
    price = number(row.get('p'))
    return {'code': code, 'name': str(row.get('n') or ''), 'boards': integer(row.get('lbc'), 1),
            'price': round(price / 1000, 3) if price is not None else None,
            'pct': number(row.get('zdp')), 'amount': number(row.get('amount')),
            'float_cap': number(row.get('ltsz')), 'turnover': number(row.get('hs')),
            'seal_amount': number(row.get('fund')), 'first_seal': clock(row.get('fbt')),
            'last_seal': clock(row.get('lbt')), 'breaks': integer(row.get('zbc')),
            'industry': str(row.get('hybk') or ''),
            'market': '科创板' if code.startswith('688') else '创业板' if code.startswith(('300', '301')) else '北交所' if code.startswith(('4', '8', '92')) else '沪深主板',
            'is_st': 'ST' in str(row.get('n', '')).upper()}


def fetch_day(day):
    compact = day.replace('-', '')
    response = astock.em_get('https://push2ex.eastmoney.com/getTopicZTPool',
                            params={'ut': astock._ZTB_UT, 'dpt': 'wz.ztzt', 'Pageindex': 0,
                                    'pagesize': 10000, 'sort': 'fbt:asc', 'date': compact},
                            headers={'User-Agent': astock.UA, 'Referer': 'https://quote.eastmoney.com/'}, timeout=10)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get('rc') != 0:
        raise ValueError('来源接口返回错误')
    data = payload.get('data')
    if not isinstance(data, dict) or str(data.get('qdate')) != compact:
        raise ValueError('来源未返回所选日期数据；可能尚未发布、非交易日或超出可查询范围')
    pool = data.get('pool')
    if not isinstance(pool, list) or not pool:
        raise ValueError('来源返回空池，未确认是零涨停还是缺失；不生成空样本')
    if any(not isinstance(row, dict) for row in pool):
        raise ValueError('来源记录格式错误')
    stocks = [normalize(row) for row in pool]
    if len({s['code'] for s in stocks}) != len(stocks):
        raise ValueError('来源含重复代码，未保存样本')
    expected = integer(data.get('tc'))
    complete = expected is not None and len(stocks) == expected
    stamp = now()
    missing = {field: sum(s[field] is None for s in stocks) for field in ('boards', 'price', 'first_seal', 'last_seal', 'breaks', 'seal_amount', 'turnover')}
    return {'date': day, 'source': '东方财富 getTopicZTPool', 'source_date': day,
            'captured_at': stamp.isoformat(), 'expected_count': expected, 'count': len(stocks),
            'coverage': 'source_complete' if complete else 'partial', 'scope': SCOPE,
            'phase': 'after_close' if day < stamp.date().isoformat() or stamp.hour * 60 + stamp.minute >= 15 * 60 + 10 else 'intraday',
            'missing_fields': missing, 'stocks': stocks, 'raw': payload, 'schema_version': 1}


def read_saved(path):
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
        if value['date'] != path.stem or not isinstance(value['stocks'], list) or value['schema_version'] != 1:
            raise ValueError()
        return value
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise HTTPException(500, '本地该日样本损坏或不可读，未覆盖；请检查文件') from exc


def atomic_save(path, value):
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as f:
        temp = f.name
        try:
            json.dump(value, f, ensure_ascii=False, allow_nan=False)
            f.flush(); os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)


def public(value, origin, warning=''):
    return {k: v for k, v in value.items() if k != 'raw'} | {'origin': origin, 'warning': warning}


def get_day(day, refresh=False):
    try:
        parsed = date.fromisoformat(day)
        if parsed.isoformat() != day or parsed > now().date():
            raise ValueError()
    except ValueError:
        raise HTTPException(400, '请选择有效日期，不能晚于北京时间今天')
    root = directory(); root.mkdir(parents=True, exist_ok=True)
    path = root / f'{day}.json'
    with (root / f'{day}.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        saved = read_saved(path)
        if saved and not refresh:
            age = (now() - datetime.fromisoformat(saved['captured_at'])).total_seconds()
            if (saved['phase'] == 'after_close' and saved['coverage'] == 'source_complete') or age < 300:
                return public(saved, 'local')
        try:
            value = fetch_day(day)
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else '公开数据源请求失败，请稍后重试'
            if saved:
                return public(saved, 'local', f'刷新失败：{message}。显示已保存样本，采样时间见下方。')
            raise HTTPException(502, message) from exc
        if saved and saved['coverage'] == 'source_complete' and value['coverage'] != 'source_complete':
            return public(saved, 'local', '本次来源条数不完整，保留上次完整样本。')
        if saved and saved['phase'] == 'after_close' and value['phase'] != 'after_close':
            return public(saved, 'local', '保留已有盘后样本。')
        try:
            atomic_save(path, value)
        except OSError as exc:
            raise HTTPException(500, '已取得来源数据，但本地样本保存失败，请检查磁盘与权限') from exc
        return public(value, 'source', '' if value['coverage'] == 'source_complete' else '来源总条数与收到条数不一致，当前为部分样本。')


@router.get('/dates')
def saved_dates():
    return {'dates': sorted([p.stem for p in directory().glob('????-??-??.json')], reverse=True)}


@router.get('')
def limit_up(date: str, refresh: bool = False):
    return get_day(date, refresh)


def start_scheduler():
    """Archive while the local service is running; never claim offline collection."""
    def loop():
        while True:
            stamp = now()
            if stamp.weekday() < 5 and stamp.hour * 60 + stamp.minute >= 15 * 60 + 10:
                try:
                    get_day(stamp.date().isoformat())
                except Exception:
                    logging.getLogger(__name__).warning('Daily limit-up capture unavailable; will retry', exc_info=False)
            threading.Event().wait(600)
    threading.Thread(target=loop, daemon=True, name='limit-up-archive').start()
