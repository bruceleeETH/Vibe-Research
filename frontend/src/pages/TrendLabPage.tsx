import { useEffect, useMemo, useState } from 'react';
import { Activity, Download, Play, RefreshCw } from 'lucide-react';
import { WorkbenchNav } from '@/features/workbench/WorkbenchNav';
import { TrendDateReview } from '@/features/workbench/TrendDateReview';
import { MainboardTrendSnapshot } from '@/features/workbench/MainboardTrendSnapshot';
import { features, runStudy, type Options, type Stock, type TrendData } from '@/features/workbench/trendEngine';
import { authHeaders } from '@/lib/api';

const defaults: Options = { volume: 1.5, stop: 5, days: 3, cost: 0.2, mode: 'day', entryTiming: 'signal-close' };
const fmt = (n: number | undefined | null, suffix = '%') => n == null ? '—' : `${n.toFixed(2)}${suffix}`;
const tone = (n?: number | null) => n == null ? '' : n > 0 ? 'text-red-500' : n < 0 ? 'text-emerald-600' : '';
const cell = 'px-3 py-3 text-right whitespace-nowrap';
type MarketStoreStatus = {
  active_revision: number;
  eligible_symbols: number;
  bar_symbols: number;
  bars: number;
  min_date: string | null;
  max_date: string | null;
};

function PriceChart({ stock }: { stock: Stock }) {
  const rows = stock.bars.slice(-60), offset = stock.bars.length - rows.length;
  const lines = [rows.map(b => b.close), rows.map((_, j) => features(stock.bars, offset + j)?.ma5 ?? 0), rows.map((_, j) => features(stock.bars, offset + j)?.ma10 ?? 0)];
  const all = lines.flat().filter(x => x > 0), lo = Math.min(...all) * .97, hi = Math.max(...all) * 1.03;
  const path = (values: number[]) => values.map((v, i) => `${i ? 'L' : 'M'}${50 + i / Math.max(1, rows.length - 1) * 900},${200 - (v - lo) / (hi - lo || 1) * 180}`).join(' ');
  return <div><div className="mb-3 flex flex-wrap gap-4 text-sm"><strong>{stock.name} · 近60个行情日</strong><span className="text-sky-500">收盘</span><span className="text-amber-500">MA5</span><span className="text-violet-500">MA10</span><span className="text-muted-foreground">前复权</span></div><svg viewBox="0 0 1000 240" role="img" aria-label={`${stock.name}收盘价与5日10日均线`} className="w-full rounded-xl bg-muted/30">{[0, 1, 2, 3].map(i => <g key={i}><line x1="50" x2="950" y1={20 + i * 60} y2={20 + i * 60} stroke="currentColor" opacity=".1" /><text x="4" y={25 + i * 60} fill="currentColor" fontSize="12">{(hi - i * (hi - lo) / 3).toFixed(1)}</text></g>)}{lines.map((values, i) => <path key={i} d={path(values)} fill="none" stroke={['#0ea5e9', '#f59e0b', '#8b5cf6'][i]} strokeWidth={i ? 1.6 : 2.7} />)}<text x="50" y="230" fill="currentColor" fontSize="12">{rows[0]?.date}</text><text x="850" y="230" fill="currentColor" fontSize="12">{rows[rows.length - 1]?.date}</text></svg></div>;
}

export function TrendLabPage() {
  const [data, setData] = useState<TrendData | null>(null), [error, setError] = useState('');
  const [marketStore, setMarketStore] = useState<MarketStoreStatus | null>(null);
  const [draft, setDraft] = useState<Options>(defaults), [options, setOptions] = useState<Options>(defaults);
  const [code, setCode] = useState('600869'), [tab, setTab] = useState<'latest' | 'history'>('latest');
  const [onlyHit, setOnlyHit] = useState(false), [historyCode, setHistoryCode] = useState(''), [page, setPage] = useState(0);
  const [runAt, setRunAt] = useState(''), [loading, setLoading] = useState(false);
  async function load() {
    setLoading(true); setError('');
    try { const r = await fetch('/trend-lab-data.json', { cache: 'no-store' }); if (!r.ok) throw new Error('本地行情未生成，请运行采集命令'); const d = await r.json() as TrendData; if (!Array.isArray(d.stocks) || !d.stocks.length) throw new Error('没有有效观察池数据'); setData(d); }
    catch (e) { setError(e instanceof Error ? e.message : '读取失败'); } finally { setLoading(false); }
  }
  async function loadMarketStore() {
    try {
      const response = await fetch('/api/market-store/status', { headers: authHeaders() });
      if (!response.ok) throw new Error('数据仓状态读取失败');
      setMarketStore(await response.json() as MarketStoreStatus);
    } catch {
      setMarketStore(null);
    }
  }
  useEffect(() => {
    void load();
    void loadMarketStore();
  }, []);
  const study = useMemo(() => data ? runStudy(data, options) : null, [data, options]);
  const base = useMemo(() => data ? runStudy(data, { ...options, mode: 'none' }) : null, [data, options]);
  const stock = data?.stocks.find(s => s.code === code) ?? data?.stocks[0];
  const history = study?.results.filter(r => !historyCode || r.code === historyCode) ?? [];
  const latest = study?.latest.filter(r => !onlyHit || r.hit) ?? [];
  function run() { setOptions({ ...draft }); setPage(0); setRunAt(new Date().toLocaleTimeString('zh-CN', { hour12: false })); }
  function download() {
    if (!data || !study) return;
    const blob = new Blob([JSON.stringify({ generated_at: data.generated_at, universe: data.universe, limitations: data.limitations, options, results: study.results }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = `trend-study-${data.cutoff}.json`; a.click(); URL.revokeObjectURL(url);
  }
  return <div className="mx-auto max-w-[1500px] space-y-6 p-4 md:p-8">
    <WorkbenchNav />
    <header className="flex flex-wrap items-start justify-between gap-4"><div><div className="mb-2 flex items-center gap-2 text-sm text-primary"><Activity size={17} /> 本地研究 · 观察池试跑</div><h1 className="text-3xl font-semibold tracking-tight">趋势策略验证</h1><p className="mt-2 text-sm text-muted-foreground">选择尾盘买入日期，以当天收盘价对照隔日开盘、最低、最高、均价、收盘。</p></div><button onClick={() => { void load(); void loadMarketStore(); }} disabled={loading} className="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm"><RefreshCw size={15} />{loading ? '读取中…' : '重读本地行情'}</button></header>
    {error && <p role="alert" className="rounded-xl bg-red-500/10 p-4 text-red-500">{error}</p>}
    {!data && !error && <p className="p-10">正在读取本地行情…</p>}
    {data && study && base && <>
      {marketStore && <MainboardTrendSnapshot status={marketStore} options={options} />}
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-5 py-4 text-sm leading-7"><strong>覆盖 {data.stocks.length}/{data.expected_count} 只指定主板股票 · 非全市场回测</strong><p>数据截至 {data.cutoff}，研究窗口 {data.start} — {data.cutoff}。截图观察池存在事后选样偏差；板块热度及历史 ST 状态未验收，当前命中仅是价格与量能条件命中。</p><p className="text-xs text-muted-foreground">采集时间 {new Date(data.generated_at).toLocaleString('zh-CN', { hour12: false })} · 腾讯前复权日线 + 新浪历史成交额 · {data.errors.length} 项行情采集失败 · {data.stocks.filter(s => s.average_coverage?.status !== 'history_complete').length} 只均价未完整</p></div>
      <TrendDateReview data={data} options={options} />
      <details className="rounded-2xl border border-border bg-card p-5"><summary className="cursor-pointer font-semibold">收盘条件探索统计（展开查看）</summary><div className="mt-5 space-y-5">
      <section className="rounded-2xl border border-border bg-card p-5"><div className="mb-4 flex items-center justify-between"><h2 className="font-semibold">策略参数</h2><span className="text-xs text-muted-foreground">5日涨幅 &gt; 0 且 10日涨幅 &gt; 0</span></div><div className="flex flex-wrap items-end gap-4">
        <label className="text-sm">量能条件<select aria-label="量能条件" value={draft.mode} onChange={e => setDraft({ ...draft, mode: e.target.value as Options['mode'] })} className="mt-2 block rounded-lg border border-border bg-background p-2"><option value="day">选股日放量</option><option value="recent">最近3日曾放量上涨</option><option value="none">不限制放量（对照）</option></select></label>
        {([{ key: 'volume', title: '放量倍数', min: 1, max: 4, step: .1 }, { key: 'stop', title: '成本风险线 %', min: 1, max: 10, step: 1 }, { key: 'days', title: '买入后交易日', min: 1, max: 10, step: 1 }, { key: 'cost', title: '往返总成本 %', min: 0, max: 1, step: .05 }] as const).map(x => <label key={x.key} className="text-sm">{x.title}<input aria-label={x.title} type="number" min={x.min} max={x.max} step={x.step} value={draft[x.key]} onChange={e => { const value = Number(e.target.value); if (Number.isFinite(value)) setDraft({ ...draft, [x.key]: Math.max(x.min, Math.min(x.max, x.key === 'days' ? Math.round(value) : value)) }); }} className="mt-2 block w-32 rounded-lg border border-border bg-background p-2" /></label>)}
        <button onClick={run} className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground"><Play size={15} />运行策略</button>
      </div><p className="mt-4 text-xs leading-6 text-muted-foreground">当前结果：当日收盘价买入 / {options.mode === 'none' ? '不限制放量' : `${options.volume}倍量能`} / 成本下方 {options.stop}% / D{options.days} 收盘到期 / 扣减 {options.cost}% 往返总成本。{runAt ? `本地重算于 ${runAt}。` : '已按默认参数计算。'} 调整参数后点击运行；不重新请求网络。</p></section>
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[
        ['已完成信号样本', `${study.count}`, `全部信号 ${study.results.length}，包含待观察及未成交`],
        ['净正收益占比', fmt(study.winRate), `无放量对照 ${fmt(base.winRate)}（${base.count}个）`],
        ['平均单次净收益', fmt(study.avg), `无放量对照 ${fmt(base.avg)}；非组合收益`],
        ['最差单次净收益', fmt(study.worst), `触发风险退出占比 ${fmt(study.stopRate)}`],
      ].map(([label, value, hint]) => <div key={label} className="rounded-xl border border-border bg-card p-5"><p className="text-sm text-muted-foreground">{label}</p><p className="my-2 text-3xl font-semibold tabular-nums">{value}</p><p className="text-xs leading-5 text-muted-foreground">{hint}</p></div>)}</section>
      <p className="text-xs leading-6 text-muted-foreground">样本是重叠信号，不能当作独立交易或实际账户收益。采用固定止损与到期退出，尚未模拟分批止盈和均线延续。按收盘价买入，忽略买入前当日低点；从隔日起观察退出，跳空可能超过风险线。全天条件在收盘后才完整，因此结果用于验证收盘条件与隔日表现，不等同于盘中实时收益。日内止损按理论价格基准再扣成本，不保证成交。</p>
      <section className="overflow-hidden rounded-2xl border border-border bg-card"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4"><div className="flex gap-4"><button onClick={() => setTab('latest')} className={tab === 'latest' ? 'font-semibold text-primary' : 'text-muted-foreground'}>最新条件命中 · {study.latest.filter(r => r.hit).length}</button><button onClick={() => setTab('history')} className={tab === 'history' ? 'font-semibold text-primary' : 'text-muted-foreground'}>逐笔历史结果</button></div><button onClick={download} className="flex items-center gap-2 text-xs text-muted-foreground"><Download size={14} />导出本次结果</button></div>
      {tab === 'latest' ? <><div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 text-xs"><span>按条件命中、日线放量倍数排序。点击股票查看走势；正式热点筛选仍待数据验收。</span><label><input type="checkbox" checked={onlyHit} onChange={e => setOnlyHit(e.target.checked)} className="mr-2" />只看命中</label></div><div className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-muted/50 text-xs text-muted-foreground"><tr>{['股票', '价格/量能', '收盘', '5日涨幅', '10日涨幅', '20日涨幅', '放量倍数', 'MA5', 'MA10'].map(t => <th key={t} className={cell}>{t}</th>)}</tr></thead><tbody>{latest.map(({ stock: s, f, hit }) => <tr key={s.code} className="border-t border-border hover:bg-muted/30"><td className={cell}><button className="text-primary underline-offset-4 hover:underline" onClick={() => setCode(s.code)}>{s.name} <span className="text-xs text-muted-foreground">{s.code}</span></button></td><td className={cell}><span className={`rounded px-2 py-1 text-xs ${hit ? 'bg-primary/10 text-primary' : 'text-muted-foreground'}`}>{hit ? '条件命中' : '未命中'}</span></td><td className={cell}>{fmt(s.bars[s.bars.length - 1]?.close, '')}</td>{[f.r5, f.r10, f.r20].map((v, j) => <td key={j} className={`${cell} ${tone(v)}`}>{fmt(v)}</td>)}<td className={cell}>{fmt(f.vr, '×')}</td><td className={cell}>{fmt(f.ma5, '')}</td><td className={cell}>{fmt(f.ma10, '')}</td></tr>)}</tbody></table>{!latest.length && <p className="p-8 text-center text-muted-foreground">当前参数没有命中，不强行补足名单。</p>}</div></> : <><div className="flex items-center justify-between px-5 py-3 text-sm"><select aria-label="历史结果股票" value={historyCode} onChange={e => { setHistoryCode(e.target.value); setPage(0); }} className="rounded border border-border bg-background p-2"><option value="">全部股票</option>{data.stocks.map(s => <option key={s.code} value={s.code}>{s.name} {s.code}</option>)}</select><span className="text-xs text-muted-foreground">共 {history.length} 个信号 · 含未成熟结果</span></div><div className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-muted/50 text-xs text-muted-foreground"><tr>{['股票', '收盘条件日', '买入日', '买入基准', '退出日', '净收益', '期间最差浮亏', '结果 / 原因'].map(t => <th key={t} className={cell}>{t}</th>)}</tr></thead><tbody>{history.slice(page * 30, (page + 1) * 30).map(r => <tr key={`${r.code}-${r.signal}`} className="border-t border-border"><td className={cell}>{r.name}</td><td className={cell}>{r.signal}</td><td className={cell}>{r.entryDate ?? '待下一交易日'}</td><td className={cell}>{fmt(r.entry, '')}</td><td className={cell}>{r.exitDate ?? '—'}</td><td className={`${cell} ${tone(r.net)}`}>{fmt(r.net)}</td><td className={`${cell} ${tone(r.worst)}`}>{fmt(r.worst)}</td><td className="min-w-56 px-3 py-3 text-xs">{r.reason}</td></tr>)}</tbody></table>{!history.length && <p className="p-8 text-center text-muted-foreground">当前参数没有历史信号。</p>}</div><div className="flex justify-end gap-4 p-4 text-sm"><button disabled={!page} onClick={() => setPage(page - 1)} className="disabled:opacity-30">上一页</button><span>{page + 1} / {Math.max(1, Math.ceil(history.length / 30))}</span><button disabled={(page + 1) * 30 >= history.length} onClick={() => setPage(page + 1)} className="disabled:opacity-30">下一页</button></div></>}
      </section>
      {stock && <section className="rounded-2xl border border-border bg-card p-5"><PriceChart stock={stock} /></section>}
      </div></details>
      <footer className="text-xs leading-6 text-muted-foreground">公开行情保存在本地，重算不产生交易。更新行情命令：<code>backend/.venv/bin/python tools/trend_lab_data.py</code>。收益使用前复权价格比值；历史均价是跨源校准后的全天成交均价，不是可成交价格；日线成交量倍数与同花顺盘中“量比”口径不同。{data.errors.map(e => <p key={e.code}>{e.code}：{e.error}</p>)}{data.stocks.filter(s => s.amount_error).map(s => <p key={s.code}>{s.code} 均价：{s.amount_error}</p>)}</footer>
    </>}
  </div>;
}
