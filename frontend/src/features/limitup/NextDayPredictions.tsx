import { useEffect, useState } from 'react';
import { authHeaders } from '@/lib/api';

type Estimate = { value: number | number[] | null; reason: string; validated: boolean; n?: number; days?: number; baseline?: number | number[]; examples?: { date: string; code: string }[] };
type Item = { code: string; name: string; group: string; observations: string[]; risks: string[]; missing: string[]; feature_count: number; estimates?: Record<string, Estimate> };
type Report = { passed: boolean; reasons: string[]; n: number; days: number; mature_days: number; score?: number; baseline_score?: number; coverage?: number; ece?: number; window?: string[]; calibration?: { from: number; to: number; n: number; predicted: number; actual: number }[] };
type Snapshot = { id: string; version: string; generated_at: string; feature_cutoff: string; available_at: string; deadline: string; prospective: boolean; training_days: number; training_rows: number; dataset_hash: string; readiness: { excluded: Record<string, number> }; rows: Item[]; reports: Record<string, Record<string, Report>> };
type Data = { snapshot: Snapshot | null; stale: boolean; archive_count: number; job: { running: boolean; date: string; message: string }; observations: Item[]; history: { id: string }[]; actual_date?: string; actual: Record<string, { close_pct: number | null; open_pct: number | null; promoted: boolean | null; touched: boolean | null }> };
const targets = [['up', '收盘上涨'], ['touched', '触板'], ['promoted', '晋级'], ['open_pct', '开盘区间'], ['close_pct', '收盘区间']];
const control = 'rounded-lg border border-border bg-background px-3 py-2 text-xs';
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const valueText = (v: Estimate['value'] | undefined) => v === null || v === undefined ? '暂不估计' : Array.isArray(v) ? `${v[0].toFixed(2)}% ～ ${v[1].toFixed(2)}%` : pct(v);
const time = (v: string) => new Date(v).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
async function api(url: string, method = 'GET', signal?: AbortSignal) {
  const r = await fetch(url, { method, headers: authHeaders(), signal }); const body = await r.json();
  if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '研究结果读取失败');
  return body;
}
export function NextDayPredictions({ day }: { day: string }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [code, setCode] = useState('');
  const [query, setQuery] = useState('');
  const [group, setGroup] = useState('');
  const [saved, setSaved] = useState<Snapshot | null>(null);
  const [recordId, setRecordId] = useState('');
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const body = await api('/api/market/limit-up-predictions/day?' + new URLSearchParams({ date: day }), 'GET', controller.signal);
        if (controller.signal.aborted) return;
        setData(body); setError('');
        if (body.job.running) timer = setTimeout(poll, 2000);
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
    };
    void poll(); return () => { controller.abort(); clearTimeout(timer); };
  }, [day, revision]);
  useEffect(() => {
    const controller = new AbortController(); setSaved(null);
    if (recordId) api('/api/market/limit-up-predictions/record?' + new URLSearchParams({ date: day, id: recordId }), 'GET', controller.signal)
      .then(body => { if (!controller.signal.aborted) setSaved(body); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [recordId, day]);
  const generate = async () => {
    setBusy(true); setError('');
    try { await api('/api/market/limit-up-predictions/day?' + new URLSearchParams({ date: day }), 'POST'); setRecordId(''); setRevision(n => n + 1); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const snapshot = recordId ? saved : data?.snapshot;
  const rows = snapshot?.rows || data?.observations || [];
  const shown = rows.filter(r => (!group || r.group === group) && `${r.code} ${r.name}`.includes(query.trim()));
  const selected = shown.find(r => r.code === code) || shown[0];
  const running = data?.job.running && !error;
  const actual = !recordId && selected ? data?.actual[selected.code] : undefined;
  return <section className="mt-6 rounded-xl border border-primary/25 bg-primary/[0.03] p-4 sm:p-5" aria-label="次日研究预测">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="text-xs tracking-wider text-primary">第三阶段 · 历史验证</div><h4 className="mt-1 text-base font-semibold">次日研究预测</h4><p className="mt-1 text-xs text-muted-foreground">当日证据 → 时间检验 → 独立目标 → 次日对照</p></div><button className={control + ' disabled:opacity-50'} disabled={busy || !!running} onClick={generate}>{busy || running ? '正在验证…' : '验证历史并生成研究记录'}</button></div>
    <p className="my-3 text-xs leading-6 text-muted-foreground">只使用已归档数据。概率须通过历史时间检验；“上涨”“触板”“晋级”分别判断。80% 涨幅区间是经过检验的历史条件范围，不保证覆盖，也不代表可成交收益。</p>
    {error && <p role="alert" className="mb-3 rounded-lg bg-red-500/10 p-3 text-sm text-red-500">{error} <button onClick={() => setRevision(n => n + 1)} className="underline">重新读取</button></p>}
    {data?.job.date === day && data.job.message && <p role="status" className="mb-3 text-xs text-primary">{data.job.message}</p>}
    {data?.stale && <p role="alert" className="mb-3 text-xs text-orange-500">原始样本已变更，旧预测不再用于当前样本。可在留档中回看原记录，请重新验证。</p>}
    <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-3"><div className="rounded-lg border border-border bg-card p-3"><p className="text-xs text-muted-foreground">本地样本日</p><p className="mt-1 text-xl font-semibold">{data?.archive_count ?? '—'}</p></div><div className="rounded-lg border border-border bg-card p-3"><p className="text-xs text-muted-foreground">本次可用训练历史</p><p className="mt-1 text-xl font-semibold">{snapshot ? `${snapshot.training_days} 日 / ${snapshot.training_rows} 条` : '待检查'}</p></div><div className="rounded-lg border border-border bg-card p-3"><p className="text-xs text-muted-foreground">最低验证门槛 · 每市场/梯队</p><p className="mt-1 text-sm font-medium">60 个成熟日 + 20 个验证日</p><p className="mt-1 text-xs text-muted-foreground">至少 200 条验证记录，且优于基准</p></div></div>
    {!snapshot && <p className="my-3 rounded-lg bg-muted/30 p-3 text-sm">{recordId ? '正在读取历史留档…' : '尚未生成有效研究记录。点击上方按钮查看具体样本缺口；下方先列出可核对事实。'}</p>}
    {snapshot && <div className="my-3 rounded-lg bg-muted/30 p-3 text-xs leading-6"><p>{snapshot.prospective ? '在研究时窗内生成' : '历史回看 / 时窗外数据检查，不生成事前概率'} · {time(snapshot.generated_at)}</p><p>特征截止 {time(snapshot.feature_cutoff)} · 实际采集 {time(snapshot.available_at)}</p><p>研究时窗截至 {time(snapshot.deadline)}（保守采用翌日 09:15，长假不延长）</p><p>模型 {snapshot.version} · 数据指纹 {snapshot.dataset_hash.slice(0, 12)}</p>{Object.entries(snapshot.readiness.excluded).map(([k,v]) => <p key={k} className="text-orange-500">{k}：{v} 个日期</p>)}</div>}
    <div className="my-3 flex flex-wrap gap-2"><input aria-label="搜索预测标的" placeholder="名称或代码" className={control} value={query} onChange={e => setQuery(e.target.value)} /><select aria-label="预测梯队市场" className={control} value={group} onChange={e => setGroup(e.target.value)}><option value="">全部市场与梯队</option>{Array.from(new Set(rows.map(r => r.group))).map(g => <option key={g}>{g}</option>)}</select><select aria-label="预测生成留档" className={control} value={recordId} onChange={e => setRecordId(e.target.value)}><option value="">最新研究记录</option>{data?.history.map(r => <option key={r.id} value={r.id}>{r.id}</option>)}</select></div>
    <div className="max-h-80 overflow-auto rounded-lg border border-border bg-card"><table className="w-full whitespace-nowrap text-left text-xs"><thead className="sticky top-0 bg-card"><tr>{['标的 / 查看解释','市场 / 梯队',...targets.map(t => t[1])].map(h => <th className="p-3" key={h}>{h}</th>)}</tr></thead><tbody>{shown.map(r => <tr key={r.code} className={'border-t border-border/50 ' + (selected?.code === r.code ? 'bg-primary/10' : '')}><td className="p-3"><button onClick={() => setCode(r.code)} aria-label={`查看 ${r.name} 预测解释`} className="text-primary underline underline-offset-4">{r.name} {r.code}</button></td><td className="p-3">{r.group}</td>{targets.map(([t]) => <td key={t} className="p-3" title={r.estimates?.[t]?.reason}>{valueText(r.estimates?.[t]?.value)}</td>)}</tr>)}</tbody></table>{!shown.length && <p className="p-4 text-xs text-muted-foreground">没有匹配的标的。</p>}</div>
    {selected && <div className="mt-4 rounded-lg border border-border bg-card p-4"><h5 className="font-medium">{selected.name} · 依据与缺口</h5><p className="mt-1 text-xs text-muted-foreground">有效特征 {selected.feature_count}/6。以下是来源事实与风险观察，未经验证时不称为预测支持证据。</p><div className="mt-3 grid gap-4 md:grid-cols-3">{[['可核对因素', selected.observations], ['风险观察', selected.risks], ['缺失信息', selected.missing]].map(([label, list]) => <div key={label as string}><h6 className="text-xs font-semibold">{label as string}</h6><ul className="mt-2 space-y-2 text-xs leading-5 text-muted-foreground">{(list as string[]).length ? (list as string[]).map(s => <li key={s}>• {s}</li>) : <li>暂无记录，不代表没有风险。</li>}</ul></div>)}</div>
      <div className="mt-4 space-y-2 border-t border-border pt-3">{targets.map(([t, label]) => { const e = selected.estimates?.[t]; return <div key={t} className="text-xs leading-5"><strong>{label}：</strong>{e?.value != null ? `${valueText(e.value)}；相似样本 ${e.n} 条 / ${e.days} 日，同组基准 ${valueText(e.baseline)}` : e?.reason || '尚未验证，不显示估计数值'}{e?.examples && <details className="mt-1 text-muted-foreground"><summary className="cursor-pointer">相似历史记录</summary><p>{e.examples.map(x => `${x.date} ${x.code}`).join('、')}</p></details>}</div>; })}</div>
      <div className="mt-4 border-t border-border pt-3 text-xs"><strong>次日对照：</strong>{actual ? `${data?.actual_date} 收盘 ${actual.close_pct === null ? '待确认' : `${actual.close_pct.toFixed(2)}%`} · 触板 ${actual.touched === null ? '待确认' : actual.touched ? '是' : '否'} · 晋级 ${actual.promoted === null ? '待确认' : actual.promoted ? '是' : '否'}` : recordId ? '历史留档仅回看原判断；当前实际结果见上方第二阶段。' : '实际结果尚未可用，补齐后可重新读取对照。'}<button className="ml-2 text-primary underline" onClick={() => setRevision(n => n + 1)}>更新对照</button></div>
    </div>}
    {snapshot && <details className="mt-4 rounded-lg border border-border bg-card p-3"><summary className="cursor-pointer text-sm font-medium">查看各目标的历史验证报告</summary><p className="my-3 text-xs leading-5 text-muted-foreground">按日期滚动验证，训练只用当时已知的更早标签。概率看 Brier 误差和校准误差；区间看实际覆盖和区间评分。误差越低越好，不能用验证集再次挑参数。</p>{!Object.keys(snapshot.reports).length && <p className="text-xs text-orange-500">还没有可验证的市场/梯队历史数据。需要累积完整盘后样本，并完成次日结果回填。</p>}{Object.entries(snapshot.reports).map(([g, reports]) => <div key={g} className="mb-4"><h5 className="mb-2 text-sm font-medium">{g}</h5>{targets.map(([t,label]) => {const r = reports[t]; return r && <div className="border-t border-border py-2 text-xs leading-6" key={t}><strong>{label} · {r.passed ? '通过当前验证门槛' : '未通过'}</strong><p>成熟 {r.mature_days} 日 · 验证 {r.days} 日 / {r.n} 条{r.window?.length ? ` · ${r.window.join(' 至 ')}` : ''}</p>{r.score !== undefined && <p>模型误差 {r.score.toFixed(4)} / 基准 {r.baseline_score?.toFixed(4)}{r.ece !== undefined ? ` · 校准误差 ${r.ece.toFixed(4)}` : ''}{r.coverage !== undefined ? ` · 区间覆盖 ${pct(r.coverage)}` : ''}</p>}{r.reasons.map(s => <p className="text-orange-500" key={s}>{s}</p>)}{r.calibration?.map(b => <p key={b.from} className="text-muted-foreground">预测分箱 {pct(b.from)}～{pct(b.to)}：平均预测 {pct(b.predicted)} / 实际 {pct(b.actual)}（{b.n} 条）</p>)}</div>;})}</div>)}</details>}
  </section>;
}
