import { ReviewAnalytics } from './ReviewAnalytics';
import { useEffect, useState } from 'react';
import { Link, useBlocker, useSearchParams } from 'react-router-dom';
import { authHeaders } from '@/lib/api';
import { beijingDate } from './GuidedEntry';

type Review = { execution: string; errors: string[]; primary_error: string; lesson: string; next_action: string };
type Trade = { id: string; side: string; date: string; name: string; code: string; quantity: number; price: number; pnl?: number };
type Cycle = { id: string; code: string; name: string; start: string; end: string; trades: Trade[]; remaining: number; complete: boolean; warnings: string[]; gross_pnl: number | null; card_id: string | null; strategy: string; link_status: string; status: string; review: Review | null };
type Journal = { revision: number; cycles: Cycle[]; cards: { id: string; name: string; code: string; strategy: string }[]; holdings: { code: string; shares: number; cost: number }[]; error_labels: Record<string, string>; untracked_holdings: string[]; stats: { completed: number; pending_review: number; gross_pnl: number; incomplete: number } };
const btn = 'rounded-lg border border-border px-3 py-2 text-sm hover:border-primary disabled:opacity-40';
const input = 'mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-primary outline-none';
const emptyReview = (): Review => ({ execution: '无法核实', errors: [], primary_error: '', lesson: '', next_action: '' });
const emptyTrade = () => ({ trade_id: crypto.randomUUID().replace(/-/g, ''), side: 'buy', code: '', name: '', quantity: '', price: '', date: beijingDate() });
class JournalError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch('/api/workbench/journal' + path, { method: body === undefined ? 'GET' : 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const data = await response.json();
  if (!response.ok) throw new JournalError(typeof data.detail === 'string' ? data.detail : data.detail?.map((x: { msg: string }) => x.msg).join('；') || '操作失败', response.status);
  return data;
}
const money = (n: number | null) => n === null ? '暂不统计' : n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function TradeJournal() {
  const [params] = useSearchParams();
  const sourceCycle = params.get('cycle') || '';
  const focusTarget = params.get('focus') || '';
  const [data, setData] = useState<Journal | null>(null);
  const [selected, setSelected] = useState('');
  const [review, setReview] = useState<Review>(emptyReview);
  const [link, setLink] = useState('');
  const [inspection, setInspection] = useState<{ label: string; ids: string[] } | null>(null);
  const [filter, setFilter] = useState('全部');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [trade, setTrade] = useState(emptyTrade);
  const [showForm, setShowForm] = useState(false);
  const [preview, setPreview] = useState(false);
  const [retryLocked, setRetryLocked] = useState(false);
  const [reviewDirty, setReviewDirty] = useState(false);
  const [linkDirty, setLinkDirty] = useState(false);
  const dirty = reviewDirty || linkDirty;
  const [tradeDirty, setTradeDirty] = useState(false);
  const blocker = useBlocker(dirty || tradeDirty);
  const cycle = data?.cycles.find(c => c.id === selected);
  const refresh = () => request<Journal>('').then(setData);
  useEffect(() => {
    let cancelled = false;
    request<Journal>('').then(result => {
      if (cancelled) return;
      setData(result);
      if (sourceCycle) {
        const found = result.cycles.find(c => c.id === sourceCycle);
        if (found) {
          setSelected(found.id); setReview(found.review || emptyReview()); setLink(found.card_id || '');
          setReviewDirty(false); setLinkDirty(false);
          setNotice('已打开指定成交周期。处理并保存后，可从上方导航返回日常待办。');
        } else { setSelected(''); setError('目标成交周期已不存在，请返回日常待办刷新。'); }
      }
    }).catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [sourceCycle]);
  useEffect(() => {
    if (!selected || selected !== sourceCycle) return;
    const target = document.getElementById(focusTarget === 'review' ? 'journal-review' : 'journal-link');
    target?.scrollIntoView({ block: 'center' }); target?.focus({ preventScroll: true });
  }, [selected, sourceCycle, focusTarget]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty || tradeDirty) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, tradeDirty]);
  function choose(c: Cycle) {
    if (dirty && !window.confirm('当前复盘或关联选择尚未保存，放弃修改？')) return;
    setSelected(c.id); setReview(c.review || emptyReview()); setLink(c.card_id || ''); setReviewDirty(false); setLinkDirty(false); setError(''); setNotice('');
  }
  async function save(path: string, body: unknown, message: string) {
    setBusy(true); setError(''); setNotice('');
    try { setData(await request<Journal>(path, body)); if (path === '/review') setReviewDirty(false); else setLinkDirty(false); setNotice(message); }
    catch (e) { setError(e instanceof Error ? e.message : '保存失败'); }
    finally { setBusy(false); }
  }
  async function record() {
    setBusy(true); setError(''); setNotice(''); setRetryLocked(true);
    try {
      await request('/record', { ...trade, quantity: Number(trade.quantity) });
      setTrade(emptyTrade()); setTradeDirty(false); setPreview(false); setRetryLocked(false); setShowForm(false);
      setNotice('成交已记入现有台账并同步持仓。请在对应周期选择投资卡关联；不会自动确认事前计划。');
      await refresh().catch(() => setError('成交已写入，但列表刷新失败，请点击刷新成交。'));
    } catch (e) { if (e instanceof JournalError && e.status < 500) setRetryLocked(false); setError((e instanceof Error ? e.message : '记账失败') + '。可用相同内容重试，系统按交易 ID 去重。'); }
    finally { setBusy(false); }
  }
  const filtered = data?.cycles.filter(c => (!inspection || inspection.ids.includes(c.id)) && (filter === '全部' || (filter === '待复盘' ? !!c.end && !c.review : c.status === filter))) || [];
  const formError = !/^\d{6}$/.test(trade.code) ? '请填写六位证券代码' : !trade.name.trim() ? '请填写证券名称' : !Number.isInteger(Number(trade.quantity)) || Number(trade.quantity) <= 0 ? '成交数量须为正整数' : !Number.isFinite(Number(trade.price)) || Number(trade.price) <= 0 ? '成交价格须为正数' : !trade.date || trade.date > beijingDate() ? '成交日期不能晚于今天' : '';
  return <div className="space-y-5">
    {blocker.state === 'blocked' && <div role="alertdialog" className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"><div className="rounded-xl bg-card p-6"><h2>有未保存的成交或复盘内容</h2><div className="mt-4 flex gap-3"><button className={btn} onClick={() => blocker.reset()}>继续编辑</button><button className={btn} onClick={() => blocker.proceed()}>放弃并离开</button></div></div></div>}
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-semibold">成交与复盘</h2><p className="mt-2 text-sm text-muted-foreground">默认本地账户 · 按实际成交补记 · 毛收益未计费用</p></div><div className="flex gap-2"><button className={btn} disabled={busy} onClick={() => refresh().catch(e => setError(e.message))}>刷新成交</button><button className={btn + ' bg-primary text-primary-foreground'} onClick={() => setShowForm(!showForm)}>{showForm ? '收起录入' : '补录实际成交'}</button></div></div>
    <div aria-live="polite">{error && <p role="alert" className="rounded-lg bg-red-500/10 p-3 text-sm text-red-500">{error}</p>}{notice && <p role="status" className="rounded-lg bg-primary/10 p-3 text-sm text-primary">{notice}</p>}</div>
    {showForm && <section className="rounded-xl border border-primary/40 bg-card p-5"><h3 className="font-semibold">补录已经发生的成交</h3><p className="my-3 text-xs leading-6 text-muted-foreground">保存会更新现有持仓和私有台账；此处不向券商下单。请按日期顺序录入，不要重复补录已存在的成交。费用暂未纳入。卖出成本采用本地当前持仓成本。</p>
      <fieldset disabled={busy || retryLocked} className="grid gap-4 sm:grid-cols-3"><label className="text-xs">方向<select className={input} value={trade.side} onChange={e => { setTrade({ ...trade, side: e.target.value }); setTradeDirty(true); }}>{['buy', 'sell'].map(s => <option key={s} value={s}>{s === 'buy' ? '买入 / 加仓' : '卖出 / 减仓'}</option>)}</select></label>{(['code', 'name', 'quantity', 'price', 'date'] as const).map((key, i) => <label key={key} className="text-xs">{['证券代码', '证券名称', '实际成交数量（股）', '实际成交价格（元）', '成交日期'][i]}<input className={input} type={key === 'date' ? 'date' : key === 'quantity' || key === 'price' ? 'number' : 'text'} step={key === 'quantity' ? '1' : 'any'} value={trade[key]} onChange={e => { setTrade({ ...trade, [key]: e.target.value }); setTradeDirty(true); setPreview(false); }} /></label>)}</fieldset>
      {formError && <p className="mt-3 text-xs text-orange-500">{formError}</p>}
      {!preview ? <button className={btn + ' mt-4'} disabled={!!formError || busy} onClick={() => setPreview(true)}>核对本次记账</button> : <div className="mt-4 rounded-lg border border-orange-500/40 p-4"><p className="text-sm">将记录 {trade.date} {trade.side === 'buy' ? '买入' : '卖出'} {trade.name}（{trade.code}）{trade.quantity} 股，成交价 {trade.price} 元，名义成交额 {money(Number(trade.quantity) * Number(trade.price))} 元。</p><div className="mt-3 flex gap-3"><button className={btn + ' bg-primary text-primary-foreground'} disabled={busy} onClick={record}>{busy ? '正在记账…' : retryLocked ? '使用相同交易 ID 重试' : '确认写入本地台账'}</button>{!retryLocked && <button className={btn} onClick={() => setPreview(false)}>返回修改</button>}</div>{retryLocked && <p className="mt-2 text-xs text-muted-foreground">为避免重复记账，重试前不修改本次内容。如需放弃，请先刷新成交核对是否已写入。</p>}</div>}
    </section>}
    {data && <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[['完整清仓周期', data.stats.completed], ['待复盘', data.stats.pending_review], ['完整周期毛收益（元）', money(data.stats.gross_pnl)], ['历史不完整周期', data.stats.incomplete]].map(([label, value]) => <div key={label} className="rounded-xl border border-border p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-2 text-xl font-semibold">{value}</p></div>)}</div>}
    {data && data.untracked_holdings.length > 0 && <p className="rounded-lg bg-orange-500/10 p-3 text-sm text-orange-500">{data.untracked_holdings.length} 只现有持仓尚无成交历史（{data.untracked_holdings.join('、')}）。请勿把期初持仓再补录成买入，以免重复增加数量。</p>}
    {data && <ReviewAnalytics revision={data.revision + data.cycles.reduce((n, c) => n + c.trades.length, 0)} onInspect={(label, ids) => { if (dirty && !window.confirm('有未保存的复盘或关联修改，放弃后查看统计明细？')) return; setSelected(''); setReviewDirty(false); setLinkDirty(false); setInspection({ label, ids }); setFilter('全部'); document.getElementById('journal-cycles')?.scrollIntoView({ behavior: 'smooth' }); }} />}
    {inspection && <p className="rounded-lg bg-primary/10 p-3 text-sm">当前明细：{inspection.label}（{inspection.ids.length} 个周期） <button className="ml-3 text-primary underline" onClick={() => setInspection(null)}>清除统计筛选</button></p>}
    <div id="journal-cycles" className="grid items-start gap-5 xl:grid-cols-[280px_minmax(0,1fr)]"><aside className="space-y-3"><select aria-label="交易周期筛选" className={input} value={filter} onChange={e => setFilter(e.target.value)}>{['全部', '持有中', '已清仓', '待复盘'].map(x => <option key={x}>{x}</option>)}</select>{filtered.map(c => <button key={c.id} className={'w-full rounded-xl border p-4 text-left ' + (selected === c.id ? 'border-primary bg-primary/5' : 'border-border')} onClick={() => choose(c)}><strong>{c.name} <span className="text-xs font-normal">{c.code}</span></strong><p className="mt-2 text-xs text-muted-foreground">{c.start} → {c.end || '持有中'}</p><p className="mt-2 text-xs">{c.status} · {c.complete ? c.review ? '已复盘' : '待复盘/跟踪' : '历史不完整'}</p><p className="mt-2 text-xs text-primary">{c.link_status}</p></button>)}{data && !filtered.length && <p className="py-8 text-center text-sm text-muted-foreground">暂无对应成交周期，可先补录实际成交。</p>}</aside>
    {!cycle || !data ? <div className="rounded-xl border border-dashed border-border p-12 text-center text-muted-foreground">{data ? '选择一个周期，关联研究并复盘。' : error ? '读取失败，请刷新成交。' : '正在读取本地成交…'}</div> : <section className="space-y-5 rounded-xl border border-border bg-card p-5"><h3 className="text-lg font-semibold">{cycle.name} · {cycle.status}</h3>{cycle.review && <p className="rounded-lg bg-primary/10 p-3 text-sm">{cycle.gross_pnl === null ? '收益暂不统计' : cycle.gross_pnl > 0 ? '盈利' : cycle.gross_pnl < 0 ? '亏损' : '零收益'} · {cycle.review.execution}（本人复盘）</p>}{cycle.warnings.length > 0 && <p className="rounded-lg bg-orange-500/10 p-3 text-sm text-orange-500">{cycle.warnings.join('；')}。可记录复盘，不计入完整周期收益统计。</p>}
      <p className="text-sm">周期剩余数量：{cycle.remaining} 股 · 已实现毛收益：{money(cycle.gross_pnl)}{cycle.gross_pnl !== null ? ' 元（未计费用）' : ''}</p>
      <fieldset id="journal-link" tabIndex={-1} disabled={busy}><label className="text-sm">关联当前投资卡<select className={input} value={link} onChange={e => { setLink(e.target.value); setLinkDirty(true); }}><option value="">无事前计划 / 仅记账</option>{data.cards.filter(c => c.code === cycle.code).map(c => <option key={c.id} value={c.id}>{c.name} · {c.strategy || '未选策略'}</option>)}</select></label><p className="my-2 text-xs leading-6 text-muted-foreground">当前状态：{cycle.link_status}。关联只建立研究链接，不增减持仓；由于不保存计划历史，不能据此证明成交前已有该计划。新成交需要重新关联。</p><button className={btn} onClick={() => save('/link', { revision: data.revision, cycle_id: cycle.id, card_id: link || null }, '关联已保存，持仓未重复更新')}>保存周期关联</button>{(error || notice) && <p aria-live="polite" className="mt-2 text-sm text-primary">{error || notice}</p>}</fieldset>
      <div className="overflow-auto"><table className="w-full text-left text-sm"><thead className="text-xs text-muted-foreground"><tr>{['日期', '方向', '数量', '成交价', '卖出毛收益'].map(h => <th key={h} className="p-2">{h}</th>)}</tr></thead><tbody>{cycle.trades.map(t => <tr key={t.id} className="border-t border-border"><td className="p-2">{t.date}</td><td>{t.side === 'buy' ? '买入' : '卖出'}</td><td>{t.quantity}</td><td>{t.price}</td><td>{t.side === 'sell' ? money(t.pnl ?? null) : '—'}</td></tr>)}</tbody></table></div>
      {!cycle.end ? <p className="rounded-lg bg-muted/40 p-3 text-sm">持有中的周期先跟踪，清仓后填写周期复盘。</p> : <fieldset id="journal-review" tabIndex={-1} disabled={busy} className="space-y-4 border-t border-border pt-5"><h4 className="font-semibold">周期复盘 {dirty && <span className="text-xs text-orange-500">有未保存修改</span>}</h4><label className="block text-sm">执行情况（本人回顾）<select className={input} value={review.execution} onChange={e => { setReview({ ...review, execution: e.target.value }); setReviewDirty(true); }}>{['无法核实', '按计划执行', '偏离计划', '无事前计划'].map(x => <option key={x}>{x}</option>)}</select></label><p className="text-xs text-muted-foreground">错误标签可多选；不因盈利或亏损自动判定是否违规。</p><div className="flex flex-wrap gap-2">{Object.entries(data.error_labels).map(([id, label]) => <button key={id} aria-pressed={review.errors.includes(id)} className={btn + (review.errors.includes(id) ? ' border-primary bg-primary/10 text-primary' : '')} onClick={() => { const errors = review.errors.includes(id) ? review.errors.filter(x => x !== id) : [...review.errors, id]; setReview({ ...review, errors, primary_error: errors.includes(review.primary_error) ? review.primary_error : '' }); setReviewDirty(true); }}>{id} {label}</button>)}</div>{review.errors.length > 0 && <label className="block text-sm">主要错误 *<select className={input} value={review.primary_error} onChange={e => { setReview({ ...review, primary_error: e.target.value }); setReviewDirty(true); }}><option value="">请选择一个主要错误</option>{review.errors.map(id => <option key={id} value={id}>{id} {data.error_labels[id]}</option>)}</select></label>}{(['lesson', 'next_action'] as const).map((key, i) => <label key={key} className="block text-sm">{i === 0 ? '复盘结论 *' : '下次改进动作'}<textarea className={input} rows={3} value={review[key]} onChange={e => { setReview({ ...review, [key]: e.target.value }); setReviewDirty(true); }} /></label>)}<button className={btn + ' bg-primary text-primary-foreground'} onClick={() => { if (!review.lesson.trim() || review.errors.length > 0 && !review.primary_error) { setError('请填写复盘结论，并为已选错误指定一个主要错误'); return; } void save('/review', { revision: data.revision, cycle_id: cycle.id, review }, '复盘已保存'); }}>{busy ? '正在保存…' : '保存复盘'}</button>{(error || notice) && <p aria-live="polite" className={'text-sm ' + (error ? 'text-red-500' : 'text-primary')}>{error || notice}</p>}</fieldset>}
    {params.get('from') === 'tasks' && <Link to="/investment-workbench/tasks" className="inline-block text-sm text-primary underline">← 返回日常待办</Link>}
    </section>}</div>
  </div>;
}
