export type Bar = {
  date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  average?: number;
  amount?: number;
  average_source?: string;
  average_adjustment_factor?: number;
};
export type AverageCoverage = {
  added: number;
  rejected: number;
  covered: number;
  total: number;
  status: 'history_complete' | 'history_partial' | 'latest_only' | 'missing';
};
export type Stock = {
  code: string;
  name: string;
  bars: Bar[];
  source_url: string;
  amount_status?: AverageCoverage['status'];
  average_coverage?: AverageCoverage;
  amount_error?: string;
};
export type TrendData = { generated_at: string; cutoff: string; start: string; universe: string; expected_count: number; limitations: string[]; stocks: Stock[]; errors: { code: string; error: string }[] };
export type Options = { volume: number; stop: number; days: number; cost: number; mode: 'day' | 'recent' | 'none'; entryTiming?: 'next-open' | 'signal-close' };
export type Features = { r5: number; r10: number; r20: number; vr: number; ma5: number; ma10: number };
export type Result = { code: string; name: string; signal: string; entryDate?: string; entry?: number; exitDate?: string; exit?: number; net?: number; worst?: number; reason: string; status: 'closed' | 'pending' | 'blocked' | 'no_fill'; features: Features };
const mean = (v: number[]) => v.reduce((a, b) => a + b, 0) / v.length;
const flat = (b: Bar) => b.volume <= 0 || b.high === b.low;

export function reviewDates(data: TrendData): string[] {
  return [...new Set(data.stocks.flatMap(s => s.bars.map(b => b.date)))].filter(d => d >= data.start && d <= data.cutoff).sort();
}

export function dateSnapshot(data: TrendData, date: string, o: Options) {
  const calendar = reviewDates(data), at = calendar.indexOf(date);
  const entryOffset = o.entryTiming === 'signal-close' ? 0 : 1;
  const entryDate = at >= 0 ? calendar[at + entryOffset] : undefined;
  const sellDate = at >= 0 ? calendar[at + entryOffset + 1] : undefined;
  const rows = data.stocks.map(stock => {
    const index = stock.bars.findIndex(b => b.date === date);
    const signal = index >= 0 ? stock.bars[index] : undefined;
    const f = index >= 0 ? features(stock.bars, index) : null;
    const entryIndex = stock.bars.findIndex(b => b.date === entryDate);
    const sellIndex = stock.bars.findIndex(b => b.date === sellDate);
    const entry = entryIndex >= 0 ? stock.bars[entryIndex] : undefined;
    const sell = sellIndex >= 0 ? stock.bars[sellIndex] : undefined;
    return { stock, signal, f, hit: Boolean(signal && f && matches(stock.bars, index, o)), entry, sell,
      entryFeatures: entryIndex >= 0 ? features(stock.bars, entryIndex) : null,
      sellFeatures: sellIndex >= 0 ? features(stock.bars, sellIndex) : null,
      entryUncertain: Boolean(entry && flat(entry)) };
  });
  rows.sort((a, b) => Number(b.hit) - Number(a.hit) || (b.f?.vr ?? 0) - (a.f?.vr ?? 0));
  return { date, isObservedDate: at >= 0, entryDate, sellDate, rows };
}

export function features(bars: Bar[], i: number): Features | null {
  if (i < 20) return null;
  const b = bars[i];
  const v = mean(bars.slice(i - 5, i).map(x => x.volume));
  if (!v || bars[i - 20].close <= 0) return null;
  return { r5: (b.close / bars[i - 5].close - 1) * 100, r10: (b.close / bars[i - 10].close - 1) * 100,
    r20: (b.close / bars[i - 20].close - 1) * 100, vr: b.volume / v,
    ma5: mean(bars.slice(i - 4, i + 1).map(x => x.close)), ma10: mean(bars.slice(i - 9, i + 1).map(x => x.close)) };
}

export function matches(bars: Bar[], i: number, o: Options): boolean {
  const f = features(bars, i);
  if (!f || f.r5 <= 0 || f.r10 <= 0 || flat(bars[i])) return false;
  if (o.mode === 'none') return true;
  if (o.mode === 'day') return f.vr >= o.volume;
  return [i - 2, i - 1, i].some(j => {
    const prev = features(bars, j);
    return prev && prev.vr >= o.volume && bars[j].close > bars[j - 1].close;
  });
}

export function simulate(stock: Stock, i: number, o: Options, calendar: string[]): Result {
  const closeEntry = o.entryTiming === 'signal-close';
  const entryOffset = closeEntry ? 0 : 1;
  const bars = stock.bars, entryIndex = i + entryOffset, end = entryIndex + o.days;
  const result: Result = { code: stock.code, name: stock.name, signal: bars[i].date, status: 'pending', reason: '后续观察期未完整', features: features(bars, i)! };
  const entry = bars[entryIndex];
  if (!entry) return result;
  result.entryDate = entry.date;
  // Suspensions or source gaps must not silently extend three exchange sessions.
  const ci = calendar.indexOf(bars[i].date);
  if (ci < 0 || calendar[ci + entryOffset] !== entry.date) return { ...result, status: 'blocked', reason: '买入日行情缺失或停牌，未假定顺延买入' };
  if (flat(entry)) return { ...result, status: 'no_fill', reason: '买入日一字或零量，保守不假定成交' };
  const entryPrice = closeEntry ? entry.close : entry.open;
  result.entry = entryPrice;
  if (!bars[end]) return result;
  for (let k = entryIndex; k <= end; k++) {
    if (calendar[ci + entryOffset + k - entryIndex] !== bars[k].date) return { ...result, status: 'blocked', reason: '观察期交易日不完整，暂停估计' };
  }
  const stop = entryPrice * (1 - o.stop / 100);
  let exitDue = !closeEntry && entry.low <= stop;
  let worst = closeEntry ? 0 : Math.min(0, entry.low / entryPrice - 1);
  for (let j = entryIndex + 1; j <= end; j++) {
    const b = bars[j];
    if (flat(b)) {
      worst = Math.min(worst, b.low / entryPrice - 1);
      exitDue ||= b.low <= stop;
      continue;
    }
    let exit: number | undefined, reason = '';
    if (exitDue) { exit = b.open; reason = '前日触线后下一可卖日开盘（含T+1）'; }
    else if (b.open <= stop) { exit = b.open; reason = '跳空穿过止损线，按开盘基准'; }
    else if (b.low <= stop) { exit = stop; reason = '日内触线，按止损价理论基准'; }
    else if (j === end) { exit = b.close; reason = `D${o.days}收盘到期退出`; }
    if (exit !== undefined) {
      // Never use the day's later low after an opening or intraday stop exit.
      worst = Math.min(worst, (reason.startsWith('D') ? b.low : exit) / entryPrice - 1);
      return { ...result, status: 'closed', reason, exitDate: b.date, exit,
        net: (exit / entryPrice - 1) * 100 - o.cost, worst: worst * 100 };
    }
    worst = Math.min(worst, b.low / entryPrice - 1);
  }
  return { ...result, status: 'blocked', reason: '到期日无法确认可成交，未按收盘价强行平仓', worst: worst * 100 };
}

export function runStudy(data: TrendData, o: Options) {
  const calendar = [...new Set(data.stocks.flatMap(s => s.bars.map(b => b.date)))].sort();
  const results: Result[] = [], latest: { stock: Stock; f: Features; hit: boolean }[] = [];
  for (const stock of data.stocks) {
    const n = stock.bars.length - 1, f = features(stock.bars, n);
    if (f) latest.push({ stock, f, hit: stock.bars[n].date === data.cutoff && matches(stock.bars, n, o) });
    for (let i = 20; i <= n; i++) {
      if (stock.bars[i].date >= data.start && stock.bars[i].date <= data.cutoff && matches(stock.bars, i, o)) results.push(simulate(stock, i, o, calendar));
    }
  }
  results.sort((a, b) => b.signal.localeCompare(a.signal) || a.code.localeCompare(b.code));
  latest.sort((a, b) => Number(b.hit) - Number(a.hit) || b.f.vr - a.f.vr);
  const closed = results.filter(r => r.status === 'closed'), wins = closed.filter(r => r.net! > 0);
  return { results, latest, count: closed.length, winRate: closed.length ? wins.length / closed.length * 100 : null,
    avg: closed.length ? mean(closed.map(r => r.net!)) : null,
    stopRate: closed.length ? closed.filter(r => !r.reason.startsWith('D')).length / closed.length * 100 : null,
    worst: closed.length ? Math.min(...closed.map(r => r.net!)) : null };
}
