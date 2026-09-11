import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowUpRight, CalendarDays, Moon, RefreshCw, Sun } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { authHeaders } from '@/lib/api';
import { beijingDate } from '@/features/workbench/GuidedEntry';
import { WorkbenchNav } from '@/features/workbench/WorkbenchNav';
import { BriefSyncButton } from '@/features/workbench/BriefSyncButton';

type Slot = 'morning' | 'evening';
type Brief = { date: string; title: string; body: string; source_title: string; thread_id: string; date_basis: string; observed_at: string; last_seen_at: string; published_at: string | null };
type Entry = {
  slot: Slot; label: string; status: 'available' | 'pending' | 'missing' | 'not_configured'; latest_date: string | null; sync_overdue: boolean; sync_due_at: string | null; sync_grace_minutes: number;
  source: { title?: string; thread_id?: string; last_checked_at?: string; last_success_at?: string; last_error?: string; schedule?: { times: string[] } };
  record: Brief | null;
};
type Day = { date: string; today: string; read_at: string; dates: string[]; slots: Entry[] };
const labels = { available: '已归档', pending: '尚未到产出时间', missing: '尚未取得本期', not_configured: '尚未连接来源' };
const stamp = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '尚无记录';

function readableBody(body: string) {
  // Keep the archived text intact. These source-native references cannot be resolved locally.
  return body.replace(/cite[\s\S]*?/g, '〔引用见原简报〕')
    .replace(/entity([\s\S]*?)/g, (_match, raw: string) => {
      try { const parts: unknown = JSON.parse(raw); return Array.isArray(parts) && typeof parts[1] === 'string' ? parts[1] : '〔实体见原简报〕'; } catch { return '〔实体见原简报〕'; }
    }).replace(/[\s\S]*?/g, '〔附加资料见原简报〕')
    .replace(/::chatgpt-content-reference\{[^}]*\}/g, '');
}

export function InvestmentBriefsPage() {
  const [params, setParams] = useSearchParams();
  const date = params.get('date') || beijingDate();
  const [selected, setSelected] = useState<Slot>('morning');
  const [data, setData] = useState<Day | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const active = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    active.current?.abort();
    const controller = new AbortController(); active.current = controller;
    setLoading(true); setError('');
    try {
      const response = await fetch('/api/workbench/briefs?' + new URLSearchParams({ date }), { headers: authHeaders(), signal: controller.signal });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '简报读取失败');
      if (!controller.signal.aborted) setData(result);
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '简报读取失败'); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }, [date]);
  useEffect(() => {
    setData(null); void refresh();
    const visible = () => { if (document.visibilityState === 'visible') void refresh(); };
    const timer = window.setInterval(visible, 60_000);
    window.addEventListener('focus', visible);
    return () => { active.current?.abort(); window.clearInterval(timer); window.removeEventListener('focus', visible); };
  }, [refresh]);
  const chooseDate = (value: string) => setParams(value ? { date: value } : {});
  const entry = data?.slots.find(item => item.slot === selected);
  const record = entry?.record;

  return <div className="mx-auto max-w-[1440px] space-y-5 p-5 lg:p-8">
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-5">
      <div><p className="text-xs tracking-[.2em] text-primary">BRUCE / DAILY BRIEF</p><h1 className="mt-2 text-2xl font-semibold">每日简报</h1><p className="mt-2 text-sm text-muted-foreground">早间看线索，晚间看变化。按日期回看已有简报。</p></div>
      <button disabled={loading} onClick={() => void refresh()} className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50"><RefreshCw size={15} className={loading ? 'animate-spin' : ''} />{loading ? '正在读取…' : '刷新归档'}</button>
    </header>
    <WorkbenchNav />
    <BriefSyncButton onComplete={() => void refresh()} />
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
      <CalendarDays size={18} className="text-primary" /><label htmlFor="brief-date" className="text-sm">简报日期</label>
      <input id="brief-date" type="date" value={date} onChange={event => chooseDate(event.target.value)} className="rounded-lg border border-border bg-background px-3 py-2 text-sm" />
      <button onClick={() => chooseDate('')} className="text-sm text-primary underline">回到今天</button>
      <select aria-label="已归档日期" value="" onChange={event => chooseDate(event.target.value)} className="rounded-lg border border-border bg-background px-3 py-2 text-sm"><option value="" disabled>查看历史归档</option>{data?.dates.map(day => <option key={day} value={day}>{day}</option>)}</select>
      <span className="text-xs text-muted-foreground sm:ml-auto">北京时间 · 早间约 08:00 / 晚间 22:30</span>
    </div>
    {error && <div role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-500">{error}。{data ? '下方保留上次读取结果，可能已过期。' : '未能读取归档，不能据此判断没有简报。'}<button className="ml-3 underline" onClick={() => void refresh()}>重新读取</button></div>}
    {!data && !error && <p role="status" className="p-8 text-center text-sm text-muted-foreground">正在读取本地简报…</p>}
    <div className="grid gap-4 md:grid-cols-2">{data?.slots.map(item => {
      const Icon = item.slot === 'morning' ? Sun : Moon;
      return <section key={item.slot} className={'rounded-xl border bg-card p-5 ' + (selected === item.slot ? 'border-primary ring-1 ring-primary/20' : 'border-border')}>
        <button onClick={() => setSelected(item.slot)} aria-pressed={selected === item.slot} className="flex w-full items-center justify-between gap-3 text-left"><span className="flex items-center gap-2 font-semibold"><Icon size={20} className="text-primary" />{item.label}</span><span className={'rounded-full px-3 py-1 text-xs ' + (item.status === 'available' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500')}>{labels[item.status]}</span></button>
        <p className="mt-4 min-h-6 text-sm">{item.record?.title || (item.status === 'pending' ? '产出后会同步到这里，可先回看上一期。' : '目前没有该日期的正文，已有归档仍可回看。')}</p>
        <div className="mt-3 space-y-1 text-xs leading-5 text-muted-foreground"><p>来源：{item.source.title || '未配置'}</p><p>最近检查：{stamp(item.source.last_checked_at)}</p><p>同步计划：{item.source.schedule ? item.source.schedule.times.join(' / ') + '，需本机 Codex 可运行' : '尚未配置自动同步'}</p></div>
        {item.source.last_error && <p role="alert" className="mt-3 rounded-lg bg-red-500/10 p-3 text-xs leading-5 text-red-500">最近同步失败：{item.source.last_error}。保留已归档正文。</p>}
        {item.sync_overdue && !item.source.last_error && <p className="mt-3 text-xs text-amber-500">同步检查已逾期：{stamp(item.sync_due_at)} 的计划在 {item.sync_grace_minutes} 分钟宽限后仍无检查记录。此前的手动检查不代表本次计划已运行。</p>}
        <div className="mt-4 flex flex-wrap gap-4 text-sm"><button onClick={() => setSelected(item.slot)} className="text-primary underline">{item.record ? '阅读本期' : '查看状态'}</button>{item.latest_date && item.latest_date !== date && <button className="text-primary underline" onClick={() => { setSelected(item.slot); chooseDate(item.latest_date!); }}>最近归档 {item.latest_date}</button>}{item.source.thread_id && <a href={'https://chatgpt.com/c/' + item.source.thread_id} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-muted-foreground hover:text-primary">打开来源任务<ArrowUpRight size={14} /></a>}</div>
      </section>;
    })}</div>
    {entry && <section className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="border-b border-border p-5"><h2 className="font-semibold">{date} · {entry.label}</h2><p className="mt-2 text-xs leading-6 text-muted-foreground">原简报内容未经本模块独立核验。同步不会更新原有行情，也不会自动改动投资计划。</p></div>
      {record ? <>
        <div className="border-b border-border bg-background/40 px-5 py-3 text-xs leading-6 text-muted-foreground"><p>首次获取：{stamp(record.observed_at)} · 最近确认：{stamp(record.last_seen_at)}</p><p>原文发布时间：{record.published_at ? stamp(record.published_at) : '来源未提供逐篇时间'} · 日期依据：{record.date_basis}</p><p>文中的引用编号请到原简报核对；原有网页链接保留。</p></div>
        <article className="prose prose-sm max-w-none break-words p-5 text-foreground prose-a:text-primary prose-pre:overflow-x-auto dark:prose-invert lg:p-8"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
          a: ({ href, children }) => href && /^https?:\/\//i.test(href) ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>,
          img: ({ alt }) => <span className="text-muted-foreground">〔{alt || '原文图片'}：请到来源任务查看〕</span>,
          table: ({ children }) => <div className="overflow-x-auto"><table>{children}</table></div>,
        }}>{readableBody(record.body)}</ReactMarkdown></article>
      </> : <div className="p-10 text-center"><p>{labels[entry.status]}</p><p className="mt-3 text-sm text-muted-foreground">点击“同步早晚简报”检查来源新内容；“刷新归档”只重新读取本地已保存内容。</p>{entry.latest_date && <button className="mt-4 text-sm text-primary underline" onClick={() => chooseDate(entry.latest_date!)}>阅读最近一期（{entry.latest_date}）</button>}</div>}
    </section>}
    <footer className="flex flex-wrap justify-between gap-3 text-xs leading-6 text-muted-foreground"><span>页面读取时间：{stamp(data?.read_at)}。断网、休眠或来源不可读时，归档可能延迟。</span><Link to="/investment-workbench/tasks" className="text-primary underline">查看今日待办与复查 →</Link></footer>
  </div>;
}
