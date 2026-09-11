import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ArrowRight, Database } from 'lucide-react';
import { authHeaders } from '@/lib/api';
import type { Options } from './trendEngine';

type StoreStatus = {
  active_revision: number;
  eligible_symbols: number;
  bar_symbols: number;
  bars: number;
};

type SnapshotRow = {
  code: string;
  name_asof: string;
  total_mcap_cny: number | null;
  close_qfq: number;
  r5: number | null;
  r10: number | null;
  volume_ratio: number | null;
  hit: boolean;
  next_open: number | null;
  next_low: number | null;
  next_high: number | null;
  next_average: number | null;
  next_close: number | null;
};

type Snapshot = {
  revision: number;
  universe_mode: string;
  date: string;
  next_date: string | null;
  universe_total: number;
  observed: number;
  historical_st_excluded: number;
  hits: number;
  total: number;
  page: number;
  page_size: number;
  rows: SnapshotRow[];
};

const td = 'px-3 py-3 text-right whitespace-nowrap';
const number = (value?: number | null) => value == null ? '—' : value.toFixed(2);
const percent = (value?: number | null) => value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
const tone = (value?: number | null) => value == null ? 'text-muted-foreground' : value > 0 ? 'text-red-500' : value < 0 ? 'text-emerald-600' : '';
const change = (value?: number | null, base?: number | null) => value == null || !base ? null : (value / base - 1) * 100;

/**
 * 展示服务端基于 DuckDB 计算的主板全池日期快照；浏览器只接收当前页。
 */
export function MainboardTrendSnapshot({ status, options }: { status: StoreStatus; options: Options }) {
  const [dates, setDates] = useState<string[]>([]);
  const [selected, setSelected] = useState('');
  const [onlyHits, setOnlyHits] = useState(true);
  const [page, setPage] = useState(1);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetch('/api/market-store/dates', { headers: authHeaders() })
      .then(async response => {
        if (!response.ok) throw new Error('交易日期读取失败');
        const payload = await response.json() as { dates: string[] };
        if (cancelled) return;
        setDates(payload.dates);
        setSelected(current => current || payload.dates[Math.max(0, payload.dates.length - 2)] || '');
      })
      .catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : '交易日期读取失败'); });
    return () => { cancelled = true; };
  }, [status.active_revision]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    const query = new URLSearchParams({
      date: selected,
      volume: String(options.volume),
      mode: options.mode,
      only_hits: String(onlyHits),
      page: String(page),
      page_size: '100',
      revision: String(status.active_revision),
    });
    void fetch(`/api/market-store/trend-snapshot?${query}`, {
      headers: authHeaders(),
      signal: controller.signal,
    })
      .then(async response => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || '主板趋势快照读取失败');
        setSnapshot(payload as Snapshot);
      })
      .catch(reason => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return;
        setError(reason instanceof Error ? reason.message : '主板趋势快照读取失败');
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [selected, onlyHits, page, options.volume, options.mode, status.active_revision]);

  const at = dates.indexOf(selected);
  const previous = at > 0 ? dates[at - 1] : '';
  const next = at >= 0 && at < dates.length - 1 ? dates[at + 1] : '';
  const pages = Math.max(1, Math.ceil((snapshot?.total ?? 0) / (snapshot?.page_size ?? 100)));
  const modeLabel = useMemo(() => options.mode === 'none' ? '不限制放量' : options.mode === 'recent' ? `最近3日曾放量上涨 ≥${options.volume}×` : `当日放量 ≥${options.volume}×`, [options.mode, options.volume]);

  return <section className="overflow-hidden rounded-2xl border border-sky-500/30 bg-card">
    <div className="border-b border-border bg-sky-500/5 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="flex items-center gap-2"><Database size={18} className="text-sky-500" /><h2 className="text-lg font-semibold">主板全池日期观察</h2></div><p className="mt-2 text-sm text-muted-foreground">当前快照股票池：主板、非 ST、总市值≥30亿元；历史信号日再次排除当日 ST。</p></div><span className="text-xs text-muted-foreground">revision {status.active_revision} · {status.bar_symbols.toLocaleString()}只 · {status.bars.toLocaleString()}根日线</span></div>
      <div className="mt-4 flex flex-wrap items-end gap-3"><label className="text-sm font-medium">条件日期<input type="date" value={selected} min={dates[0]} max={dates[dates.length - 1]} onChange={event => { setSelected(event.target.value); setPage(1); }} className="mt-2 block rounded-lg border border-border bg-background px-3 py-2" /></label><button disabled={!previous} onClick={() => { setSelected(previous); setPage(1); }} className="flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-30"><ArrowLeft size={14} />前一天</button><button disabled={!next} onClick={() => { setSelected(next); setPage(1); }} className="flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-30">后一天<ArrowRight size={14} /></button><label className="pb-2 text-sm"><input type="checkbox" checked={onlyHits} onChange={event => { setOnlyHits(event.target.checked); setPage(1); }} className="mr-2" />只看条件命中</label></div>
      {snapshot && <div className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5"><div><span className="block text-xs text-muted-foreground">当前固定池</span><strong>{snapshot.universe_total.toLocaleString()}</strong></div><div><span className="block text-xs text-muted-foreground">当日有行情</span><strong>{snapshot.observed.toLocaleString()}</strong></div><div><span className="block text-xs text-muted-foreground">条件命中</span><strong>{snapshot.hits.toLocaleString()}</strong></div><div><span className="block text-xs text-muted-foreground">当日 ST 排除</span><strong>{snapshot.historical_st_excluded.toLocaleString()}</strong></div><div><span className="block text-xs text-muted-foreground">隔日</span><strong>{snapshot.next_date ?? '待更新'}</strong></div></div>}
      <p className="mt-3 text-xs text-muted-foreground">筛选：5日、10日涨幅均为正；{modeLabel}。股票池市值是 2026-09-11 当前快照，不是历史时点市值，因此本页暂用于数据与规则验证。</p>
    </div>
    {error && <p role="alert" className="p-5 text-sm text-red-500">{error}</p>}
    {loading && <p role="status" className="p-5 text-sm text-muted-foreground">正在从本地 DuckDB 计算…</p>}
    {snapshot && !loading && <><div className="overflow-x-auto"><table aria-label="主板全池隔日价格对照" className="w-full text-sm"><thead className="bg-muted/50 text-xs text-muted-foreground"><tr>{['股票', '总市值', '条件日收盘', '5日', '10日', '放量', '隔日开盘', '最低', '最高', '均价', '收盘'].map(title => <th key={title} className={td}>{title}</th>)}</tr></thead><tbody>{snapshot.rows.map(row => <tr key={row.code} className="border-t border-border hover:bg-muted/20"><td className={td}><strong className="text-primary">{row.name_asof}</strong><span className="ml-2 text-xs text-muted-foreground">{row.code}</span></td><td className={td}>{row.total_mcap_cny == null ? '—' : `${(row.total_mcap_cny / 1e8).toFixed(1)}亿`}</td><td className={td}>{number(row.close_qfq)}</td><td className={`${td} ${tone(row.r5)}`}>{percent(row.r5)}</td><td className={`${td} ${tone(row.r10)}`}>{percent(row.r10)}</td><td className={td}>{row.volume_ratio == null ? '—' : `${row.volume_ratio.toFixed(2)}×`}</td>{[row.next_open, row.next_low, row.next_high, row.next_average, row.next_close].map((value, index) => <td key={index} className={`${td} ${tone(change(value, row.close_qfq))}`}>{number(value)}<span className="mt-1 block text-xs">{percent(change(value, row.close_qfq))}</span></td>)}</tr>)}</tbody></table>{!snapshot.rows.length && <p className="p-8 text-center text-sm text-muted-foreground">当前日期与参数没有命中；可取消“只看条件命中”查看全池。</p>}</div><div className="flex items-center justify-end gap-4 border-t border-border p-4 text-sm"><span>第 {page}/{pages} 页 · {snapshot.total.toLocaleString()} 条</span><button disabled={page <= 1} onClick={() => setPage(value => value - 1)} className="disabled:opacity-30">上一页</button><button disabled={page >= pages} onClick={() => setPage(value => value + 1)} className="disabled:opacity-30">下一页</button></div></>}
  </section>;
}
