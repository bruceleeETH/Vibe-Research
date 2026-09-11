import { useMemo, useState } from 'react';
import { ArrowLeft, ArrowRight, CalendarDays } from 'lucide-react';
import { dateSnapshot, features, reviewDates, type Bar, type Options, type TrendData } from './trendEngine';

const price = (v?: number) => v == null ? '—' : v.toFixed(2);
const pct = (v?: number | null) => v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`;
const color = (v?: number | null) => v == null ? 'text-muted-foreground' : v > 0 ? 'text-red-500' : v < 0 ? 'text-emerald-600' : 'text-muted-foreground';
const change = (v?: number, base?: number) => v == null || !base ? undefined : (v / base - 1) * 100;
const volume = (b?: Bar) => b ? `${(b.volume / 10000).toFixed(2)}万手` : '—';
const mult = (v?: number | null) => v == null ? '—' : `${v.toFixed(2)}×`;
const td = 'px-3 py-3 text-right whitespace-nowrap align-top';

function PriceCell({ value, base, missing }: { value?: number; base?: number; missing?: string }) {
  const r = change(value, base);
  return <><span className="font-medium tabular-nums">{price(value)}</span><span className={`mt-1 block text-xs tabular-nums ${color(r)}`}>{value == null && missing ? missing : pct(r)}</span></>;
}

export function TrendDateReview({ data, options }: { data: TrendData; options: Options }) {
  const dates = useMemo(() => reviewDates(data), [data]);
  const [chosen, setChosen] = useState('');
  const date = chosen || dates[Math.max(0, dates.length - 2)] || data.cutoff;
  const [onlyHits, setOnlyHits] = useState(false), [filter, setFilter] = useState('');
  const [detailCode, setDetailCode] = useState('600869');
  const snapshot = useMemo(() => dateSnapshot(data, date, { ...options, entryTiming: 'signal-close' }), [data, date, options]);
  const visible = snapshot.rows.filter(r => (!onlyHits || r.hit) && (!filter || r.stock.code === filter));
  const detail = snapshot.rows.find(r => r.stock.code === detailCode) ?? snapshot.rows[0];
  const previous = dates.filter(d => d < date).slice(-1)[0], next = dates.find(d => d > date);
  const detailDays = dates.filter(d => d >= date).slice(0, 4);
  const scope = options.mode === 'none' ? '5日、10日上涨；不限制放量' : `5日、10日上涨；${options.mode === 'day' ? '买入日' : '最近3日曾上涨并'}放量 ≥ ${options.volume}倍`;

  return <section aria-label="尾盘日期观察" className="overflow-hidden rounded-2xl border border-primary/25 bg-card">
    <div className="border-b border-border bg-primary/5 p-5">
      <div className="flex items-center gap-2"><CalendarDays size={19} className="text-primary" /><h2 className="text-lg font-semibold">尾盘买入，看隔日表现</h2></div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">选一个交易日，以当天收盘价为买入基准，直接对照隔日五个价格与放量情况。</p>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="text-sm font-medium">尾盘买入日期<input type="date" aria-label="尾盘买入日期" value={date} min={data.start} max={data.cutoff} onChange={e => setChosen(e.target.value)} className="mt-2 block rounded-lg border border-border bg-background px-3 py-2" /></label>
        <button aria-label="前一个交易日" disabled={!previous} onClick={() => previous && setChosen(previous)} className="flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-30"><ArrowLeft size={14} />前一天</button>
        <button aria-label="后一个交易日" disabled={!next} onClick={() => next && setChosen(next)} className="flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-30">后一天<ArrowRight size={14} /></button>
        <button onClick={() => setChosen(dates[Math.max(0, dates.length - 2)] || data.cutoff)} className="rounded-lg px-2 py-2 text-sm text-primary">最近可完整对照日</button>
      </div>
      <div className="mt-4 grid gap-2 text-sm sm:grid-cols-3">
        <div className="rounded-lg bg-background/70 p-3"><span className="block text-xs text-muted-foreground">① 选股与买入基准</span><strong className="mt-1 block">当日收盘价</strong><span className="text-xs text-muted-foreground">统一比较口径</span></div>
        <div className="rounded-lg bg-background/70 p-3"><span className="block text-xs text-muted-foreground">② 尾盘买入 · 收盘价基准</span><strong className="mt-1 block">{date}</strong><span className="text-xs text-muted-foreground">{snapshot.rows.filter(r => r.hit).length}只收盘后条件命中</span></div>
        <div className="rounded-lg bg-background/70 p-3"><span className="block text-xs text-muted-foreground">③ 隔日观察 · 最早可卖</span><strong className="mt-1 block">{snapshot.sellDate || '尚无后续数据'}</strong><span className="text-xs text-muted-foreground">各价格均与买入日收盘价对照</span></div>
      </div>
      <p className="mt-4 text-sm leading-6 text-amber-700 dark:text-amber-400">当前采用收盘后复盘口径：用当天完整的涨幅和量能筛选，并以当天收盘价作为统一买入基准，观察隔日价格表现。收盘价是研究基准，实际尾盘成交价可能略有差异。</p>
    </div>
    {!snapshot.isObservedDate ? <p role="status" className="p-6 text-sm text-muted-foreground">{date} 没有交易日行情。请用“前一天 / 后一天”选择已有交易日；不会自动套用别的日期。</p> : <>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <strong className="text-sm">{date} 收盘 → {snapshot.sellDate || '隔日待更新'}</strong>
        <div className="flex flex-wrap items-center gap-3 text-sm"><label><input aria-label="日期对照只看命中" type="checkbox" checked={onlyHits} onChange={e => setOnlyHits(e.target.checked)} className="mr-2" />只看收盘后命中</label><select aria-label="日期对照股票" value={filter} onChange={e => { setFilter(e.target.value); if (e.target.value) setDetailCode(e.target.value); }} className="rounded-lg border border-border bg-background p-2"><option value="">全部{data.stocks.length}只观察池股票</option>{data.stocks.map(s => <option key={s.code} value={s.code}>{s.name} {s.code}</option>)}</select></div>
      </div>
      <p className="px-5 pb-3 text-xs leading-6 text-muted-foreground">筛选口径：{scope}。价格为前复权对照价；百分比相对买入日收盘，未扣费用、未执行止损，不是已实现收益。横向滚动可查看全部列。</p>
      <div className="overflow-x-auto"><table aria-label="尾盘买入隔日价格对照" className="w-full text-sm"><thead className="bg-muted/50 text-xs text-muted-foreground"><tr>{['股票 / 收盘后条件', '买入基准（收盘）', '5日 / 10日涨幅', '买入日放量', '隔日开盘', '隔日最低', '隔日最高', '隔日均价', '隔日收盘', '隔日放量'].map((name, i) => <th key={name} className={`${td} ${i === 0 ? 'sticky left-0 z-10 bg-card' : ''}`}>{name}</th>)}</tr></thead><tbody>{visible.map(row => {
        const b = row.sell, f = row.sellFeatures, base = row.entry?.close;
        return <tr key={row.stock.code} className={`border-t border-border ${detailCode === row.stock.code ? 'bg-primary/5' : 'hover:bg-muted/20'}`}><td className={`${td} sticky left-0 bg-card`}><button onClick={() => setDetailCode(row.stock.code)} className="font-medium text-primary hover:underline">{row.stock.name}</button><span className="mt-1 block text-xs text-muted-foreground">{row.stock.code} · {row.hit ? '命中' : !row.signal ? '当日缺数据' : '未命中'}</span></td><td className={td}>{price(base)}{row.entryUncertain && <span className="mt-1 block text-xs text-amber-600">一字/零量，成交未确认</span>}</td><td className={td}><span className={color(row.f?.r5)}>{pct(row.f?.r5)}</span><span className={`mt-1 block text-xs ${color(row.f?.r10)}`}>{pct(row.f?.r10)}</span></td><td className={td}><span>{mult(row.f?.vr)}</span><span className="mt-1 block text-xs text-muted-foreground">{volume(row.signal)}</span></td>{(['open', 'low', 'high', 'average', 'close'] as const).map(key => <td key={key} className={td}><PriceCell value={b?.[key]} base={base} missing={key === 'average' && b ? '缺成交额' : undefined} /></td>)}<td className={td}><span className={f && f.vr >= options.volume ? 'font-semibold text-primary' : ''}>{mult(f?.vr)}</span><span className="mt-1 block text-xs text-muted-foreground">{volume(b)}</span>{!b && <span className="block text-xs text-muted-foreground">{snapshot.sellDate ? '缺数据/可能停牌' : '待后续数据'}</span>}</td></tr>;
      })}</tbody></table>{!visible.length && <p className="p-6 text-center text-sm text-muted-foreground">当日没有匹配股票，可取消“只看收盘后命中”继续比较。</p>}</div>
      <p className="px-5 py-3 text-xs leading-6 text-muted-foreground">放量倍数 = 当日成交量 ÷ 此前5个交易日平均量。隔日放量是事后结果，不参与条件日筛选。均价 = 成交额 ÷ 成交股数；目前仅最新日有经校验的收盘成交额，历史缺失显示“—”。最高价和全天均价均不代表一定可卖到的价格。</p>
      {detail && <div className="border-t border-border p-5"><div className="mb-3 flex flex-wrap items-baseline justify-between gap-2"><h3 className="font-semibold">{detail.stock.name} · 连续几天一起看</h3><span className="text-xs text-muted-foreground">点击上表股票可切换 · 买入日至买入后第3日</span></div><div className="overflow-x-auto"><table aria-label="单股连续日行情" className="w-full text-sm"><thead className="bg-muted/40 text-xs text-muted-foreground"><tr>{['日期 / 阶段', '开盘', '最低', '最高', '均价', '收盘', '成交量', '放量倍数', '收盘较买价'].map(t => <th key={t} className={td}>{t}</th>)}</tr></thead><tbody>{detailDays.map((d, j) => {
        const ix = detail.stock.bars.findIndex(b => b.date === d), b = ix >= 0 ? detail.stock.bars[ix] : undefined, f = ix >= 0 ? features(detail.stock.bars, ix) : null;
        const r = change(b?.close, detail.entry?.close);
        return <tr key={d} className="border-t border-border"><td className={td}>{d}<span className="mt-1 block text-xs text-muted-foreground">{['尾盘买入 D0', '隔日 D1', '买入后 D2', '买入后 D3'][j]}</span></td>{(['open', 'low', 'high', 'average', 'close'] as const).map(key => <td key={key} className={td}>{price(b?.[key])}</td>)}<td className={td}>{volume(b)}</td><td className={td}>{mult(f?.vr)}</td><td className={`${td} ${color(r)}`}>{pct(r)}</td></tr>;
      })}</tbody></table></div></div>}
    </>}
  </section>;
}
