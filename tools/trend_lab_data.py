"""Fetch the user's explicit 15-stock observation pool. Public prices only.

Run: python3 tools/trend_lab_data.py
This is NOT a full-mainboard universe and does not verify historical liquidity.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
POOL = {
    '002815': '崇达技术', '000823': '超声电子', '002980': '华盛昌',
    '601869': '长飞光纤', '603936': '博敏电子', '600103': '青山纸业',
    '605058': '澳弘电子', '603386': '骏亚科技', '603083': '剑桥科技',
    '002902': '铭普光磁', '603328': '依顿电子', '600601': '方正科技',
    '002579': '中京电子', '603228': '景旺电子', '600869': '远东股份',
}


def add_quote_average(bars: list[dict], quote: list) -> str:
    if not bars or not isinstance(quote, list) or len(quote) < 38:
        return 'missing'
    try:
        timestamp = str(quote[30])
        quote_date = f'{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}'
        latest = bars[-1]
        if len(timestamp) != 14 or timestamp[8:12] < '1500' or latest['date'] != quote_date:
            return 'missing'
        shares = float(quote[36]) * 100
        amount = float(quote[37]) * 10000
        if shares <= 0 or amount <= 0 or abs(float(quote[3]) - latest['close']) > 0.001:
            return 'missing'
        if abs(shares / 100 - latest['volume']) > max(1, latest['volume'] * 0.001):
            return 'missing'
        average = amount / shares
        if not latest['low'] - 0.01 <= average <= latest['high'] + 0.01:
            return 'missing'
        latest.update(average=average, amount=amount, average_source='Tencent closing quote amount/volume', average_quote_time=timestamp)
        return 'latest_only'
    except (ValueError, TypeError, ZeroDivisionError):
        return 'missing'


def fetch_stock(code: str, name: str, cutoff: str, raw_dir: Path) -> dict:
    symbol = ('sh' if code.startswith('6') else 'sz') + code
    url = f'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get?param={symbol},day,,,360,qfq'
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode('utf-8')
    (raw_dir / f'{code}.json').write_text(raw, encoding='utf-8')
    payload = json.loads(raw)
    rows = payload.get('data', {}).get(symbol, {}).get('qfqday')
    if payload.get('code') != 0 or not isinstance(rows, list) or len(rows) < 30:
        raise ValueError('有效前复权日线不足，不用未复权数据替代')
    bars = []
    for r in rows:
        if r[0] > cutoff:
            continue
        day, o, c, h, l, v = r[:6]
        bar = dict(date=day, open=float(o), close=float(c), high=float(h), low=float(l), volume=float(v))
        if not (0 < bar['low'] <= min(bar['open'], bar['close']) <= max(bar['open'], bar['close']) <= bar['high'] and bar['volume'] >= 0):
            raise ValueError(f'OHLC 校验失败 {day}')
        bars.append(bar)
    if any(a['date'] >= b['date'] for a, b in zip(bars, bars[1:])):
        raise ValueError('日期重复或顺序错误')
    quote = payload.get('data', {}).get(symbol, {}).get('qt', {}).get(symbol, [])
    amount_status = add_quote_average(bars, quote)
    return dict(code=code, name=name, bars=bars, source_url=url, adjustment='qfq', amount_status=amount_status)


def main() -> None:
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    cutoff_day = now.date() if now.hour >= 16 else now.date() - dt.timedelta(days=1)
    cutoff = cutoff_day.isoformat()
    raw_dir = ROOT / 'data/trend-study' / cutoff / 'raw-tencent'
    raw_dir.mkdir(parents=True, exist_ok=True)
    stocks, errors = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        tasks = {executor.submit(fetch_stock, code, name, cutoff, raw_dir): (code, name) for code, name in POOL.items()}
        for future in concurrent.futures.as_completed(tasks):
            code, name = tasks[future]
            try:
                stock = future.result()
                stocks.append(stock)
                print(code, name, len(stock['bars']), stock['bars'][-1]['date'], flush=True)
            except Exception as exc:
                errors.append(dict(code=code, name=name, error=f'{type(exc).__name__}: {exc}'))
                print(code, 'FAILED', str(exc), flush=True)
    result = dict(version=1, generated_at=now.isoformat(), cutoff=cutoff,
                  start=(cutoff_day - dt.timedelta(days=365)).isoformat(),
                  universe='用户截图主板股票 + 远东股份；事后观察池，非全主板', expected_count=len(POOL),
                  limitations=['仅最新日可从收盘报价补成交均价，历史成交额缺失，1亿元流动性条件未验收', '没有实时板块热度与历史ST/停牌完整状态',
                               '观察池为事后选定，结果仅作研究演示，存在选样偏差', '止损价是理论成交基准，已单列成本与不可交易情况'],
                  stocks=sorted(stocks, key=lambda x: x['code']), errors=errors)
    archive = raw_dir.parent / 'trend-lab-data.json'
    archive.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    if not stocks:
        raise SystemExit('所有数据源失败；保留页面旧数据，不覆盖为成功结果')
    target = ROOT / 'frontend/public/trend-lab-data.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    tmp.replace(target)
    print(f'Published {len(stocks)}/{len(POOL)} to {target}', flush=True)


if __name__ == '__main__':
    main()
