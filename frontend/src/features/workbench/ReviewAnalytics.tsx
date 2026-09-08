import { useEffect, useState } from 'react';
import { authHeaders } from '@/lib/api';

type Summary = { label: string; count: number; wins: number; losses: number; zeros: number; win_rate: number | null; payoff_ratio: number | null; gross_pnl: number; cycle_ids: string[] };
type Analytics = { total: Summary; strategies: Summary[]; executions: Summary[]; errors: { label: string; count: number; primary_loss: number; cycle_ids: string[] }[]; excluded_open: number; excluded_incomplete: number };
const money = (n: number) => n.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
export function ReviewAnalytics({ revision, onInspect }: { revision: number; onInspect: (label: string, ids: string[]) => void }) {
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError('');
    if (start && end && start > end) { setError('开始日期不能晚于结束日期'); return; }
    const query = new URLSearchParams();
    if (start) query.set('start', start);
    if (end) query.set('end', end);
    fetch('/api/workbench/journal/analytics?' + query, { headers: authHeaders(), signal: controller.signal })
      .then(async r => { const value = await r.json(); if (!r.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '统计读取失败'); return value; })
      .then(setData).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [revision, start, end]);
  const table = (title: string, rows: Summary[]) => <div className="overflow-auto"><h4 className="my-3 text-sm font-semibold">{title}</h4><table className="w-full whitespace-nowrap text-left text-xs"><thead className="text-muted-foreground"><tr>{['分组', '周期数', '胜率', '平均盈亏比', '毛收益（元）', ''].map((x, i) => <th key={i} className="p-2">{x}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.label} className="border-t border-border"><td className="p-2">{row.label}</td><td>{row.count}</td><td>{row.win_rate === null ? '—' : (row.win_rate * 100).toFixed(1) + '%'}</td><td>{row.payoff_ratio === null ? '—' : row.payoff_ratio.toFixed(2)}</td><td>{money(row.gross_pnl)}</td><td><button className="p-2 text-primary hover:underline" onClick={() => onInspect(title + ' · ' + row.label, row.cycle_ids)}>明细</button></td></tr>)}</tbody></table></div>;
  return <section className="rounded-xl border border-border bg-card p-5"><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">复盘统计</h3><div className="flex flex-wrap gap-3 text-xs"><label>清仓起日 <input aria-label="清仓起日" type="date" className="rounded border border-border bg-background p-2" value={start} onChange={e => setStart(e.target.value)} /></label><label>清仓止日 <input aria-label="清仓止日" type="date" className="rounded border border-border bg-background p-2" value={end} onChange={e => setEnd(e.target.value)} /></label><button className="text-primary" onClick={() => { setStart(''); setEnd(''); }}>全部日期</button></div></div>
    <p className="mt-3 text-xs leading-6 text-muted-foreground">按清仓日期筛选（含首尾两日）。只统计历史完整的清仓周期；策略使用当前投资卡分类，执行情况来自本人复盘。胜率＝盈利周期数／全部纳入周期数，含零收益周期；平均盈亏比＝平均盈利金额／平均亏损金额绝对值，无盈利或无亏损时显示“—”。金额未计费用，样本不代表未来表现。</p>
    {error ? <p role="alert" className="mt-3 text-sm text-red-500">{error}</p> : !data ? <p className="mt-3 text-sm">正在读取统计…</p> : <><p className="mt-3 text-sm">纳入 {data.total.count} 个周期：盈利 {data.total.wins} / 亏损 {data.total.losses} / 零收益 {data.total.zeros} · 毛收益 {money(data.total.gross_pnl)} 元</p><p className="mt-2 text-xs text-muted-foreground">全历史排除：持有中 {data.excluded_open} 个、历史不完整的清仓周期 {data.excluded_incomplete} 个。</p>{!data.total.count ? <p className="mt-4 rounded-lg bg-muted p-4 text-sm">当前日期范围暂无完整清仓周期，完成成交记录后会自动生成统计。</p> : <>{table('按策略', data.strategies)}{table('按执行情况', data.executions)}<h4 className="mb-2 mt-5 text-sm font-semibold">错误标签</h4><p className="text-xs text-muted-foreground">多选标签分别计次；主要错误对应亏损仅计一次，是本人归因，不代表因果结论。</p>{data.errors.length ? <div className="mt-3 flex flex-wrap gap-3">{data.errors.map(row => <button key={row.label} className="rounded-lg border border-border p-3 text-left text-xs hover:border-primary" onClick={() => onInspect(row.label, row.cycle_ids)}><strong>{row.label}</strong><p className="mt-2">出现 {row.count} 次 · 主要错误对应亏损 {money(row.primary_loss)} 元</p><p className="mt-2 text-primary">查看明细 →</p></button>)}</div> : <p className="mt-3 text-xs">尚无已保存的错误标签。</p>}</>}</>}
  </section>;
}
