import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, CheckCircle2, RefreshCw } from 'lucide-react';
import { authHeaders } from '@/lib/api';
import { beijingDate } from '@/features/workbench/GuidedEntry';
import { WorkbenchNav } from '@/features/workbench/WorkbenchNav';

type Kind = 'plan' | 'evidence' | 'link' | 'review';
type Item = { id: string; kind: Kind; record_id: string; name: string; code: string; date: string; overdue: boolean; detail: string };
type Tasks = { today: string; revision: number; counts: Record<Kind, number>; items: Item[] };
const kinds: { key: Kind; label: string; action: string; hint: string }[] = [
  { key: 'plan', label: '到期计划', action: '复查计划', hint: '检查判断与条件，保存下次复查日期' },
  { key: 'evidence', label: '待核验证据', action: '核验证据', hint: '按投资卡汇总，查阅来源后更新状态' },
  { key: 'link', label: '待关联成交', action: '处理关联', hint: '关联当前投资卡或明确无事前计划' },
  { key: 'review', label: '待复盘周期', action: '填写复盘', hint: '清仓后回顾执行情况与改进动作' },
];
function destination(item: Item) {
  return item.kind === 'plan' || item.kind === 'evidence'
    ? '/investment-workbench?' + new URLSearchParams({ card: item.record_id, focus: item.kind, from: 'tasks' })
    : '/investment-workbench/journal?' + new URLSearchParams({ cycle: item.record_id, focus: item.kind, from: 'tasks' });
}
export function InvestmentTasksPage() {
  const [data, setData] = useState<Tasks | null>(null);
  const [filter, setFilter] = useState<Kind | 'all'>('all');
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [updated, setUpdated] = useState('');
  const active = useRef<AbortController | null>(null);
  const loadedDay = useRef('');
  const refresh = useCallback(async () => {
    active.current?.abort();
    const controller = new AbortController(); active.current = controller;
    setLoading(true); setError('');
    try {
      const response = await fetch('/api/workbench/journal/tasks', { headers: authHeaders(), signal: controller.signal });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '待办读取失败');
      if (controller.signal.aborted) return;
      setData(result); loadedDay.current = result.today;
      setUpdated(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '待办读取失败'); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }, []);
  useEffect(() => {
    void refresh();
    const onFocus = () => { if (document.visibilityState === 'visible') void refresh(); };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible' && loadedDay.current && loadedDay.current !== beijingDate()) void refresh(); }, 30_000);
    return () => { active.current?.abort(); window.clearInterval(timer); window.removeEventListener('focus', onFocus); document.removeEventListener('visibilitychange', onFocus); };
  }, [refresh]);
  const shown = data?.items.filter(item => (filter === 'all' || item.kind === filter) && `${item.name} ${item.code} ${item.detail}`.includes(query.trim())) || [];
  return <div className="mx-auto max-w-[1440px] space-y-5 p-5 lg:p-8">
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-5"><div><p className="text-xs tracking-[.2em] text-primary">BRUCE / DAILY DESK</p><h1 className="mt-2 text-2xl font-semibold">日常待办与复查</h1><p className="mt-2 text-sm text-muted-foreground">先处理到期判断，再补齐证据、关联和复盘。</p></div><button disabled={loading} onClick={() => void refresh()} className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50"><RefreshCw size={15} />{loading ? '正在刷新…' : '刷新待办'}</button></header>
    <WorkbenchNav />
    <p className="text-xs leading-6 text-muted-foreground">待办由当前记录自动生成，处理并保存后返回本页刷新即可更新。到期判断使用北京时间；已撤销卡片不提醒。数量按待办项统计，同一标的可能有多项。</p>
    {error && <div role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-500">{error}。{data ? '下方保留上次结果，可能已过期。' : '尚未取得待办数据，不能据此判断已全部完成。'}<button className="ml-3 underline" onClick={() => void refresh()}>重新读取</button></div>}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{kinds.map(kind => <button key={kind.key} aria-pressed={filter === kind.key} onClick={() => setFilter(filter === kind.key ? 'all' : kind.key)} className={'rounded-xl border bg-card p-5 text-left transition hover:border-primary ' + (filter === kind.key ? 'border-primary ring-1 ring-primary/30' : 'border-border')}><p className="text-sm">{kind.label}</p><p className="my-2 text-3xl font-semibold tabular-nums">{data ? data.counts[kind.key] : '—'}</p><p className="text-xs leading-5 text-muted-foreground">{kind.hint}</p></button>)}</div>
    <section className="rounded-xl border border-border bg-card"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4"><div className="flex flex-wrap items-center gap-3"><h2 className="font-semibold">{filter === 'all' ? '全部待办' : kinds.find(k => k.key === filter)?.label} {data && <span className="text-sm font-normal text-muted-foreground">{shown.length} 项</span>}</h2>{filter !== 'all' && <button className="text-xs text-primary underline" onClick={() => setFilter('all')}>显示全部</button>}</div><input aria-label="搜索待办" placeholder="搜索名称、代码或待办内容" className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm sm:w-64" value={query} onChange={e => setQuery(e.target.value)} /></div>
      <div aria-live="polite" className="px-4 py-3 text-xs text-muted-foreground">{data ? `北京时间 ${data.today} · 最近读取 ${updated}${loading ? ' · 正在更新' : ''}` : loading ? '正在读取本地记录…' : '待办读取失败'}</div>
      {shown.map(item => { const kind = kinds.find(k => k.key === item.kind)!; return <article key={item.id} className="flex flex-wrap items-center justify-between gap-4 border-t border-border p-5"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="rounded bg-primary/10 px-2 py-1 text-xs text-primary">{kind.label}</span>{item.overdue && <span className="text-xs text-orange-500">已逾期</span>}<h3 className="font-semibold">{item.name} <span className="text-xs font-normal text-muted-foreground">{item.code}</span></h3></div><p className="mt-2 text-sm leading-6 text-muted-foreground">{item.detail}</p>{item.date && <p className="mt-1 text-xs text-muted-foreground">{item.kind === 'plan' ? '复查日期' : '周期日期'}：{item.date}</p>}</div><Link aria-label={`${kind.action}：${item.name} ${item.code}`} to={destination(item)} className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-primary/40 px-3 py-2 text-sm text-primary hover:bg-primary/10">{kind.action}<ArrowUpRight size={15} /></Link></article>; })}
      {data && !shown.length && !error && <div className="p-10 text-center"><CheckCircle2 className="mx-auto mb-3 text-primary" size={28} /><p>{data.items.length ? '没有匹配的待办' : '当前没有这四类待办'}</p><p className="mt-2 text-sm text-muted-foreground">{data.items.length ? '试试其他分类或搜索词。' : '未设置日期的草稿、未清仓周期不代表已完成所有研究；可继续查看投资卡。'}</p><Link to="/investment-workbench" className="mt-4 inline-block text-sm text-primary underline">查看投资卡</Link></div>}
    </section>
  </div>;
}
