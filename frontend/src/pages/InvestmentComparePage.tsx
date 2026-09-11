import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Columns3, Copy, RefreshCw, X } from 'lucide-react';
import { authHeaders } from '@/lib/api';
import { beijingDate, formatConditions, type Catalog, type Choice } from '@/features/workbench/GuidedEntry';
import type { Card, Snapshot } from '@/features/workbench/types';
import { WorkbenchNav } from '@/features/workbench/WorkbenchNav';

const button = 'inline-flex items-center justify-center gap-2 rounded-lg border border-border px-3 py-2 text-sm hover:border-primary disabled:opacity-40';
const input = 'rounded-lg border border-border bg-background px-3 py-2 text-sm';
const missing = '未填写';
const text = (value: string) => value.trim() || missing;
const themeKey = (card: Card) => card.theme.trim() ? 'theme:' + card.theme.trim() : 'unthemed';
const joined = (items: string[]) => items.filter(x => x.trim()).join('\n') || missing;
const choiceLabels = (ids: string[], options: Choice[], strategy: string) => ids.map(id => {
  const option = options.find(o => o.id === id);
  return option ? option.label + (option.strategies.includes(strategy) ? '' : '（原策略选项）') : '未知选项，需检查原卡';
});
function rowsFor(card: Card, catalog: Catalog, today: string) {
  const conditions = (group: 'entry' | 'exit') => formatConditions(card, catalog, group).map((line, i) => {
    const option = catalog[group].find(o => o.id === card[`${group}_conditions`][i].id);
    return line + (option && !option.strategies.includes(card.strategy) ? '（原策略条件）' : '');
  });
  return [
    ['研究主题', text(card.theme)],
    ['主策略', text(card.strategy)],
    ['主要收益来源', text(card.return_type === '自定义' ? card.return_custom : card.return_type)],
    ['关注业务 / 关键变量', text(card.subject)],
    ['研究逻辑 / 假设', joined([...choiceLabels(card.logic_ids, catalog.logic, card.strategy), card.thesis])],
    ['判断依据', text(card.basis)],
    ['风险与反证', joined([...choiceLabels(card.risk_ids, catalog.risks, card.strategy), card.counter])],
    ['入场条件（全部满足）', joined([...conditions('entry'), card.entry])],
    ['退出复查条件（任一触发）', joined([...conditions('exit'), card.exit])],
    ['其他风险约束', text(card.risk_note)],
    ['下次复查（北京时间）', card.review_date ? card.review_date + (card.status !== '已撤销' && card.review_date <= today ? card.review_date < today ? ' · 已逾期' : ' · 今天到期' : '') : missing],
    ['计划状态', card.status + (card.strategy && card.strategy_ack !== card.strategy ? ' · 策略条件需重新确认' : '')],
    ['证据核验概况', card.evidence.length ? ['已核实', '部分支持', '未核验', '已否定'].map(status => `${status} ${card.evidence.filter(e => e.status === status).length} 条`).join(' / ') : '尚无证据'],
    ['最近保存', card.updated_at ? new Date(card.updated_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '尚未保存'],
  ];
}
export function InvestmentComparePage() {
  const [params, setParams] = useSearchParams();
  const ids = [...new Set((params.get('cards') || '').split(',').filter(Boolean))].slice(0, 4);
  const theme = params.get('theme') || 'all';
  const query = params.get('q') || '';
  const includeRevoked = params.get('revoked') === '1';
  const [data, setData] = useState<{ snapshot: Snapshot; catalog: Catalog } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [today, setToday] = useState(beijingDate);
  const controller = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    controller.current?.abort();
    const current = new AbortController(); controller.current = current;
    setLoading(true); setError('');
    try {
      const read = async (path: string) => {
        const result = await fetch('/api/workbench' + path, { headers: authHeaders(), signal: current.signal });
        const value = await result.json();
        if (!result.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '比较数据读取失败');
        return value;
      };
      const [snapshot, catalog] = await Promise.all([read(''), read('/catalog')]);
      if (!current.signal.aborted) { setData({ snapshot, catalog }); setToday(beijingDate()); }
    } catch (e) { if (!current.signal.aborted) setError(e instanceof Error ? e.message : '读取失败'); }
    finally { if (!current.signal.aborted) setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); return () => controller.current?.abort(); }, [refresh]);
  const update = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    setParams(next, { replace: true }); setNotice('');
  };
  const cards = data?.snapshot.cards || [];
  const selected = ids.flatMap(id => { const card = cards.find(c => c.id === id); return card ? [card] : []; });
  const missingIds = ids.filter(id => !cards.some(c => c.id === id));
  const candidates = cards.filter(c => includeRevoked || c.status !== '已撤销');
  const groups = new Map<string, { label: string; count: number }>();
  candidates.forEach(c => { const key = themeKey(c); const current = groups.get(key); groups.set(key, { label: c.theme.trim() || '未填写主题', count: (current?.count || 0) + 1 }); });
  const visible = candidates.filter(c => (theme === 'all' || themeKey(c) === theme) && `${c.name} ${c.code} ${c.theme} ${c.subject}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const hiddenCount = selected.filter(c => !visible.some(v => v.id === c.id)).length;
  const toggle = (id: string) => {
    if (ids.includes(id)) update({ cards: ids.filter(x => x !== id).join(',') });
    else if (ids.length >= 4) setNotice('最多比较 4 张投资卡，请先移除一张，再添加。');
    else update({ cards: [...ids, id].join(',') });
  };
  const rows = selected.map(card => rowsFor(card, data!.catalog, today));
  const cardLink = (card: Card) => '/investment-workbench?' + new URLSearchParams({ card: card.id, from: 'compare', comparison: params.toString() });
  async function copyComparison() {
    const value = [`主题与标的比较 · 北京时间 ${today}`, '当前已保存研究记录；证据状态由本人维护，不代表收益预测。', ...selected.map((card, i) => [
      `\n${card.name}（${card.code}）`, ...rows[i].map(([label, content]) => `${label}：${content}`),
      ...card.evidence.map((e, j) => `证据 ${j + 1} [${e.status}] ${e.title || '未填写标题'}\n公开时间：${e.published_at || '未知'}\n来源：${e.url || '未填写'}\n主张：${e.claim || '未填写'}`),
    ].join('\n'))].join('\n');
    try { await navigator.clipboard.writeText(value); setNotice('已复制当前所选卡片的比较摘要。'); }
    catch { setNotice('复制失败，请检查浏览器剪贴板权限，或直接选中表格内容复制。'); }
  }
  return <div className="mx-auto max-w-[1600px] space-y-5 p-5 lg:p-8">
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-5"><div><p className="text-xs tracking-[.2em] text-primary">BRUCE / RESEARCH COMPARISON</p><h1 className="mt-2 text-2xl font-semibold">主题与标的比较</h1><p className="mt-2 text-sm text-muted-foreground">把逻辑、证据和风险放在一起，找出需要继续研究的差异。</p></div><button className={button} disabled={loading} onClick={() => void refresh()}><RefreshCw size={15} />{loading ? '正在读取…' : '刷新已保存记录'}</button></header>
    <WorkbenchNav />
    <p className="text-xs leading-6 text-muted-foreground">按投资卡的“研究主题”分组，可跨主题比较，最多 4 张。仅展示已保存内容；草稿不等于已确认计划，核验状态由本人维护。证据数量不代表质量，未填写内容不代表不存在风险。</p>
    {error && <p role="alert" className="rounded-lg bg-red-500/10 p-3 text-sm text-red-500">{error}。{data ? '下方是上次读取的记录，可能已过期。' : '请点击刷新重试。'}</p>}
    <section className="rounded-xl border border-border bg-card p-5"><div className="flex flex-wrap items-end gap-4"><label className="text-xs">研究主题<select aria-label="筛选研究主题" className={input + ' ml-2 max-w-64'} value={theme} onChange={e => update({ theme: e.target.value })}><option value="all">全部主题（{candidates.length} 张）</option>{[...groups].sort((a, b) => a[1].label.localeCompare(b[1].label, 'zh-CN')).map(([key, group]) => <option key={key} value={key}>{group.label}（{group.count} 张）</option>)}{theme !== 'all' && !groups.has(theme) && <option value={theme}>当前主题暂无卡片</option>}</select></label><input aria-label="搜索比较候选" className={input + ' min-w-0 flex-1'} placeholder="搜索名称、代码、主题或关键变量" value={query} onChange={e => update({ q: e.target.value })} /><label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={includeRevoked} onChange={e => update({ revoked: e.target.checked ? '1' : '' })} />显示已撤销</label></div>
      <div className="mt-4 max-h-64 space-y-2 overflow-y-auto" aria-label="比较候选卡片">{visible.map(card => <div key={card.id} className={'flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 ' + (ids.includes(card.id) ? 'border-primary bg-primary/5' : 'border-border')}><div className="min-w-0 flex-1"><strong className="text-sm">{card.name} <span className="font-normal text-muted-foreground">{card.code}</span></strong><p className="mt-1 break-words text-xs text-muted-foreground">{card.theme.trim() || '未填写主题'} · {card.strategy || '未选策略'} · {card.status}</p></div><button aria-label={`${ids.includes(card.id) ? '移出' : '加入'}比较：${card.name} ${card.code} ${card.theme || '未填写主题'}`} aria-pressed={ids.includes(card.id)} className={button} onClick={() => toggle(card.id)}>{ids.includes(card.id) ? '已选 · 移除' : '加入比较'}</button></div>)}{!visible.length && <p className="py-6 text-center text-sm text-muted-foreground">{loading && !data ? '正在读取投资卡…' : error && !data ? '尚未取得投资卡数据' : candidates.length ? '没有匹配的卡片，试试其他主题或搜索词。' : '暂无可选卡片，可先新建投资卡或显示已撤销卡片。'}</p>}</div>
      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-4"><span className="text-sm">已选 {ids.length} / 4</span>{selected.map(card => <button key={card.id} className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1.5 text-xs text-primary" aria-label={`移除所选：${card.name} ${card.code}`} onClick={() => toggle(card.id)}>{card.name} {card.code}<X size={12} /></button>)}{ids.length > 0 && <button className="text-xs text-muted-foreground underline" onClick={() => update({ cards: '' })}>清空选择</button>}<Link to="/investment-workbench" className="ml-auto text-xs text-primary underline">管理投资卡与主题</Link></div>
      {hiddenCount > 0 && <p className="mt-3 text-xs text-muted-foreground">有 {hiddenCount} 张已选卡片不在当前筛选范围，仍保留在下方比较。</p>}
      {data && missingIds.length > 0 && <p role="alert" className="mt-3 text-sm text-orange-500">{missingIds.length} 张所选卡片已不存在，未展示其内容。<button className="ml-2 underline" onClick={() => update({ cards: selected.map(c => c.id).join(',') })}>移除失效选择</button></p>}
    </section>
    <div role="status" className="min-h-5 text-sm text-primary">{notice || (ids.length === 4 ? '已达 4 张上限；如需加入其他卡片，请先移除一张。' : '')}</div>
    {selected.length < 2 ? <section className="rounded-xl border border-dashed border-border p-10 text-center"><Columns3 size={30} className="mx-auto mb-4 text-primary" /><h2 className="font-semibold">{selected.length ? '再选一张，开始并排比较' : '选择 2–4 张投资卡开始比较'}</h2><p className="mt-2 text-sm text-muted-foreground">主题为空的卡片在“未填写主题”分组中，也可以打开原卡补充。</p></section> : <section className="space-y-3"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">并排比较 <span className="text-xs font-normal text-muted-foreground">{selected.length} 张卡 · 北京时间 {today}</span></h2><button className={button} disabled={loading || !!error} onClick={() => void copyComparison()}><Copy size={15} />复制比较摘要</button></div><p className="text-xs text-muted-foreground">表格可横向滚动；选择会保留在本页地址中。打开原卡修改并保存后，点击“返回主题比较”读取最新内容。</p>
      <div className="max-h-[75vh] overflow-auto rounded-xl border border-border bg-card" tabIndex={0} aria-label="投资卡并排比较表格"><table className="w-full table-fixed border-collapse text-left text-sm" style={{ minWidth: 160 + selected.length * 290 }}><caption className="sr-only">投资卡研究逻辑、风险、条件和证据对照</caption><colgroup><col style={{ width: 160 }} />{selected.map(c => <col key={c.id} />)}</colgroup><thead className="sticky top-0 z-20 bg-card"><tr><th scope="col" className="sticky left-0 z-30 border-b border-r border-border bg-card p-4">比较维度</th>{selected.map(card => <th scope="col" key={card.id} className="border-b border-r border-border p-4 align-top"><strong className="block break-words">{card.name} <span className="text-xs font-normal text-muted-foreground">{card.code}</span></strong><p className="mt-2 text-xs font-normal text-muted-foreground">{card.status} · {card.theme.trim() || '未填写主题'}</p><Link to={cardLink(card)} className="mt-3 inline-block text-xs font-normal text-primary underline" aria-label={`打开原卡：${card.name} ${card.code}`}>打开原卡 →</Link></th>)}</tr></thead><tbody>{rows[0].map(([label], i) => <tr key={label}><th scope="row" className="sticky left-0 z-10 border-b border-r border-border bg-card p-4 align-top text-xs font-medium text-muted-foreground">{label}</th>{selected.map((card, j) => <td key={card.id} className={'whitespace-pre-wrap break-words border-b border-r border-border p-4 align-top leading-6 ' + (rows[j][i][1] === missing || rows[j][i][1] === '尚无证据' ? 'text-orange-500' : '')}>{rows[j][i][1]}</td>)}</tr>)}<tr><th scope="row" className="sticky left-0 z-10 border-r border-border bg-card p-4 align-top text-xs font-medium text-muted-foreground">证据与来源</th>{selected.map(card => <td key={card.id} className="border-r border-border p-4 align-top">{card.evidence.length ? <details><summary className="cursor-pointer text-primary">展开 {card.evidence.length} 条证据</summary><div className="mt-3 space-y-3">{card.evidence.map((e, i) => <article key={i} className="rounded-lg border border-border p-3"><p className="text-xs text-primary">{e.status}</p><p className="mt-1 whitespace-pre-wrap break-words font-medium">{e.title || '未填写标题'}</p><p className="mt-2 whitespace-pre-wrap break-words text-xs leading-6">{e.claim || '未填写具体主张'}</p><p className="mt-2 break-words text-xs text-muted-foreground">公开时间：{e.published_at || '未知'}</p><p className="mt-1 break-all text-xs text-muted-foreground">来源：{e.url || '未填写'}</p></article>)}</div></details> : <span className="text-orange-500">尚无证据</span>}</td>)}</tr></tbody></table></div>
    </section>}
  </div>;
}
