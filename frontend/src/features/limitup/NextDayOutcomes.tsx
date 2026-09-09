import { useEffect, useState } from 'react';
import { authHeaders } from '@/lib/api';

type Row = { code: string; name: string; boards: number | null; market: string; open_pct: number | null; close_pct: number | null; high_pct: number | null; touched: boolean | null; promoted: boolean | null; reason: string };
type Result = { captured_at?: string; state: string; running: boolean; message: string; target_date?: string; completed?: number; total?: number; rows: Row[]; sources?: Record<string, string> };
type Group = { market: string; tier: string; total: number; up: number; returns_n: number; touched: number; touch_n: number; promoted: number; promotion_n: number };
type Stats = { groups: Group[]; included_dates: string[]; excluded_dates: string[]; scope: string };
const input = 'rounded-lg border border-border bg-background px-3 py-2 text-xs';
const pct = (n: number | null) => n === null ? '—' : `${n > 0 ? '+' : ''}${n.toFixed(2)}%`;
const yes = (v: boolean | null) => v === null ? '待确认' : v ? '是' : '否';
const rate = (n: number, d: number) => d ? `${(n / d * 100).toFixed(1)}%（${n}/${d}）` : '—（有效样本 0）';
async function request(url: string, signal?: AbortSignal, method = 'GET') {
  const r = await fetch(url, { headers: authHeaders(), signal, method });
  const value = await r.json();
  if (!r.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '请求失败');
  return value;
}
export function NextDayOutcomes({ day }: { day: string }) {
  const [result, setResult] = useState<Result | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState('');
  const [statsError, setStatsError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [market, setMarket] = useState('');
  const [filter, setFilter] = useState('all');
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    setResult(null); setError('');
    const poll = async () => {
      try {
        const value = await request('/api/market/limit-up-outcomes/day?' + new URLSearchParams({ date: day }), controller.signal);
        if (controller.signal.aborted) return;
        setResult(value);
        if (value.running) timer = setTimeout(poll, 2000);
      } catch (e) { if (!controller.signal.aborted) { setError((e as Error).message); setResult(previous => previous ? { ...previous, running: false } : null); } }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [day, revision]);
  useEffect(() => {
    const controller = new AbortController(); setStats(null); setStatsError('');
    request('/api/market/limit-up-outcomes/stats?' + new URLSearchParams({ start, end, market }), controller.signal)
      .then(v => { if (!controller.signal.aborted) setStats(v); })
      .catch(e => { if (!controller.signal.aborted) setStatsError(e.message); });
    return () => controller.abort();
  }, [start, end, market, result?.state, revision]);
  const run = async () => {
    setBusy(true); setError('');
    try { await request('/api/market/limit-up-outcomes/day?' + new URLSearchParams({ date: day }), undefined, 'POST'); setRevision(n => n + 1); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const rows = (result?.rows || []).filter(r => filter === 'all' || (filter === 'unknown' ? r.close_pct === null || r.touched === null || r.promoted === null : filter === 'promoted' ? r.promoted : r.close_pct !== null && r.close_pct > 0));
  return <div className="mt-6 border-t border-border pt-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><h4 className="font-semibold">次日实际表现</h4><p className="mt-1 text-xs text-muted-foreground">样本日 {day} → 下一交易日 {result?.target_date || '待交易日数据确认'}</p></div><button className={input + ' disabled:opacity-50'} disabled={busy || result?.running} onClick={run}>{busy || result?.running ? `正在核对 ${result?.completed || 0}/${result?.total || '…'}` : '补齐 / 重试次日结果'}</button></div>
    <p role="status" className="my-3 rounded-lg bg-muted/30 p-3 text-xs">{result?.running ? '后台核对中，可离开页面后再查看。' : result?.message || '正在读取本地结果…'}</p>
    {result?.captured_at && <p className="mb-2 text-xs text-muted-foreground">结果采集时间：{new Date(result.captured_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}</p>}
    {error && <p role="alert" className="my-2 text-sm text-red-500">{error}</p>}
    <p className="mb-3 text-xs leading-6 text-muted-foreground">仅核对完整盘后样本。涨跌幅来自次日行情；开盘与最高涨幅以样本日收盘价为基准，经不复权日线交叉核对。最高涨幅不代表可成交收益。停牌、缺失或参考价变化以“—”显示；触板、晋级按来源涨停 / 炸板池核对。数据保存在本地。服务运行时，15:10 后每 10 分钟尝试补齐已存样本；也可点击按钮重试。</p>
    {result?.sources && <details className="mb-3 text-xs text-muted-foreground"><summary className="cursor-pointer">查看来源核对状态</summary>{Object.entries(result.sources).map(([k, v]) => <p key={k} className="mt-2">{k}：{v}</p>)}</details>}
    {result && result.rows.length > 0 && <><select aria-label="次日结果筛选" className={input + ' mb-3'} value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部实际结果</option><option value="up">收盘上涨</option><option value="promoted">连板晋级</option><option value="unknown">存在待确认字段</option></select><div className="max-h-96 overflow-auto rounded-lg border border-border"><table className="w-full whitespace-nowrap text-left text-xs"><thead className="sticky top-0 bg-card"><tr>{['股票', '样本日梯队', '开盘涨幅', '收盘涨幅', '最高涨幅', '触板', '晋级', '核对状态'].map(h => <th className="p-3" key={h}>{h}</th>)}</tr></thead><tbody>{rows.map(r => <tr className="border-t border-border/50" key={r.code}><td className="p-3">{r.name} {r.code}</td><td className="p-3">{r.boards === null ? '未知' : `${r.boards} 板`}</td><td className="p-3">{pct(r.open_pct)}</td><td className="p-3">{pct(r.close_pct)}</td><td className="p-3">{pct(r.high_pct)}</td><td className="p-3">{yes(r.touched)}</td><td className="p-3">{yes(r.promoted)}</td><td className="p-3 text-muted-foreground">{r.reason}</td></tr>)}</tbody></table>{rows.length === 0 && <p className="p-4">没有匹配的结果。</p>}</div></>}
    <h4 className="mb-3 mt-6 font-semibold">梯队历史统计</h4><div className="mb-3 flex flex-wrap gap-3"><label className="text-xs">样本开始 <input aria-label="统计开始日期" type="date" className={input} value={start} onChange={e => setStart(e.target.value)} /></label><label className="text-xs">样本结束 <input aria-label="统计结束日期" type="date" className={input} value={end} onChange={e => setEnd(e.target.value)} /></label><select aria-label="统计市场" className={input} value={market} onChange={e => setMarket(e.target.value)}><option value="">全部市场（分开统计）</option>{['沪深主板', '创业板', '科创板', '北交所'].map(m => <option key={m}>{m}</option>)}</select></div>
    {statsError && <p role="alert" className="mb-3 text-sm text-red-500">{statsError}</p>}
    {stats && <><p className="mb-3 text-xs leading-6 text-muted-foreground">{stats.scope}<br />纳入 {stats.included_dates.length} 个样本日{stats.included_dates.length > 0 ? `（${stats.included_dates[0]} 至 ${stats.included_dates[stats.included_dates.length - 1]}）` : ''}；待补齐或不可用 {stats.excluded_dates.length} 日。比例括号为“事件数 / 有效样本数”，平盘不算上涨。</p><div className="overflow-auto rounded-lg border border-border"><table className="w-full whitespace-nowrap text-left text-xs"><thead><tr>{['市场', '样本日梯队', '样本数', '上涨率', '触板率', '晋级率'].map(h => <th className="p-3" key={h}>{h}</th>)}</tr></thead><tbody>{stats.groups.map(g => <tr key={g.market + g.tier} className="border-t border-border/50"><td className="p-3">{g.market}</td><td className="p-3">{g.tier}</td><td className="p-3">{g.total}</td><td className="p-3">{rate(g.up, g.returns_n)}</td><td className="p-3">{rate(g.touched, g.touch_n)}</td><td className="p-3">{rate(g.promoted, g.promotion_n)}</td></tr>)}</tbody></table>{stats.groups.length === 0 && <p className="p-4 text-xs text-muted-foreground">还没有可统计的次日结果。选择已收盘的历史样本日期，点击“补齐 / 重试次日结果”。</p>}</div>{stats.excluded_dates.length > 0 && <details className="mt-3 text-xs text-muted-foreground"><summary>待补齐 / 未纳入日期</summary><p className="mt-2">{stats.excluded_dates.join('、')}</p></details>}</>}
  </div>;
}
