import { WorkbenchNav } from '@/features/workbench/WorkbenchNav';
import { useEffect, useRef, useState } from 'react';
import { Link, useBlocker, useSearchParams } from 'react-router-dom';
import { Plus, Save, Trash2, Download, Upload, ClipboardCheck, Search } from 'lucide-react';
import { authHeaders } from '@/lib/api';
import { GuidedEntry, guidedDefaults, validationIssues, beijingDate, type Catalog } from '@/features/workbench/GuidedEntry';

import type { Card, Snapshot } from '@/features/workbench/types';
const blank = (): Card => ({ ...structuredClone(guidedDefaults), id: crypto.randomUUID().replace(/-/g, ''), name: '', code: '', theme: '', status: '草稿', evidence: [], updated_at: '', confirmed_at: '' });
const control = 'mt-1.5 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-1 focus:ring-primary';
const button = 'inline-flex items-center justify-center gap-2 rounded-lg border border-border px-3 py-2 text-sm transition hover:bg-muted disabled:opacity-40';
async function api(path = '', body?: unknown): Promise<Snapshot> {
  const r = await fetch('/api/workbench' + path, { method: body === undefined ? 'GET' : 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const data = await r.json();
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail) ? data.detail.map((x: { msg: string }) => x.msg).join('；') : '请求失败');
  return data;
}
const today = beijingDate;
const due = (c: Card) => c.status !== '已撤销' && !!c.review_date && c.review_date <= today();

export function InvestmentWorkbench() {
  const [params] = useSearchParams();
  const sourceCard = params.get('card') || '';
  const focusTarget = params.get('focus') || '';
  const sourceCode = params.get('code') || '';
  const sourceName = params.get('name') || '';
  const [state, setState] = useState<Snapshot>({ revision: 0, cards: [] });
  const [card, setCard] = useState<Card | null>(null);
  const [dirty, setDirty] = useState(false);
  const [ready, setReady] = useState(false);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const blocker = useBlocker(dirty);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [showIssues, setShowIssues] = useState(false);
  const [issueDialogOpen, setIssueDialogOpen] = useState(false);
  const issueDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (issueDialogOpen && !issueDialog.current?.open) issueDialog.current?.showModal();
    if (!issueDialogOpen && issueDialog.current?.open) issueDialog.current?.close();
  }, [issueDialogOpen]);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('全部');
  const [restore, setRestore] = useState<Snapshot | null>(null);
  useEffect(() => {
    let cancelled = false;
    Promise.all([api(), fetch('/api/workbench/catalog', { headers: authHeaders() }).then(async r => { if (!r.ok) throw new Error('选项加载失败，请刷新页面'); return r.json() as Promise<Catalog>; })])
      .then(([s, options]) => {
        if (cancelled) return;
        setState(s); setCatalog(options); setReady(true);
        if (sourceCard) {
          const existing = s.cards.find(c => c.id === sourceCard);
          setCard(existing ? structuredClone(existing) : null);
          setDirty(false);
          if (existing) {
            setQuery(existing.code);
            setMessage(params.get('from') === 'compare' ? '已打开比较中的投资卡。修改并保存后，返回主题比较查看最新内容。' : focusTarget === 'evidence' ? '已打开待核验证据。查阅来源并更新核验状态后，请保存草稿。' : '已打开到期计划。请复查判断与条件，并保存下次复查日期；仍需跟进可保留原日期。');
          } else setError('目标投资卡已不存在，请返回来源页面刷新。');
        } else if (/^\d{6}$/.test(sourceCode)) {
          const existing = s.cards.filter(c => c.code === sourceCode);
          setQuery(sourceCode);
          setCard(existing.length ? structuredClone(existing[0]) : { ...blank(), code: sourceCode, name: sourceName });
          setDirty(!existing.length);
          setMessage(existing.length ? `已打开现有投资卡，同代码共 ${existing.length} 张。` : '已带入名称和代码，请补充研究逻辑后保存。');
        }
      })
      .catch(e => { if (!cancelled) setError(String(e.message)); });
    return () => { cancelled = true; };
  }, [sourceCode, sourceName, sourceCard, focusTarget]);
  useEffect(() => {
    if (!card || card.id !== sourceCard || !['evidence', 'plan'].includes(focusTarget)) return;
    const target = document.getElementById(focusTarget === 'evidence' ? 'wb-evidence' : 'wb-review_date');
    if (target instanceof HTMLDetailsElement) target.open = true;
    target?.scrollIntoView({ block: 'center' });
    target?.focus({ preventScroll: true });
  }, [card?.id, sourceCard, focusTarget]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const discard = () => !dirty || window.confirm('有未保存的内容，确定放弃这些修改？');
  const select = (c: Card) => { if (discard()) { setCard(structuredClone(c)); setDirty(false); setMessage(''); setShowIssues(false); } };
  const change = (patch: Partial<Card>) => { setCard(c => c ? { ...c, ...patch, status: patch.status ?? (c.status === '已确认' ? '草稿' : c.status) } : c); setDirty(true); };
  async function run(action: () => Promise<Snapshot>, success: string, clear = false) {
    setBusy(true); setError(''); setMessage('');
    try { const s = await action(); setState(s); setReady(true); setDirty(false); setMessage(success); if (clear) setCard(null); else if (card) setCard(s.cards.find(c => c.id === card.id) ?? null); return true; }
    catch (e) { setError(e instanceof Error ? e.message : '操作失败'); return false; }
    finally { setBusy(false); }
  }
  const save = (status: string) => card && run(() => api('/save', { revision: state.revision, card: { ...card, status } }), status === '已确认' ? '计划已确认。仅保存当前内容，后续修改会重新检查。' : '已保存到本地');
  const issues = card && catalog ? [
    ...(!card.name.trim() ? [{ label: '股票名称', target: 'wb-name', help: '填写股票名称。' }] : []),
    ...(!/^\d{6}$/.test(card.code) ? [{ label: '六位证券代码', target: 'wb-code', help: '填写完整的六位数字代码。' }] : []),
    ...validationIssues(card, catalog),
  ] : [];
  const locate = (target: string) => {
    const element = document.getElementById(target);
    if (!element) return;
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    element.focus({ preventScroll: true });
    element.classList.add('ring-2', 'ring-orange-500');
    window.setTimeout(() => element.classList.remove('ring-2', 'ring-orange-500'), 2500);
  };
  const confirmPlan = () => {
    if (issues.length) { setShowIssues(true); setIssueDialogOpen(true); return; }
    setShowIssues(false);
    void save('已确认');
  };

  const shown = state.cards.filter(c => `${c.code} ${c.name} ${c.theme}`.includes(query) && (filter === '全部' || (filter === '待复查' ? due(c) : c.status === filter)));
  const field = (key: keyof Card, label: string, multiline = false, type = 'text') => <label className="block text-xs font-medium text-muted-foreground">{label}{multiline ? <textarea rows={3} className={control} value={String(card?.[key] ?? '')} onChange={e => change({ [key]: e.target.value })} /> : <input id={`wb-${key}`} list={key === 'theme' ? 'wb-existing-themes' : undefined} type={type} className={control} value={String(card?.[key] ?? '')} onChange={e => change({ [key]: e.target.value })} />}</label>;
  return <div className="mx-auto max-w-[1440px] space-y-5 p-5 lg:p-8">
    {blocker.state === 'blocked' && <div role="alertdialog" aria-label="未保存修改" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-5"><div className="rounded-xl border border-border bg-card p-6 shadow-xl"><h2 className="font-semibold">有未保存的修改</h2><p className="my-4 text-sm">离开工作台会丢失本次修改。</p><div className="flex gap-3"><button className={button} onClick={() => blocker.reset()}>继续编辑</button><button className={button} onClick={() => blocker.proceed()}>放弃修改并离开</button></div></div></div>}
    <dialog ref={issueDialog} aria-labelledby="wb-confirm-title" onCancel={() => setIssueDialogOpen(false)} className="m-auto w-[min(92vw,520px)] rounded-2xl border border-border bg-card p-6 text-foreground shadow-2xl backdrop:bg-black/60">
      <h2 id="wb-confirm-title" className="text-lg font-semibold">暂不能确认计划：还有 {issues.length} 项未完成</h2>
      <p className="mt-2 text-sm text-muted-foreground">本次尚未保存或确认。请点击下面的缺项，跳转到对应位置补充；也可以关闭提示后保存草稿。</p>
      <div className="my-5 max-h-[50vh] space-y-2 overflow-auto">{issues.map((issue, index) => <button key={`${issue.target}-${index}`} className="flex w-full items-center justify-between gap-3 rounded-lg border border-orange-500/40 p-3 text-left hover:bg-orange-500/10" onClick={() => { issueDialog.current?.close(); setIssueDialogOpen(false); setShowIssues(false); locate(issue.target); }}><span><strong className="block text-sm">{issue.label}</strong><span className="text-xs text-muted-foreground">{issue.help}</span></span><span className="shrink-0 text-sm text-primary">去填写 →</span></button>)}</div>
      <button className={button + ' w-full'} onClick={() => setIssueDialogOpen(false)}>关闭提示，继续编辑</button>
    </dialog>
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-5">
      <div><p className="mb-2 text-xs tracking-[.2em] text-primary">BRUCE / INVESTMENT JOURNAL</p><h1 className="text-2xl font-semibold">投资工作台</h1><p className="mt-2 text-sm text-muted-foreground">把研究写清楚，让下一次决策有据可查。</p></div>
      <div className="flex gap-2"><button className={button} disabled={!ready || busy} onClick={() => { const url = URL.createObjectURL(new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = `workbench-${today()}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }}><Download size={15} />导出已保存记录</button>
      <label className={button + ' cursor-pointer'}><Upload size={15} />恢复<input aria-label="选择备份文件" type="file" accept=".json" className="hidden" disabled={!ready || busy} onChange={async e => { const file = e.target.files?.[0]; e.target.value = ''; if (!file) return; try { if (file.size > 10_000_000) throw new Error('文件不能超过 10 MB'); const s = JSON.parse(await file.text()); if (!Array.isArray(s.cards) || !Number.isInteger(s.revision)) throw new Error('不是工作台备份文件'); setRestore(s); setError(''); } catch (err) { setError(err instanceof Error ? err.message : '读取失败'); } }} /></label></div>
    </header>
    <WorkbenchNav />
    <div className="grid grid-cols-3 gap-3">{[['研究卡片', state.cards.length], ['待复查', state.cards.filter(due).length], ['待核验证据', state.cards.flatMap(c => c.evidence).filter(e => e.status === '未核验').length]].map(([label, value]) => <div key={label} className="rounded-xl border border-border bg-card px-5 py-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p></div>)}</div>
    <div aria-live="polite" className="min-h-6 text-sm">{error ? <span role="alert" className="text-red-500">{error} <button className="underline" onClick={() => { if (discard()) window.location.reload(); }}>重新加载</button></span> : <span className="text-primary">{message || '本地保存 · 仅保留当前记录 · 风险额度未启用'}</span>}</div>
    {restore && <div className="rounded-xl border border-primary bg-primary/5 p-4"><p>备份包含 {restore.cards.length} 张卡片，将替换当前 {state.cards.length} 张卡片。包含工作台关联与复盘；不包含原始成交文件。现有持仓与成交不受影响。</p><div className="mt-3 flex gap-2"><button className={button} disabled={busy} onClick={async () => { if (discard() && await run(() => api('/restore', { revision: state.revision, snapshot: restore }), '已恢复备份', true)) setRestore(null); }}>确认替换工作台记录</button><button className={button} onClick={() => setRestore(null)}>取消</button></div></div>}
    <div className="grid items-start gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
      <aside className="space-y-3"><button disabled={!ready || busy} className={button + ' w-full bg-primary text-primary-foreground hover:bg-primary/90'} onClick={() => select(blank())}><Plus size={16} />新建投资卡</button><div className="relative"><Search className="absolute left-3 top-3 text-muted-foreground" size={15} /><input aria-label="搜索卡片" placeholder="名称、代码或主题" className={control + ' !mt-0 pl-9'} value={query} onChange={e => setQuery(e.target.value)} /></div><select aria-label="筛选状态" className={control} value={filter} onChange={e => setFilter(e.target.value)}>{['全部', '待复查', '草稿', '已确认', '已撤销'].map(x => <option key={x}>{x}</option>)}</select>
      {!ready ? <p className="py-8 text-center text-sm text-muted-foreground">{error ? '连接失败，请重新加载' : '正在读取本地记录…'}</p> : shown.length === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">{state.cards.length ? '没有匹配的卡片' : '从一个正在研究的标的开始。'}</p> : shown.map(c => <button key={c.id} disabled={busy} onClick={() => select(c)} className={'w-full rounded-xl border p-4 text-left transition ' + (card?.id === c.id ? 'border-primary bg-primary/5' : 'border-border bg-card hover:border-primary/50')}><div className="flex items-center justify-between gap-2"><strong>{c.name}</strong><span className="text-xs text-muted-foreground">{c.code}</span></div><div className="mt-2 text-xs text-muted-foreground">{c.strategy} · {c.theme || '未填写主题'}</div><div className="mt-3 flex justify-between text-xs"><span className="text-primary">{c.status}</span>{due(c) && <span className="text-orange-500">需要复查</span>}</div></button>)}</aside>
      {!card ? <section className="flex min-h-[430px] flex-col items-center justify-center rounded-2xl border border-dashed border-border px-8 text-center"><ClipboardCheck size={38} className="mb-5 text-primary" /><h2 className="text-xl font-medium">先记录判断，再检查计划</h2><p className="mt-3 max-w-sm text-sm leading-7 text-muted-foreground">选择左侧投资卡，或新建一张。记录事实依据、反证和入退场条件；草稿可以随时保存。</p></section> : <fieldset disabled={busy} className="min-w-0 rounded-2xl border border-border bg-card p-5 lg:p-7">
      <div className="mb-6 flex items-center justify-between border-b border-border pb-4"><h2 className="text-lg font-semibold">{card.name || '新的投资卡'} <span className="ml-2 text-xs font-normal text-primary">{dirty ? '有未保存修改' : card.status}</span></h2><span className="text-xs text-muted-foreground">{card.updated_at ? `保存于 ${new Date(card.updated_at).toLocaleString('zh-CN')}` : '尚未保存'}</span></div>
      <div className="grid gap-4 sm:grid-cols-3">{field('name', '股票名称 *')}{field('code', '六位证券代码 *')}{field('theme', '研究主题')}</div>
      <datalist id="wb-existing-themes">{[...new Set(state.cards.map(c => c.theme.trim()).filter(Boolean))].sort().map(theme => <option key={theme} value={theme} />)}</datalist>
      <p className="mt-2 text-xs text-muted-foreground">研究主题可选择已有名称或填写新主题，用于主题与标的比较分组。</p>
      {catalog && <GuidedEntry card={card} catalog={catalog} change={change} notify={setMessage} />}
      <details id="wb-evidence" tabIndex={-1} className="mt-6 border-t border-border pt-5"><summary className="mb-4 cursor-pointer text-sm font-semibold">证据与来源 · {card.evidence.length} 条 / {card.evidence.filter(e => e.status === '未核验').length} 条待核验</summary><div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-semibold">证据记录</h3><button className={button} onClick={() => change({ evidence: [...card.evidence, { title: '', url: '', claim: '', published_at: '', status: '未核验' }] })}><Plus size={14} />添加证据</button></div>{card.evidence.length === 0 && <p className="text-sm text-muted-foreground">尚无证据，研究判断仍需核验。</p>}{card.evidence.map((ev, i) => <div key={i} className="mb-3 space-y-3 rounded-lg border border-border bg-background/50 p-4"><div className="flex items-center justify-between"><span className="text-xs text-muted-foreground">证据 {i + 1}</span><button aria-label={`删除证据 ${i + 1}`} onClick={() => change({ evidence: card.evidence.filter((_, n) => n !== i) })}><Trash2 size={14} /></button></div>{(['title', 'url', 'published_at', 'claim'] as const).map((key, n) => <label key={key} className="block text-xs text-muted-foreground">{['来源标题', '来源链接或文件位置', '首次公开时间（可注明仅日期或未知）', '支持的具体主张 / 原文片段'][n]}<input className={control} value={ev[key]} onChange={e => change({ evidence: card.evidence.map((x, j) => j === i ? { ...x, [key]: e.target.value } : x) })} /></label>)}<label className="block text-xs text-muted-foreground">核验状态<select className={control} value={ev.status} onChange={e => change({ evidence: card.evidence.map((x, j) => j === i ? { ...x, status: e.target.value } : x) })}>{['未核验', '已核实', '部分支持', '已否定'].map(s => <option key={s}>{s}</option>)}</select></label></div>)}</details>
      <footer className="sticky bottom-0 z-10 mt-6 space-y-3 border-t border-border bg-card py-4 shadow-[0_-6px_20px_rgba(0,0,0,0.08)]">
        {params.get('from') === 'compare' && <Link to={'/investment-workbench/compare?' + (params.get('comparison') || '')} className="inline-block text-sm text-primary underline">← 返回主题比较</Link>}
        {params.get('from') === 'tasks' && <Link to="/investment-workbench/tasks" className="inline-block text-sm text-primary underline">← 返回日常待办</Link>}
        {issues.length > 0 ? <div className="rounded-lg border border-orange-500/40 bg-orange-500/10 p-3">
          <button type="button" aria-expanded={showIssues} aria-controls="wb-missing-list" className="flex w-full items-center justify-between gap-3 text-left text-sm font-medium text-orange-500" onClick={() => setShowIssues(!showIssues)}>
            <span>还差 {issues.length} 项，补齐后即可确认</span><span className="shrink-0 underline">{showIssues ? '收起清单' : '查看未完成项'}</span>
          </button>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">{issues.map(i => i.label).join('、')}。可以先保存草稿。</p>
          {showIssues && <div id="wb-missing-list" role="alert" className="mt-3 max-h-48 space-y-2 overflow-auto">{issues.map((issue, index) => <button type="button" key={`${issue.target}-${index}`} className="flex w-full items-center justify-between gap-3 rounded border border-orange-500/20 bg-card p-2 text-left hover:border-orange-500" onClick={() => locate(issue.target)}><span><strong className="block text-xs">{issue.label}</strong><span className="text-xs text-muted-foreground">{issue.help}</span></span><span className="shrink-0 text-xs text-primary">去填写 →</span></button>)}</div>}
        </div> : <p role="status" className="text-sm text-primary">必填项已完成，可以保存并确认计划。</p>}
        {error && <p role="alert" className="rounded-lg bg-red-500/10 p-3 text-sm text-red-500">保存失败：{error}</p>}
        {!error && message && <p role="status" className="rounded-lg bg-primary/10 p-3 text-sm text-primary">{message}</p>}
        <div className="flex flex-wrap gap-2"><button className={button} onClick={() => save('草稿')}><Save size={15} />保存草稿</button><button className={button + (issues.length ? ' border-orange-500/60 bg-orange-500/10 text-orange-500' : ' bg-primary text-primary-foreground hover:bg-primary/90')} onClick={confirmPlan}><ClipboardCheck size={15} />{busy ? '正在保存…' : issues.length ? `保存并确认计划（还差 ${issues.length} 项）` : '保存并确认计划'}</button><button className={button} onClick={() => save('已撤销')}>撤销计划</button>{state.cards.some(c => c.id === card.id) && <button className={button + ' ml-auto text-red-500'} onClick={() => { if (window.confirm('删除这张卡片及其证据和计划？此操作不可撤销。')) void run(() => api('/delete/' + card.id, { revision: state.revision }), '卡片已删除', true); }}><Trash2 size={15} />删除</button>}</div>
      </footer>
      </fieldset>}
    </div>
  </div>;
}
