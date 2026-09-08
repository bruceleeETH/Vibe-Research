import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { authHeaders } from '@/lib/api';
import { beijingDate } from '@/features/workbench/GuidedEntry';
import { InvestmentCardLink } from '@/features/workbench/InvestmentCardLink';

type Stock = { code: string; name: string; boards: number | null; price: number | null; pct: number | null; amount: number | null; float_cap: number | null; turnover: number | null; seal_amount: number | null; first_seal: string | null; last_seal: string | null; breaks: number | null; industry: string; market: string; is_st: boolean };
type Snapshot = { date: string; captured_at: string; expected_count: number | null; count: number; coverage: string; phase: string; scope: string; origin: string; warning: string; missing_fields: Record<string, number>; stocks: Stock[] };
const input = 'rounded-lg border border-border bg-background px-3 py-2 text-xs';
const num = (value: number | null, suffix = '') => value === null ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) + suffix;
const money = (value: number | null) => value === null ? '—' : value >= 1e8 ? num(value / 1e8, '亿') : num(value / 1e4, '万');
export function LimitUpList({ marketDate }: { marketDate?: string }) {
  const [day, setDay] = useState(beijingDate);
  const [manual, setManual] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<Snapshot | null>(null);
  const [dates, setDates] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [tier, setTier] = useState('all');
  const [query, setQuery] = useState('');
  const [market, setMarket] = useState('all');
  const [sort, setSort] = useState('boards');
  const [st, setSt] = useState('all');
  useEffect(() => { if (!manual && marketDate) setDay(marketDate); }, [marketDate, manual]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(''); setData(null);
    const headers = authHeaders();
    fetch('/api/market/limit-up?' + new URLSearchParams({ date: day, refresh: String(refresh > 0) }), { headers, signal: controller.signal })
      .then(async r => { const value = await r.json(); if (!r.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '涨停样本读取失败'); return value; })
      .then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => {
        if (controller.signal.aborted) return;
        setLoading(false);
        fetch('/api/market/limit-up/dates', { headers, signal: controller.signal }).then(r => r.ok ? r.json() : null).then(value => { if (value && !controller.signal.aborted) setDates(value.dates); }).catch(() => {});
      });
    return () => controller.abort();
  }, [day, refresh]);
  const chooseDay = (value: string) => { if (!value) return; setManual(true); setDay(value); setRefresh(0); };
  const stocks = data?.stocks || [];
  const shown = stocks.filter(s => (tier === 'all' || tier === 'unknown' ? tier === 'all' || s.boards === null : tier === '4+' ? s.boards !== null && s.boards >= 4 : s.boards === Number(tier)) && (market === 'all' || s.market === market) && (st === 'all' || (st === 'st' ? s.is_st : !s.is_st)) && `${s.code} ${s.name} ${s.industry}`.includes(query.trim())).sort((a, b) => {
    if (sort === 'first_seal') return (a.first_seal || '99').localeCompare(b.first_seal || '99') || a.code.localeCompare(b.code);
    const key = sort as 'boards' | 'amount' | 'turnover' | 'seal_amount';
    return (b[key] ?? -1) - (a[key] ?? -1) || a.code.localeCompare(b.code);
  });
  const counts = [1, 2, 3].map(n => stocks.filter(s => s.boards === n).length);
  return <section className="mb-6 rounded-xl border border-border bg-card p-4 sm:p-5"><header className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-base font-semibold">全量涨停与次日观察</h3><p className="mt-1 text-xs text-muted-foreground">第一阶段：首板至高位板清单与每日样本，次日预测尚未启用。</p></div><button className={input + ' flex items-center gap-2 disabled:opacity-50'} disabled={loading} onClick={() => setRefresh(n => n + 1)}><RefreshCw size={14} />{loading ? '正在读取…' : '重新采集所选日期'}</button></header>
    <div className="my-4 flex flex-wrap items-center gap-3"><label className="text-xs">样本日期 <input aria-label="涨停样本日期" className={input} type="date" max={beijingDate()} value={day} onChange={e => chooseDay(e.target.value)} /></label>{marketDate && <button className="text-xs text-primary underline" onClick={() => chooseDay(marketDate)}>最近行情日 {marketDate}</button>}<select aria-label="已保存涨停样本" className={input} value="" onChange={e => chooseDay(e.target.value)}><option value="">本地已保存日期（{dates.length}）</option>{dates.map(d => <option key={d} value={d}>{d}</option>)}</select></div>
    <p className="mb-3 text-xs leading-6 text-muted-foreground">盘中为动态快照，盘后为收盘后采样。打开日期会保存取得的样本；本地服务运行时，工作日 15:10 后自动采集当日并重试失败请求。关机或服务停止期间不会采集，历史能否补取取决于来源。</p>
    {loading && <p role="status" className="py-6 text-sm text-muted-foreground">正在读取 {day} 的涨停池…</p>}
    {error && <p role="alert" className="rounded-lg bg-red-500/10 p-4 text-sm text-red-500">{day}：{error}。未用其他日期替代；可重试或选择已保存日期。</p>}
    {data && <><div className="rounded-lg bg-muted/30 p-3 text-xs leading-6"><p>{data.date} · {data.phase === 'after_close' ? '盘后样本' : '盘中快照（非收盘结论）'} · {data.origin === 'local' ? '读取本地存档' : '已采集并保存本地'} · 采样时间 {new Date(data.captured_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}</p><p>收到 {data.count} 只 / 来源报告 {data.expected_count ?? '未知'} 只 · {data.coverage === 'source_complete' ? '来源内条数一致' : '来源覆盖不完整'}</p><p className="text-muted-foreground">{data.scope}</p>{data.warning && <p role="alert" className="text-orange-500">{data.warning}</p>}{Object.values(data.missing_fields).some(n => n > 0) && <p className="text-orange-500">部分字段缺失，表格以“—”显示；缺失连板数不按首板计算。</p>}</div>
      <div className="my-3 flex flex-wrap gap-2 text-xs">{[['全部', stocks.length], ['首板', counts[0]], ['二板', counts[1]], ['三板', counts[2]], ['四板及以上', stocks.filter(s => s.boards !== null && s.boards >= 4).length], ['连板数未知', stocks.filter(s => s.boards === null).length]].map(([label, count]) => <span key={label} className="rounded bg-muted/30 px-3 py-2">{label} {count}</span>)}</div>
      <div className="mb-3 flex flex-wrap gap-2"><select aria-label="涨停梯队筛选" className={input} value={tier} onChange={e => setTier(e.target.value)}>{[['all', '全部梯队'], ['1', '首板'], ['2', '二板'], ['3', '三板'], ['4+', '四板及以上'], ['unknown', '连板数未知']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select><select aria-label="涨停市场筛选" className={input} value={market} onChange={e => setMarket(e.target.value)}>{['all', '沪深主板', '创业板', '科创板', '北交所'].map(x => <option key={x} value={x}>{x === 'all' ? '全部市场' : x}</option>)}</select><select aria-label="ST筛选" className={input} value={st} onChange={e => setSt(e.target.value)}><option value="all">含 ST</option><option value="exclude">排除 ST</option><option value="st">仅 ST（按名称识别）</option></select><select aria-label="涨停排序" className={input} value={sort} onChange={e => setSort(e.target.value)}>{[['boards', '连板数从高到低'], ['first_seal', '首次封板从早到晚'], ['amount', '成交额从高到低'], ['turnover', '换手率从高到低'], ['seal_amount', '封板资金从高到低']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select><input aria-label="搜索涨停股票" className={input + ' min-w-0 flex-1'} placeholder="名称、代码或行业" value={query} onChange={e => setQuery(e.target.value)} /></div>
      <p className="mb-2 text-xs text-muted-foreground">显示 {shown.length} / {stocks.length} 只 · 封板资金是来源快照值，不代表全天稳定封单。暂不推断一字板或涨停原因。</p>
      <div className="max-h-[600px] overflow-auto rounded-lg border border-border"><table className="w-full whitespace-nowrap text-left text-xs"><thead className="sticky top-0 z-10 bg-card"><tr>{['名称 / 代码', '梯队', '来源价格', '涨幅', '首次封板', '最后封板', '开板次数', '换手率', '成交额', '封板资金', '流通市值', '市场 / 行业', '研究'].map(h => <th key={h} className="px-3 py-3 font-medium">{h}</th>)}</tr></thead><tbody>{shown.map(s => <tr key={s.code} className="border-t border-border/50 hover:bg-muted/20"><td className="px-3 py-3"><strong>{s.name}</strong><span className="ml-2 text-muted-foreground">{s.code}</span></td><td className="px-3 text-primary">{s.boards === null ? '未知' : s.boards === 1 ? '首板' : `${s.boards} 板`}</td><td className="px-3 font-mono">{num(s.price)}</td><td className="px-3 font-mono text-danger">{num(s.pct, '%')}</td><td className="px-3">{s.first_seal || '—'}</td><td className="px-3">{s.last_seal || '—'}</td><td className="px-3">{num(s.breaks)}</td><td className="px-3">{num(s.turnover, '%')}</td><td className="px-3">{money(s.amount)}</td><td className="px-3">{money(s.seal_amount)}</td><td className="px-3">{money(s.float_cap)}</td><td className="px-3">{s.market} / {s.industry || '未知'}</td><td className="px-3"><InvestmentCardLink code={s.code} name={s.name} /></td></tr>)}</tbody></table>{!shown.length && <p className="p-6 text-center text-muted-foreground">没有匹配筛选条件的股票。</p>}</div>
    </>}
  </section>;
}
