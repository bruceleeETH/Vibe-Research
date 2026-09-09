"""Fixed nearest-neighbour research estimates, released only after temporal validation."""
import fcntl
import hashlib
import json
import math
import threading
import uuid
from collections import Counter
from datetime import datetime, timedelta

import numpy as np
from fastapi import APIRouter, HTTPException
import limitup as seeds
import limitup_outcomes as outcomes

router = APIRouter(prefix='/api/market/limit-up-predictions', tags=['limit-up'])
VERSION = 'neighbours-1.0'
POLICY = {'mature_days': 60, 'train_days': 30, 'train_rows': 300, 'validation_days': 20,
          'validation_rows': 200, 'neighbours': 80, 'neighbour_days': 10, 'class_count': 20,
          'max_label_age_days': 30, 'max_per_day': 8, 'train_lookback_days': 120, 'min_features': 4,
          'brier_improvement': .02, 'max_ece': .10, 'min_coverage': .75, 'max_coverage': .95}
TARGETS = {'up': '收盘上涨', 'touched': '盘中触板', 'promoted': '连板晋级', 'open_pct': '开盘涨幅区间', 'close_pct': '收盘涨幅区间'}
FEATURES = ['首次封板', '最后封板', '开板次数', '换手率', '封板资金/成交额', '流通市值']
_guard = threading.Lock()
_job = {'running': False, 'date': None, 'message': ''}


def stamp(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None: raise ValueError('采集时间缺少时区')
    return dt.astimezone(seeds.TZ)


def deadline(day):
    return datetime.fromisoformat(day).replace(tzinfo=seeds.TZ, hour=9, minute=15) + timedelta(days=1)


def close_time(day):
    return datetime.fromisoformat(day).replace(tzinfo=seeds.TZ, hour=15, minute=10)


def tier(stock):
    n = seeds.integer(stock.get('boards'), 1)
    return '未知' if n is None else '四板及以上' if n >= 4 else ['首板', '二板', '三板'][n-1]


def group(stock):
    # ST/non-ST must not share a market-limit regime.
    return f"{stock.get('market', '未知')} / {tier(stock)}" + (' / ST' if stock.get('is_st') else '')


def features(s):
    def minute(v):
        try:
            t = datetime.strptime(v, '%H:%M:%S')
            return t.hour * 60 + t.minute + t.second / 60
        except (ValueError, TypeError): return None
    amount = seeds.number(s.get('amount')); seal = seeds.number(s.get('seal_amount')); cap = seeds.number(s.get('float_cap'))
    return [minute(s.get('first_seal')), minute(s.get('last_seal')), seeds.number(s.get('breaks')),
            seeds.number(s.get('turnover')), seal / amount if seal is not None and amount and amount > 0 else None,
            math.log(cap) if cap and cap > 0 else None]


def observations(s):
    positive = []; risks = []; x = features(s)
    if x[0] is not None: positive.append(f"首次封板 {s['first_seal']}（描述事实，不预设早封板必然有效）")
    if x[2] == 0: positive.append('来源记录当日未开板')
    elif x[2] is not None: risks.append(f"当日开板 {int(x[2])} 次，存在反复封板")
    if s.get('boards') and s['boards'] >= 4: risks.append(f"已连续 {s['boards']} 板，需单独检验高位样本")
    if x[4] is not None: positive.append(f'封板资金/成交额 {x[4] * 100:.2f}%（采样值）')
    missing = [name for name, v in zip(FEATURES, x) if v is None]
    missing += ['未接入可靠题材/涨停原因、公告催化、竞价及分钟路径']
    return {'observations': positive, 'risks': risks, 'missing': missing, 'feature_count': sum(v is not None for v in x)}


def dataset(as_of):
    rows = []; skipped = Counter(); archived = 0
    for path in sorted(seeds.directory().glob('????-??-??.json')):
        archived += 1
        try:
            seed = seeds.read_saved(path)
            if seed['phase'] != 'after_close' or seed['coverage'] != 'source_complete':
                skipped['盘中或不完整'] += 1; continue
            captured = stamp(seed['captured_at'])
            if captured < close_time(seed['date']) or captured > deadline(seed['date']):
                skipped['样本采集超出研究时窗'] += 1; continue
            if captured > as_of:
                skipped['截至生成时尚不可用'] += 1; continue
            result = outcomes.read_result(path.stem)
            if result['state'] not in ('complete', 'partial'):
                skipped['次日结果尚未成熟或已失效'] += 1; continue
            target = result.get('target_date')
            if not target or target <= seed['date']:
                skipped['次日日期无效'] += 1; continue
            available = max(stamp(result.get('available_at') or result['captured_at']), close_time(target))
            if available > as_of:
                skipped['标签晚于生成时间'] += 1; continue
            labels = {r['code']: r for r in result['rows']}
            if len(labels) != len(result['rows']):
                skipped['重复标签代码'] += 1; continue
            codes = set()
            for s in seed['stocks']:
                if s['code'] in codes: raise ValueError('重复样本代码')
                codes.add(s['code'])
            candidates = []
            for s in seed['stocks']:
                r = labels.get(s['code']); x = features(s)
                if not r or sum(v is not None for v in x) < POLICY['min_features']: continue
                y = {k: outcomes.finite(r.get(k)) for k in ('open_pct', 'close_pct')}
                y['up'] = int(y['close_pct'] > 0) if y['close_pct'] is not None else None
                y.update({k: int(r[k]) if isinstance(r.get(k), bool) else None for k in ('touched', 'promoted')})
                if all(v is None for v in y.values()): continue
                candidates.append({'date': seed['date'], 'code': s['code'], 'group': group(s), 'x': x, 'y': y,
                             'available_at': available.isoformat(), 'feature_available_at': captured.isoformat(),
                             'target_date': target, 'seed_hash': outcomes.fingerprint(seed)})
            rows.extend(candidates)
        except (ValueError, TypeError, KeyError, OSError, HTTPException):
            skipped['存档损坏或字段不完整'] += 1
    return rows, {'archived_days': archived, 'mature_days': len({r['date'] for r in rows}), 'rows': len(rows), 'excluded': dict(skipped)}


def training_before(rows, day, cutoff):
    eligible = [r for r in rows if r['date'] < day and stamp(r['available_at']) <= cutoff and stamp(r['feature_available_at']) <= cutoff]
    days = sorted({r['date'] for r in eligible})[-POLICY['train_lookback_days']:]
    return [r for r in eligible if r['date'] in set(days)]


class Neighbours:
    def __init__(self, rows, target):
        self.rows = [r for r in rows if r['y'][target] is not None]
        self.binary = target in ('up', 'touched', 'promoted')
        self.ready = len(self.rows) >= POLICY['train_rows'] and len({r['date'] for r in self.rows}) >= POLICY['train_days']
        if not self.ready: return
        self.y = np.array([r['y'][target] for r in self.rows], dtype=float)
        raw = np.array([[np.nan if v is None else v for v in r['x']] for r in self.rows])
        # Columns entirely missing remain neutral; no validation data used for imputation.
        self.median = np.array([np.median(c[np.isfinite(c)]) if np.isfinite(c).any() else 0 for c in raw.T])
        self.missing = ~np.isfinite(raw)
        clean = np.where(self.missing, self.median, raw)
        self.scale = np.std(clean, axis=0); self.scale[self.scale < 1e-8] = 1
        self.x = (clean - self.median) / self.scale
        self.low = clean.min(axis=0) - self.scale; self.high = clean.max(axis=0) + self.scale
        self.baseline = self.estimate(self.y)

    def estimate(self, y):
        return float((y.sum() + 1) / (len(y) + 2)) if self.binary else [float(v) for v in np.quantile(y, [.1, .9])]

    def predict(self, x):
        if not self.ready or sum(v is not None for v in x) < POLICY['min_features']: return None
        raw = np.array([np.nan if v is None else v for v in x]); missing = ~np.isfinite(raw)
        clean = np.where(missing, self.median, raw)
        if int(((clean < self.low) | (clean > self.high)).sum()) >= 2: return None
        distances = (((clean-self.median)/self.scale - self.x)**2).sum(axis=1) + (self.missing != missing).sum(axis=1)
        indices = []; per_day = Counter()
        for i in np.argsort(distances, kind='stable'):
            day = self.rows[int(i)]['date']
            if per_day[day] >= POLICY['max_per_day']: continue
            per_day[day] += 1; indices.append(int(i))
            if len(indices) == POLICY['neighbours']: break
        if len(indices) < POLICY['neighbours']: return None
        neighbours = [self.rows[int(i)] for i in indices]
        days = len({r['date'] for r in neighbours})
        if days < POLICY['neighbour_days']: return None
        return {'value': self.estimate(self.y[indices]), 'n': len(indices), 'days': days,
                'examples': [{'date': r['date'], 'code': r['code']} for r in neighbours],
                'baseline': self.baseline}


def interval_score(y, value):
    lo, hi = value
    return hi-lo + 10 * max(lo-y, 0) + 10 * max(y-hi, 0)


def assess(points, binary, total_days):
    reasons = []; n = len(points); days = sorted({p['date'] for p in points})
    report = {'passed': False, 'n': n, 'days': len(days), 'mature_days': total_days, 'reasons': reasons}
    if total_days < POLICY['mature_days']: reasons.append(f"成熟样本日 {total_days}/{POLICY['mature_days']}")
    if len(days) < POLICY['validation_days']: reasons.append(f"有效时间验证日 {len(days)}/{POLICY['validation_days']}")
    if n < POLICY['validation_rows']: reasons.append(f"有效验证记录 {n}/{POLICY['validation_rows']}")
    if not points: return report
    if binary:
        pos = sum(p['y'] for p in points); report.update(positive=pos, negative=n-pos)
        if min(pos, n-pos) < POLICY['class_count']: reasons.append('验证正负例各需至少 20 条')
        score = sum((p['value']-p['y'])**2 for p in points) / n
        baseline = sum((p['baseline']-p['y'])**2 for p in points) / n
        ece = 0; bins = []
        for i in range(5):
            selected = [p for p in points if min(4, int(p['value']*5)) == i]
            if selected:
                predicted = sum(p['value'] for p in selected)/len(selected); actual = sum(p['y'] for p in selected)/len(selected)
                ece += abs(predicted-actual)*len(selected)/n
                bins.append({'from': i/5, 'to': (i+1)/5, 'n': len(selected), 'predicted': predicted, 'actual': actual})
        report.update(score=score, baseline_score=baseline, ece=ece, calibration=bins)
        if baseline <= 0 or score > baseline*(1-POLICY['brier_improvement']): reasons.append('Brier 误差未比同梯队基准降低 2%')
        if ece > POLICY['max_ece']: reasons.append('概率校准误差超过 0.10')
        halves = [set(days[:len(days)//2]), set(days[len(days)//2:])]
        for index, ds in enumerate(halves):
            part = [p for p in points if p['date'] in ds]
            if part and sum((p['value']-p['y'])**2 for p in part) > sum((p['baseline']-p['y'])**2 for p in part): reasons.append(f'时间验证第 {index+1} 段未优于基准')
    else:
        coverage = sum(p['value'][0] <= p['y'] <= p['value'][1] for p in points)/n
        score = sum(interval_score(p['y'],p['value']) for p in points)/n
        baseline = sum(interval_score(p['y'],p['baseline']) for p in points)/n
        report.update(coverage=coverage, score=score, baseline_score=baseline)
        if not POLICY['min_coverage'] <= coverage <= POLICY['max_coverage']: reasons.append('80% 区间的实测覆盖不在 75%～95% 范围')
        if score >= baseline: reasons.append('区间评分未优于同梯队基准')
    report['passed'] = not reasons
    report['window'] = [days[0], days[-1]] if days else []
    return report


def validate(rows, progress=lambda _: None):
    reports = {}
    for key in sorted({r['group'] for r in rows}):
        subset = [r for r in rows if r['group'] == key]
        days = sorted({r['date'] for r in subset}); targets = {}
        for target in TARGETS:
            points = []
            if len(days) >= POLICY['mature_days']:
                for day in days[-POLICY['validation_days']:]:
                    model = Neighbours(training_before(subset, day, deadline(day)), target)
                    for r in (r for r in subset if r['date'] == day and r['y'][target] is not None):
                        p = model.predict(r['x'])
                        if p: points.append({'date': day, 'code': r['code'], 'y': r['y'][target], 'value': p['value'], 'baseline': p['baseline']})
            targets[target] = assess(points, target in ('up','touched','promoted'), len(days)) | {'points': points}
            progress(f"正在验证 {key} · {TARGETS[target]}")
        reports[key] = targets
    return reports


def root(day):
    outcomes.seed_for(day)  # validate before path use
    return seeds.directory().parent / 'predictions' / day


def latest(day):
    files = sorted(root(day).glob('*.json'), reverse=True)
    if not files: return None
    try:
        return json.loads(files[0].read_text())
    except (ValueError, OSError): raise HTTPException(500, '预测留档不可读，未覆盖原记录')


def public_snapshot(value):
    if not value: return None
    clean = {k:v for k,v in value.items() if k != 'training_snapshot'}
    clean['reports'] = {g: {t: {k:v for k,v in r.items() if k != 'points'} for t,r in rs.items()} for g,rs in value['reports'].items()}
    return clean


def build(day, progress=lambda _: None):
    seed = outcomes.seed_for(day); now = seeds.now()
    rows, readiness = dataset(now)
    # Do not include selected day outcomes, even when generating a retrospective diagnostic.
    train = training_before(rows, day, now)
    reports = validate(train, progress)
    prospective = seed['phase'] == 'after_close' and seed['coverage'] == 'source_complete' and close_time(day) <= now <= deadline(day)
    prospective = prospective and close_time(day) <= stamp(seed['captured_at']) <= now
    items = []
    models = {}
    for s in seed['stocks']:
        key = group(s); estimates = {}
        group_rows = [r for r in train if r['group'] == key]
        recent = bool(group_rows and (close_time(day) - close_time(max(r['target_date'] for r in group_rows))).days <= POLICY['max_label_age_days'])
        for t in TARGETS:
            report = reports.get(key, {}).get(t)
            reason = '样本不足，尚未完成时间验证'
            if not prospective: reason = '不在盘后研究时窗，或样本并非完整盘后记录'
            elif report and not report['passed']: reason = '；'.join(report['reasons'])
            elif report and report['passed'] and not recent: reason = '同组最新结果已超过 30 天，暂停使用过期样本估计'
            elif report and report['passed']:
                if (key,t) not in models: models[key,t] = Neighbours([r for r in train if r['group'] == key],t)
                p = models[key,t].predict(features(s))
                if p:
                    estimates[t] = p | {'reason': '', 'validated': True}; continue
                reason = '有效特征或跨日相似样本不足，或超出训练范围'
            estimates[t] = {'value': None, 'reason': reason, 'validated': False}
        if all(estimates[t]['value'] is not None for t in ('promoted', 'touched')) and estimates['promoted']['value'] > estimates['touched']['value']:
            estimates['promoted'] = {'value': None, 'reason': '晋级与触板的独立估计不一致，暂停展示晋级概率', 'validated': False}
        items.append({k:s.get(k) for k in ('code','name','boards','market')} | {'group':key, 'features':features(s), **observations(s), 'estimates': estimates})
    finished = seeds.now()
    if finished > deadline(day):
        prospective = False
        for item in items:
            for estimate in item['estimates'].values():
                estimate.update(value=None, validated=False, reason='生成完成时已超过研究时窗，仅保存检查记录')
    serialized = json.dumps(train,sort_keys=True,ensure_ascii=False,allow_nan=False)
    value = {'id': finished.strftime('%Y%m%dT%H%M%S%f')+'-'+uuid.uuid4().hex[:8], 'date':day,
             'version':VERSION, 'policy':POLICY, 'seed_hash':outcomes.fingerprint(seed), 'generated_at':finished.isoformat(), 'training_as_of':now.isoformat(),
             'feature_cutoff': close_time(day).replace(minute=0).isoformat(), 'available_at':seed['captured_at'],
             'deadline':deadline(day).isoformat(), 'prospective':prospective, 'readiness':readiness,
             'training_rows':len(train), 'training_days':len({r['date'] for r in train}),
             'dataset_hash':hashlib.sha256(serialized.encode()).hexdigest(), 'training_snapshot':train,
             'reports':reports, 'rows':items}
    directory = root(day); directory.mkdir(parents=True,exist_ok=True)
    seeds.atomic_save(directory / (value['id']+'.json'), value)
    return value


@router.get('/day')
def view(date: str):
    seed = outcomes.seed_for(date); value = latest(date)
    stale = bool(value and value['seed_hash'] != outcomes.fingerprint(seed))
    actual = outcomes.read_result(date)
    comparison = {r['code']:r for r in actual['rows']} if value and not stale else {}
    with _guard: job = dict(_job)
    return {'date':date, 'snapshot':public_snapshot(value) if not stale else None, 'stale':stale, 'job':job,
            'actual':comparison, 'actual_date':actual.get('target_date'), 'policy':POLICY,
            'archive_count':len(list(seeds.directory().glob('????-??-??.json'))),
            'history': [{'id': p.stem} for p in sorted(root(date).glob('*.json'),reverse=True)],
            'observations': [{k:s.get(k) for k in ('code','name','boards','market')} | {'group':group(s), **observations(s)} for s in seed['stocks']]}


@router.get('/record')
def record(date: str, id: str):
    if not id or any(c not in '0123456789Tabcdef-' for c in id) or len(id) > 80:
        raise HTTPException(400, '无效留档标识')
    path = root(date) / (id+'.json')
    if not path.exists(): raise HTTPException(404, '留档不存在')
    return public_snapshot(json.loads(path.read_text()))


def run(day):
    def progress(message):
        with _guard: _job['message'] = message
    try:
        directory = seeds.directory().parent / 'predictions'; directory.mkdir(parents=True, exist_ok=True)
        with (directory / 'worker.lock').open('a') as lock:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                progress('其他进程正在验证，请稍后重试'); return
            build(day, progress); progress('本地验证和留档完成')
    except Exception:
        progress('验证失败，未覆盖已有留档，请检查数据后重试')
    finally:
        with _guard: _job['running'] = False


@router.post('/day')
def start(date: str):
    outcomes.seed_for(date)
    with _guard:
        if _job['running']:
            if _job['date'] != date: raise HTTPException(409,'其他日期正在验证，请完成后再试')
        else:
            _job.update(running=True, date=date, message='正在检查历史样本与时间口径')
            threading.Thread(target=run,args=(date,),daemon=True).start()
    return {'started':True}
