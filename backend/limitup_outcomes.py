"""Observed T+1 outcomes; missing observations never become negative labels."""
import fcntl
import hashlib
import json
import math
import threading
from datetime import date, timedelta
import requests
from fastapi import APIRouter, HTTPException
import astock
import limitup as seeds

router = APIRouter(prefix='/api/market/limit-up-outcomes', tags=['limit-up'])
_guard = threading.Lock()
_jobs = {}


def finite(v):
    try:
        return float(v) if not isinstance(v, bool) and math.isfinite(float(v)) else None
    except (TypeError, ValueError):
        return None


def fingerprint(seed):
    return hashlib.sha256(json.dumps({k: seed[k] for k in ('date', 'phase', 'coverage', 'stocks')}, sort_keys=True).encode()).hexdigest()


def seed_for(day):
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError()
    except ValueError:
        raise HTTPException(400, '无效样本日期')
    seed = seeds.read_saved(seeds.directory() / f'{day}.json')
    if not seed:
        raise HTTPException(404, '请先采集该日涨停样本')
    return seed


def path_for(day):
    root = seeds.directory().parent / 'outcomes'
    root.mkdir(parents=True, exist_ok=True)
    return root / f'{day}.json'


def bars(symbol, day):
    end = min(date.fromisoformat(day) + timedelta(days=40), seeds.now().date()).isoformat()
    r = requests.get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get', params={'param': f'{symbol},day,{day},{end},60,'}, timeout=12)
    r.raise_for_status()
    payload = r.json()
    rows = payload.get('data', {}).get(symbol, {}).get('day')
    if payload.get('code') != 0 or not isinstance(rows, list):
        raise ValueError('不复权日线缺失')
    return rows


def next_session(day, rows):
    dates = sorted({r[0] for r in rows if isinstance(r, list) and len(r) >= 6 and (finite(r[5]) or 0) > 0})
    if day not in dates:
        raise ValueError('指数交易日数据未覆盖样本日')
    return next((d for d in dates if d > day), None)


def pool(endpoint, day):
    r = astock.em_get('https://push2ex.eastmoney.com/' + endpoint, params={'ut': astock._ZTB_UT, 'dpt': 'wz.ztzt', 'Pageindex': 0, 'pagesize': 10000, 'sort': 'zs:desc' if endpoint == 'getYesterdayZTPool' else 'fbt:asc', 'date': day.replace('-', '')}, timeout=10)
    r.raise_for_status()
    payload = r.json(); data = payload.get('data') or {}; rows = data.get('pool')
    if payload.get('rc') != 0 or str(data.get('qdate')) != day.replace('-', '') or not isinstance(rows, list):
        raise ValueError('来源日期不匹配或数据缺失')
    mapped = {str(r['c']): r for r in rows}
    if len(mapped) != len(rows) or seeds.integer(data.get('tc')) != len(rows):
        raise ValueError('来源条数不完整')
    return mapped, payload


def classify(stock, target, rows, yesterday, sealed, broken):
    out = {k: stock.get(k) for k in ('code', 'name', 'boards', 'market')}
    out.update(close_pct=None, open_pct=None, high_pct=None, touched=None, promoted=None, reason='次日日线或昨日涨停池记录缺失')
    bar = next((r for r in rows if r[0] == target), None)
    old = yesterday.get(stock['code']) if yesterday is not None else None
    if not bar or len(bar) < 6 or (finite(bar[5]) or 0) <= 0 or not old or (finite(old.get('amount')) or 0) <= 0:
        return out
    opening, close, high = map(finite, bar[1:4])
    price = finite(old.get('p'))
    if not all(v is not None and v > 0 for v in (opening, close, high, price)) or abs(close - price / 1000) > .011:
        out['reason'] = '日线与涨停来源价格不一致'; return out
    out['close_pct'] = finite(old.get('zdp'))
    base = finite(stock.get('price'))
    if base and out['close_pct'] is not None and abs((close / base - 1) * 100 - out['close_pct']) < .06:
        out.update(open_pct=(opening / base - 1) * 100, high_pct=(high / base - 1) * 100)
    code = stock['code']
    if sealed is not None:
        if code not in sealed:
            out['promoted'] = False
        elif stock.get('boards') is not None and seeds.integer(sealed[code].get('lbc'), 1) == stock['boards'] + 1:
            out['promoted'] = True
    if (sealed is not None and code in sealed) or (broken is not None and code in broken):
        out['touched'] = True
    elif sealed is not None and broken is not None:
        out['touched'] = False
    out['reason'] = '已核对' if all(out[k] is not None for k in ('close_pct', 'open_pct', 'high_pct', 'touched', 'promoted')) else '部分字段待确认（来源缺失、连板数或除权参考价变化）'
    return out


def read_result(day):
    seed = seed_for(day); path = path_for(day)
    if path.exists():
        try:
            value = json.loads(path.read_text())
        except (ValueError, OSError):
            raise HTTPException(500, '次日结果存档损坏，请检查文件')
        if value.get('seed_hash') == fingerprint(seed):
            return value
    return {'date': day, 'state': 'idle', 'rows': [], 'message': '尚未补齐次日结果，点击开始核对。'}


def _process(day):
    seed = seed_for(day)
    value = {'date': day, 'seed_hash': fingerprint(seed), 'state': 'running', 'rows': [], 'total': len(seed['stocks']), 'completed': 0, 'target_date': None, 'captured_at': seeds.now().isoformat(), 'sources': {}, 'raw': {}}
    previous = read_result(day)
    def save():
        destination = path_for(day).with_suffix('.progress') if value['state'] == 'running' else path_for(day)
        if value['state'] != 'running' and previous['state'] == 'complete' and value['state'] != 'complete':
            previous['message'] = '本次重试未取得完整结果，保留上次完整核对记录。'
            seeds.atomic_save(destination, previous)
        else:
            seeds.atomic_save(destination, value)
    try:
        if seed['phase'] != 'after_close' or seed['coverage'] != 'source_complete':
            value.update(state='pending', message='需要完整盘后样本；请先重新采集样本日。'); save(); return
        calendar = bars('sh000001', day); value['raw']['calendar'] = calendar
        target = next_session(day, calendar); value['target_date'] = target
        now = seeds.now()
        if not target or target > now.date().isoformat() or target == now.date().isoformat() and now.hour * 60 + now.minute < 910:
            value.update(state='pending', message='等待下一交易日收盘及数据发布；未按自然日推算。'); save(); return
        save(); pools = []
        for endpoint in ('getYesterdayZTPool', 'getTopicZTPool', 'getTopicZBPool'):
            try:
                mapped, raw = pool(endpoint, target); pools.append(mapped)
                value['raw'][endpoint] = raw; value['sources'][endpoint] = '日期及条数已核对'
            except Exception:
                pools.append(None); value['sources'][endpoint] = '缺失或不完整，相关结论待确认'
        for stock in seed['stocks']:
            try:
                rows = bars(astock.get_prefix(stock['code']) + stock['code'], day)
            except Exception:
                rows = []
            value['raw'][stock['code']] = rows
            value['rows'].append(classify(stock, target, rows, *pools))
            value['completed'] += 1; save()
        complete = all(all(r[k] is not None for k in ('close_pct', 'touched', 'promoted')) for r in value['rows'])
        value.update(state='complete' if complete else 'partial', message='核对完成；统计仅使用各字段的有效样本。' if complete else '部分结果缺失，可重试；缺失项不计入对应分母。')
    except Exception:
        value.update(state='error', message='来源请求失败或交易日无法确认，请稍后重试。')
    finally:
        value['available_at'] = seeds.now().isoformat()
        save()


def process(day):
    try:
        with path_for(day).with_suffix('.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            _process(day)
    finally:
        with _guard:
            _jobs.pop(day, None)


@router.get('/day')
def get_result(date: str):
    value = read_result(date)
    with _guard:
        running = date in _jobs
    progress = path_for(date).with_suffix('.progress')
    if running and progress.exists():
        candidate = json.loads(progress.read_text())
        if candidate.get('seed_hash') == fingerprint(seed_for(date)):
            value = candidate
    if value['state'] == 'running' and not running:
        value = value | {'state': 'partial', 'message': '上次任务中断，可重试补齐。'}
    return {k: v for k, v in value.items() if k != 'raw'} | {'running': running}


@router.post('/day')
def start(date: str):
    seed_for(date)
    with _guard:
        if date not in _jobs:
            if _jobs:
                raise HTTPException(409, '已有日期正在核对，请完成后再开始')
            _jobs[date] = True
            threading.Thread(target=process, args=(date,), daemon=True).start()
    return {'started': True}


@router.get('/stats')
def statistics(start: str = '', end: str = '', market: str = ''):
    for value in (start, end):
        if value:
            try:
                if date.fromisoformat(value).isoformat() != value: raise ValueError()
            except ValueError:
                raise HTTPException(400, '统计日期格式无效')
    if start and end and start > end:
        raise HTTPException(400, '开始日期不能晚于结束日期')
    groups = {}; included = []; excluded = []
    for path in sorted(seeds.directory().glob('????-??-??.json')):
        if start and path.stem < start or end and path.stem > end:
            continue
        seed = seed_for(path.stem); result = read_result(path.stem)
        if seed['phase'] != 'after_close' or seed['coverage'] != 'source_complete' or result['state'] in ('idle', 'pending', 'error', 'running'):
            excluded.append(path.stem); continue
        included.append(path.stem)
        for row in result['rows']:
            if market and row['market'] != market: continue
            n = row['boards']; tier = '未知' if n is None else '四板及以上' if n >= 4 else ['首板', '二板', '三板'][n-1]
            key = (row['market'], tier)
            g = groups.setdefault(key, {'market': key[0], 'tier': tier, 'total': 0, 'up': 0, 'returns_n': 0, 'touched': 0, 'touch_n': 0, 'promoted': 0, 'promotion_n': 0})
            g['total'] += 1
            if row['close_pct'] is not None:
                g['returns_n'] += 1; g['up'] += int(row['close_pct'] > 0)
            for field, denom in (('touched', 'touch_n'), ('promoted', 'promotion_n')):
                if row[field] is not None:
                    g[denom] += 1; g[field] += int(row[field])
    return {'groups': list(groups.values()), 'included_dates': included, 'excluded_dates': excluded, 'scope': '按来源样本、市场及样本日梯队分组；上涨为次日收盘涨幅大于 0；触板含炸板；晋级要求次日封板且连板数增加 1。历史频率不是个股预测概率。'}


def start_scheduler():
    """Only stored cohorts; retries while the local service is running."""
    def loop():
        while True:
            stamp = seeds.now()
            if stamp.hour * 60 + stamp.minute >= 910:
                for path in sorted(seeds.directory().glob('????-??-??.json')):
                    try:
                        if path.stem >= stamp.date().isoformat() or read_result(path.stem)['state'] == 'complete':
                            continue
                        with _guard:
                            if _jobs: break
                            _jobs[path.stem] = True
                        process(path.stem)
                    except Exception:
                        continue
            threading.Event().wait(600)
    threading.Thread(target=loop, daemon=True, name='limit-up-outcomes').start()
