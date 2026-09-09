import { Copy } from 'lucide-react';

export type Choice = { id: string; label: string; strategies: string[]; kind?: string; parameter?: string; format?: string };
export type Catalog = { strategies: string[]; returns: string[]; logic: Choice[]; risks: Choice[]; entry: Choice[]; exit: Choice[] };
export type Condition = { id: string; value: string; detail: string };
export type GuidedFields = {
  strategy: string; return_type: string; return_custom: string; subject: string; basis: string;
  logic_ids: string[]; risk_ids: string[]; entry_conditions: Condition[]; exit_conditions: Condition[];
  strategy_ack: string; thesis: string; counter: string; entry: string; exit: string; review_date: string; risk_note: string;
};
export const guidedDefaults: GuidedFields = {
  strategy: '', return_type: '', return_custom: '', subject: '', basis: '', logic_ids: [], risk_ids: [],
  entry_conditions: [], exit_conditions: [], strategy_ack: '', thesis: '', counter: '', entry: '', exit: '', review_date: '', risk_note: '',
};
export const beijingDate = (offset = 0) => {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  const part = (type: string) => parts.find(p => p.type === type)!.value;
  const date = new Date(`${part('year')}-${part('month')}-${part('day')}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
};
function parameterErrors(condition: Condition, option?: Choice): string[] {
  if (!option) return ['未知条件'];
  const value = condition.value.trim();
  if (!value) return [option.parameter || option.label];
  if (option.kind === 'price' || option.kind === 'integer') {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0 || (option.kind === 'integer' && (!Number.isInteger(n) || n > 1000))) return [`${option.parameter}无效`];
  }
  if (option.kind === 'deadline') {
    const result = [];
    const d = new Date(value + 'T12:00:00Z');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(d.valueOf()) || d.toISOString().slice(0, 10) !== value) result.push('有效截止日期');
    if (!condition.detail.trim()) result.push('到期事项');
    return result;
  }
  return [];
}
export type ValidationIssue = { label: string; target: string; help: string };
export function validationIssues(c: GuidedFields, catalog: Catalog): ValidationIssue[] {
  const required = [
    ['主策略', c.strategy, 'strategy', '请选择产业趋势、事件驱动或情绪资金。'],
    ['收益来源', c.return_type, 'returns', '请选择这笔计划主要赚什么钱。'],
    ['关注业务 / 关键变量', c.subject, 'subject', '补充这只股票关注的具体业务或指标。'],
    ['一句话判断依据', c.basis, 'basis', '写明判断来自什么材料或观察，可注明待核验。'],
    ['下次复查日期', c.review_date, 'review_date', '可直接选择今天、明天或7天后。'],
  ];
  const errors: ValidationIssue[] = required.filter(([, value]) => !value.trim()).map(([label, , target, help]) => ({ label, target: `wb-${target}`, help }));
  if (c.return_type === '自定义' && !c.return_custom.trim()) errors.push({ label: '自定义收益来源', target: 'wb-return_custom', help: '填写自定义收益来源。' });
  if (!c.logic_ids.length && !c.thesis.trim()) errors.push({ label: '研究逻辑', target: 'wb-logic', help: '至少选择一个逻辑，或在下方自定义逻辑框填写。' });
  if (!c.entry_conditions.length && !c.entry.trim()) errors.push({ label: '入场条件', target: 'wb-entry', help: '至少选择一个入场条件，并填写需要的参数。' });
  if (!c.exit_conditions.length && !c.exit.trim()) errors.push({ label: '退出复查条件', target: 'wb-exit', help: '至少选择一个退出复查条件，并填写需要的参数。' });
  for (const group of ['entry', 'exit'] as const) {
    for (const item of c[`${group}_conditions`]) {
      const option = catalog[group].find(o => o.id === item.id);
      for (const label of parameterErrors(item, option)) errors.push({ label: `${group === 'entry' ? '入场' : '退出'}：${label}`, target: `wb-${group}-${item.id}`, help: `${option?.label || '条件'}：请补齐或修正参数。` });
    }
  }
  if (c.strategy_ack !== c.strategy) errors.push({ label: '策略条件重新确认', target: 'wb-strategy-ack', help: '策略切换后，请检查并确认是否沿用原条件。' });
  return errors;
}
export function formatConditions(c: GuidedFields, catalog: Catalog, group: 'entry' | 'exit'): string[] {
  return c[`${group}_conditions`].map(item => {
    const option = catalog[group].find(o => o.id === item.id);
    if (!option) return '未知条件';
    if (parameterErrors(item, option).length) return `${option.label}（待补参数）`;
    return (option.format || '{value}').replace('{value}', item.value).replace('{detail}', item.detail);
  });
}
export function planSummary(c: GuidedFields, catalog: Catalog) {
  const labels = (ids: string[], group: Choice[]) => ids.map(id => group.find(o => o.id === id)?.label || '未知选项');
  return [
    `主策略：${c.strategy || '待选择'}`,
    `主要收益来源：${(c.return_type === '自定义' ? c.return_custom : c.return_type) || '待选择'}`,
    `关注业务 / 变量：${c.subject || '待补充'}`,
    `研究假设：${[...labels(c.logic_ids, catalog.logic), c.thesis].filter(Boolean).join('；') || '待选择'}`,
    `判断依据：${c.basis || '待补充'}（核验状态以证据记录为准）`,
    `风险与反证：${[...labels(c.risk_ids, catalog.risks), c.counter].filter(Boolean).join('；') || '未补充'}`,
    `入场（全部满足后评估）：${[...formatConditions(c, catalog, 'entry'), c.entry].filter(Boolean).join('；') || '待补充'}`,
    `退出复查（任一触发）：${[...formatConditions(c, catalog, 'exit'), c.exit].filter(Boolean).join('；') || '待补充'}`,
    `下次复查：${c.review_date || '待选择'}（北京时间）`,
    ...(c.risk_note ? [`其他风险约束：${c.risk_note}`] : []),
    ...(c.strategy && c.strategy_ack !== c.strategy ? ['注意：策略已切换，原条件需要重新确认。'] : []),
    '仅记录研究假设与条件，不自动监控或执行交易。',
  ].join('\n');
}
const input = 'mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary';
const chip = 'rounded-lg border px-3 py-2 text-sm transition hover:border-primary';
const section = 'mt-6 space-y-4 border-t border-border pt-5';

export function GuidedEntry({ card: c, catalog, change, notify }: { card: GuidedFields; catalog: Catalog; change: (patch: Partial<GuidedFields>) => void; notify: (message: string) => void }) {
  const text = (key: keyof GuidedFields, label: string, placeholder = '') => <label className="block text-xs text-muted-foreground">{label}<input id={`wb-${key}`} className={input} value={String(c[key])} placeholder={placeholder} onChange={e => change({ [key]: e.target.value })} /></label>;
  const selectedStyle = (selected: boolean) => chip + (selected ? ' border-primary bg-primary/10 text-primary' : ' border-border text-muted-foreground');
  const choices = (group: 'logic' | 'risks', key: 'logic_ids' | 'risk_ids') => {
    const visible = catalog[group].filter(o => o.strategies.includes(c.strategy) || c[key].includes(o.id));
    return <div className="flex flex-wrap gap-2">{visible.map(o => <button key={o.id} type="button" aria-pressed={c[key].includes(o.id)} className={selectedStyle(c[key].includes(o.id))} onClick={() => change({ [key]: c[key].includes(o.id) ? c[key].filter(id => id !== o.id) : [...c[key], o.id] })}>{o.label}{!o.strategies.includes(c.strategy) && ' · 原策略'}</button>)}</div>;
  };
  const conditions = (group: 'entry' | 'exit') => {
    const key = `${group}_conditions` as const;
    const visible = catalog[group].filter(o => o.strategies.includes(c.strategy) || c[key].some(x => x.id === o.id));
    return <div id={`wb-${group}`} tabIndex={-1} className="space-y-3 scroll-mt-6"><div className="flex flex-wrap gap-2">{visible.map(o => {
      const chosen = c[key].some(x => x.id === o.id);
      return <button type="button" key={o.id} aria-pressed={chosen} className={selectedStyle(chosen)} onClick={() => change({ [key]: chosen ? c[key].filter(x => x.id !== o.id) : [...c[key], { id: o.id, value: '', detail: '' }] })}>{o.label}{!o.strategies.includes(c.strategy) && ' · 原策略'}</button>;
    })}</div>{c[key].map(item => {
      const o = catalog[group].find(x => x.id === item.id)!;
      const update = (patch: Partial<Condition>) => change({ [key]: c[key].map(x => x.id === item.id ? { ...x, ...patch } : x) });
      return <div id={`wb-${group}-${item.id}`} tabIndex={-1} key={item.id} className="scroll-mt-6 rounded-lg border border-border bg-background/50 p-3"><label className="block text-xs text-muted-foreground">{o.label} · {o.parameter}<input className={input} type={o.kind === 'deadline' ? 'date' : o.kind === 'price' || o.kind === 'integer' ? 'number' : 'text'} step={o.kind === 'integer' ? '1' : 'any'} value={item.value} onChange={e => update({ value: e.target.value })} /></label>{o.kind === 'deadline' && <label className="mt-3 block text-xs text-muted-foreground">到期事项<input className={input} value={item.detail} placeholder="例如：指定客户的订单正式落地" onChange={e => update({ detail: e.target.value })} /></label>}{parameterErrors(item, o).length > 0 && <p className="mt-2 text-xs text-orange-500">待补充：{parameterErrors(item, o).join('、')}</p>}</div>;
    })}</div>;
  };
  return <>
    <section className={section}>
      <h3 className="text-sm font-semibold">01 / 选择策略与研究假设</h3>
      <div id="wb-strategy" tabIndex={-1} className="flex scroll-mt-6 flex-wrap gap-2">{catalog.strategies.map(s => <button type="button" key={s} aria-pressed={c.strategy === s} className={selectedStyle(c.strategy === s)} onClick={() => {
        if (s !== c.strategy) change({ strategy: s, strategy_ack: c.strategy ? '' : s });
      }}>{s}</button>)}</div>
      {c.strategy && c.strategy_ack !== c.strategy && <div id="wb-strategy-ack" tabIndex={-1} role="status" className="rounded-lg border border-orange-500/40 bg-orange-500/5 p-3 text-sm"><p>策略已切换，已填内容全部保留。请检查带“原策略”的选项及入退场条件，再确认是否沿用。</p><button className={chip + ' mt-3 border-orange-500/50'} onClick={() => change({ strategy_ack: c.strategy })}>已检查，确认沿用当前条件</button></div>}
      <p className="text-xs text-muted-foreground">主要赚什么钱？单选；具体逻辑可多选。</p>
      <div id="wb-returns" tabIndex={-1} className="flex scroll-mt-6 flex-wrap gap-2">{catalog.returns.map(s => <button type="button" key={s} aria-pressed={c.return_type === s} className={selectedStyle(c.return_type === s)} onClick={() => change({ return_type: s })}>{s}</button>)}</div>
      {c.return_type === '自定义' && text('return_custom', '自定义收益来源')}
      <div id="wb-logic" tabIndex={-1} className="scroll-mt-6 space-y-3 rounded-lg border border-border p-4"><h4 className="text-sm font-semibold">研究逻辑（至少选一项，或填写自定义逻辑）</h4><p className="text-xs text-muted-foreground">这笔计划为什么值得研究？下方为当前策略的常见逻辑。</p>{c.strategy ? choices('logic', 'logic_ids') : <p className="text-sm text-muted-foreground">先选择主策略，显示常用逻辑与条件。</p>}<label className="block text-xs text-muted-foreground">自定义逻辑 / 补充说明（可选）<textarea aria-label="自定义逻辑" className={input} rows={2} placeholder="以上选项不适用？在这里写你的研究逻辑。" value={c.thesis} onChange={e => change({ thesis: e.target.value })} /></label>{!c.logic_ids.length && !c.thesis.trim() && <p className="text-xs text-orange-500">尚未选择或填写研究逻辑，确认计划前需要补充。</p>}</div>
      <div className="grid gap-4 sm:grid-cols-2">{text('subject', '关注业务 / 关键变量 *', '例如：液冷业务订单转收入')}{text('basis', '一句话判断依据 *', '例如：某公告进展，尚待核实收入贡献')}</div>

      <p className="text-xs text-muted-foreground">选项只是研究假设；选择后不会自动变成已核实事实。</p>
    </section>
    <section className={section}><h3 className="text-sm font-semibold">02 / 风险与计划条件</h3>{choices('risks', 'risk_ids')}
      <details className="text-sm"><summary className="cursor-pointer text-muted-foreground">自定义风险 / 反证{c.counter ? ' · 已填写' : ''}</summary><textarea aria-label="自定义风险" className={input} rows={2} value={c.counter} onChange={e => change({ counter: e.target.value })} /></details>
      <h4 className="text-sm font-medium">入场条件 · 全部满足后评估</h4>{conditions('entry')}
      {c.entry && text('entry', '补充入场条件')}
      <h4 className="text-sm font-medium">退出复查条件 · 任一触发即复查</h4>{conditions('exit')}
      {c.exit && text('exit', '补充退出条件')}
      <p className="text-xs text-muted-foreground">条件仅记录，不会自动读取行情、判断触发或执行交易。</p>
      <div className="flex flex-wrap items-end gap-3"><label className="text-xs text-muted-foreground">下次复查日期（北京时间）<input id="wb-review_date" aria-label="下次复查日期（北京时间）" type="date" className={input} value={c.review_date} onChange={e => change({ review_date: e.target.value })} /></label>{[['今天', 0], ['明天', 1], ['7天后', 7]].map(([label, offset]) => <button type="button" key={label} className={selectedStyle(c.review_date === beijingDate(Number(offset)))} onClick={() => change({ review_date: beijingDate(Number(offset)) })}>{label}</button>)}<span className="pb-2 text-xs text-muted-foreground">按自然日</span></div>
      <details className="text-sm"><summary className="cursor-pointer text-muted-foreground">其他风险约束{c.risk_note ? ' · 已填写' : ''}</summary>{text('risk_note', '风险约束备注（不计算仓位）')}</details>
    </section>
    <section className={section}><div className="flex items-center justify-between"><h3 className="text-sm font-semibold">计划摘要</h3><button type="button" className={chip + ' inline-flex items-center gap-2 border-border'} onClick={async () => { try { await navigator.clipboard.writeText(planSummary(c, catalog)); notify('摘要已复制'); } catch { notify('复制失败，可直接选择下方摘要复制'); } }}><Copy size={14} />复制摘要</button></div><pre className="whitespace-pre-wrap rounded-lg bg-muted/30 p-4 font-sans text-sm leading-7">{planSummary(c, catalog)}</pre></section>
  </>;
}
