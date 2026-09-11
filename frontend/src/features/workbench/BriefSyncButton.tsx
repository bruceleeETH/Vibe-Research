import { useCallback, useEffect, useRef, useState } from 'react';
import { CloudDownload } from 'lucide-react';
import { authHeaders } from '@/lib/api';

type Job = { id: string; status: string; message: string; results?: { slot: string; error: string | null; today_archived: boolean; latest_date: string | null }[] };
type SyncState = { available: boolean; unavailable_reason?: string; job: Job | null };
const pending = new Set(['dispatching', 'queued', 'running', 'delivery_unknown']);
const labels: Record<string, string> = { dispatching: '正在提交', queued: '等待执行', running: '同步中', completed: '已完成', failed: '失败', timed_out: '等待超时', delivery_unknown: '投递待确认' };

export function BriefSyncButton({ onComplete }: { onComplete?: () => void }) {
  const [state, setState] = useState<SyncState | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const callback = useRef(onComplete); callback.current = onComplete;
  const observed = useRef('');
  const alive = useRef(true);
  const requestVersion = useRef(0);
  const apply = useCallback((next: SyncState) => {
    setState(next);
    const key = next.job ? next.job.id + '/' + next.job.status : '';
    if (key !== observed.current && next.job && ['completed', 'failed'].includes(next.job.status)) callback.current?.();
    observed.current = key;
  }, []);
  const load = useCallback(async () => {
    const version = ++requestVersion.current;
    try {
      const response = await fetch('/api/workbench/briefs/sync', { headers: authHeaders() });
      const next = await response.json();
      if (!response.ok) throw new Error(next.detail || '无法读取同步状态');
      if (alive.current && version === requestVersion.current) { apply(next); setError(''); }
    } catch (e) { if (alive.current && version === requestVersion.current) setError(e instanceof Error ? e.message : '无法读取同步状态'); }
  }, [apply]);
  useEffect(() => {
    alive.current = true; void load();
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load(); }, 3000);
    return () => { alive.current = false; ++requestVersion.current; window.clearInterval(timer); };
  }, [load]);
  const sync = async () => {
    if (sending || (state?.job && pending.has(state.job.status))) return;
    setSending(true); setError(''); ++requestVersion.current;
    try {
      const response = await fetch('/api/workbench/briefs/sync', { method: 'POST', headers: { ...authHeaders(), 'X-Brief-Sync': 'manual' } });
      const next = await response.json();
      if (!response.ok) throw new Error(next.detail || '提交同步失败');
      if (alive.current) apply(next);
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : '提交同步失败'); }
    finally { if (alive.current) { setSending(false); void load(); } }
  };
  const busy = sending || !!(state?.job && pending.has(state.job.status));
  return <section aria-label="手动同步简报" className="rounded-xl border border-border bg-card p-4">
    <div className="flex flex-wrap items-center gap-3">
      <button onClick={() => void sync()} disabled={!state?.available || busy} className="inline-flex min-w-36 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"><CloudDownload size={16} className={busy ? 'animate-pulse' : ''} />{busy ? (sending ? '正在提交…' : labels[state!.job!.status] + '…') : '同步早晚简报'}</button>
      <p className="text-xs text-muted-foreground">立即检查两档来源的新内容。需本机 Codex 可运行，定时同步照常。</p>
    </div>
    {!state?.available && state?.unavailable_reason && <p className="mt-3 text-sm text-amber-600">{state.unavailable_reason}</p>}
    {error && <p role="alert" className="mt-3 text-sm text-red-500">{error}<button onClick={() => void load()} className="ml-3 underline">重查状态</button></p>}
    {state?.job && <div role="status" aria-live="polite" className="mt-3 space-y-1 text-sm"><p className={['failed', 'timed_out'].includes(state.job.status) ? 'text-amber-600' : 'text-muted-foreground'}>{labels[state.job.status]}：{state.job.message}</p>{state.job.results?.map(result => <p key={result.slot} className="text-xs text-muted-foreground">{result.slot === 'morning' ? '早报' : '晚报'}：{result.error ? '读取失败：' + result.error : result.today_archived ? '今日已归档' : '尚未取得今日内容'}{result.latest_date && ` · 最近归档 ${result.latest_date}`}</p>)}</div>}
  </section>;
}
