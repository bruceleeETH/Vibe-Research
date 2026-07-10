import { useEffect, useMemo, useState } from "react";
import { Plus, RefreshCw, X, ClipboardList, ScanSearch, Tag } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { api, type ScanResult, type PoolData, type ScanCandidate, type PoolEntry } from "@/lib/api";
import { cn } from "@/lib/utils";

// A 股红涨绿跌（全站一致）
const color = (v: number | null | undefined) =>
  v == null ? "text-muted-foreground" : v > 0 ? "text-danger" : v < 0 ? "text-success" : "text-muted-foreground";
const pct = (v: number | null | undefined) => (v == null ? "待" : `${v > 0 ? "+" : ""}${v}%`);
const yi = (v: number | null | undefined) => (v == null ? "—" : `${(v / 1e8).toFixed(v >= 1e9 ? 0 : 1)}亿`);

const STRATEGY_NAME: Record<string, string> = {
  volume_surge: "放量上涨",
  high_turnover: "高换手",
  value_breakout: "估值突破",
};

const TAG_STYLE: Record<string, string> = {
  重点关注: "bg-primary/15 text-primary",
  观察: "bg-sky-500/15 text-sky-500",
  备选: "bg-violet-500/15 text-violet-400",
  谨慎: "bg-amber-500/15 text-amber-500",
};

export function ReviewPool() {
  const [tab, setTab] = useState<"scan" | "pool">("scan");
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [pool, setPool] = useState<PoolData | null>(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [poolLoading, setPoolLoading] = useState(false);
  const [strategy, setStrategy] = useState<string>("all"); // all | 策略 key
  const [hideFlagged, setHideFlagged] = useState(true);
  const [minAmount3, setMinAmount3] = useState(false);
  const [manualInput, setManualInput] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const loadScan = (refresh = false) => {
    setScanLoading(true);
    setErr(null);
    api.reviewScan(refresh)
      .then(setScan)
      .catch((e) => setErr(e.message))
      .finally(() => setScanLoading(false));
  };
  const loadPool = (refresh = false) => {
    setPoolLoading(true);
    api.reviewPool(refresh)
      .then(setPool)
      .catch((e) => setErr(e.message))
      .finally(() => setPoolLoading(false));
  };
  useEffect(() => {
    loadScan();
    loadPool();
  }, []);

  const poolCodesToday = useMemo(() => {
    const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
    return new Set((pool?.entries || []).filter((e) => e.entry_date === today).map((e) => e.code));
  }, [pool]);

  const candidates = useMemo(() => {
    let rows = scan?.candidates || [];
    if (strategy !== "all") rows = rows.filter((c) => c.strategies.includes(strategy));
    if (hideFlagged) rows = rows.filter((c) => c.flags.length === 0);
    if (minAmount3) rows = rows.filter((c) => (c.amount ?? 0) >= 3e8);
    return rows;
  }, [scan, strategy, hideFlagged, minAmount3]);

  const addToPool = async (c: ScanCandidate) => {
    try {
      const r = await api.reviewPoolAdd([{ code: c.code, strategies: c.strategies }]);
      toast[r.added ? "success" : "info"](r.added ? `${c.name} 已入复盘池` : `${c.name} 今日已在池中`);
      if (r.added) loadPool();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const addManual = async () => {
    const codes = [...new Set(manualInput.match(/\b\d{6}\b/g) || [])];
    if (!codes.length) {
      toast.info("没识别到 6 位代码");
      return;
    }
    try {
      const r = await api.reviewPoolAdd(codes.map((code) => ({ code })));
      toast.success(`已入池 ${r.added} 只（重复入池自动跳过）`);
      setManualInput("");
      loadPool();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const setTag = async (e: PoolEntry, tag: string) => {
    try {
      await api.reviewPoolTag(e.id, tag === e.tag ? "" : tag, e.note);
      loadPool();
    } catch (er) {
      toast.error((er as Error).message);
    }
  };

  const removeEntry = async (e: PoolEntry) => {
    try {
      await api.reviewPoolRemove(e.id);
      loadPool();
    } catch (er) {
      toast.error((er as Error).message);
    }
  };

  // 喂给用户 AI 的上下文（客观数据 + 手动标签，分析由用户模型给出）
  const scanContext = useMemo(() => {
    if (!candidates.length) return "今日候选扫描暂无结果。";
    return (
      `候选扫描（客观阈值硬筛，${scan?.generated_at}，扫描 ${scan?.scanned} 只，当前视图 ${candidates.length} 只）：\n` +
      candidates.slice(0, 40).map((c) =>
        `${c.name}(${c.code}) ${c.industry} 涨${pct(c.pct)} 成交${yi(c.amount)} 换手${c.turnover ?? "—"}% 量比${c.vol_ratio ?? "—"} PE(TTM)${c.pe_ttm ?? "—"} 命中[${c.strategies.map((s) => STRATEGY_NAME[s]).join("/")}]${c.flags.length ? " 提示[" + c.flags.join("/") + "]" : ""}`,
      ).join("\n")
    );
  }, [candidates, scan]);

  const poolContext = useMemo(() => {
    const es = pool?.entries || [];
    if (!es.length) return "复盘池为空。";
    return (
      `我的复盘池（入池后真实收盘的客观回看，${pool?.updated}）：\n` +
      es.map((e) =>
        `${e.name}(${e.code}) 入池${e.entry_date}@${e.entry_price} 现价${e.price ?? "—"} 1D:${pct(e.perf.d1)} 3D:${pct(e.perf.d3)} 5D:${pct(e.perf.d5)} 10D:${pct(e.perf.d10)} ${e.status}${e.tag ? " 标签:" + e.tag : ""}${e.note ? " 备注:" + e.note : ""}`,
      ).join("\n")
    );
  }, [pool]);

  return (
    <div>
      <PageHeader
        title="复盘工作台"
        subtitle="客观阈值硬筛候选 → 入池记录 → 1D/3D/5D/10D 真实表现回看。不评分、不推荐，标签手动标注，数据只存本地。"
        actions={
          tab === "scan" ? (
            <AskAiButton
              context={scanContext}
              label="让 AI 读候选"
              suggestions={["按行业帮我分组梳理", "这批票里哪些量价结构值得细看", "各自的主要风险是什么"]}
            />
          ) : (
            <AskAiButton
              context={poolContext}
              label="让 AI 复盘"
              suggestions={["帮我复盘这批票的整体表现", "哪类策略命中的票走得更好", "成熟样本里有什么共性"]}
            />
          )
        }
      />

      {/* Tab 切换 + 状态条 */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-1.5">
          {([["scan", "候选扫描", ScanSearch], ["pool", "复盘池", ClipboardList]] as const).map(([k, label, Icon]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-sm transition-colors",
                tab === k ? "bg-primary/15 font-medium text-primary shadow-glow" : "text-muted-foreground hover:bg-muted/50",
              )}
            >
              <Icon className="h-4 w-4" /> {label}
              {k === "pool" && pool ? <span className="text-xs opacity-70">（{pool.total}）</span> : null}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {scan && <span>扫描 {scan.generated_at} · 全市场 {scan.scanned} 只</span>}
          {pool && <span>复盘样本 {pool.total} 条 · 成熟 {pool.mature_count}</span>}
        </div>
      </div>

      {err && (
        <GlassCard className="mb-4">
          <p className="text-sm text-destructive">{err}</p>
        </GlassCard>
      )}

      {tab === "scan" ? (
        <GlassCard glow>
          {/* 策略 chips + 过滤 */}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button
              onClick={() => setStrategy("all")}
              className={cn(
                "rounded-full px-3 py-1 text-xs transition-colors",
                strategy === "all" ? "bg-primary/15 font-medium text-primary" : "bg-muted/40 text-muted-foreground hover:text-foreground",
              )}
            >
              全部候选{scan ? `（${scan.candidates.length}）` : ""}
            </button>
            {(scan?.strategies || []).map((s) => (
              <button
                key={s.key}
                onClick={() => setStrategy(s.key)}
                title={s.desc}
                className={cn(
                  "rounded-full px-3 py-1 text-xs transition-colors",
                  strategy === s.key ? "bg-primary/15 font-medium text-primary" : "bg-muted/40 text-muted-foreground hover:text-foreground",
                )}
              >
                {s.name}（{s.count}）
              </button>
            ))}
            <span className="mx-1 h-4 w-px bg-border/60" />
            <label className="flex cursor-pointer items-center gap-1 text-xs text-muted-foreground">
              <input type="checkbox" checked={hideFlagged} onChange={(e) => setHideFlagged(e.target.checked)} />
              隐藏有提示项（涨停附近/换手过热/成交不足）
            </label>
            <label className="flex cursor-pointer items-center gap-1 text-xs text-muted-foreground">
              <input type="checkbox" checked={minAmount3} onChange={(e) => setMinAmount3(e.target.checked)} />
              成交额＞3亿
            </label>
            <button
              onClick={() => loadScan(true)}
              disabled={scanLoading}
              className="ml-auto text-muted-foreground hover:text-primary"
              title="重新扫描"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", scanLoading && "animate-spin")} />
            </button>
          </div>

          {/* 当前策略的规则说明（透明可核） */}
          <p className="mb-2 text-[11px] text-muted-foreground/70">
            {strategy === "all"
              ? (scan?.strategies || []).map((s) => `${s.name}：${s.desc}`).join("　·　")
              : scan?.strategies.find((s) => s.key === strategy)?.desc}
            　·　命中即列出（成交额降序的客观排序），无评分无推荐
          </p>

          {scanLoading && !scan ? (
            <p className="py-10 text-center text-sm text-muted-foreground/60">扫描中…</p>
          ) : candidates.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground/60">
              当前条件下没有候选（非交易时段量比/换手可能失真，可切换过滤条件或稍后重扫）。
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    {["名称", "行业", "命中策略", "涨跌%", "成交额", "换手%", "量比", "PE(TTM)", "提示", ""].map((h) => (
                      <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {candidates.slice(0, 100).map((c) => (
                    <tr key={c.code} className="border-b border-border/30">
                      <td className="px-2 py-2.5">
                        <span className="font-medium">{c.name}</span>
                        <span className="ml-1.5 font-mono text-xs text-muted-foreground">{c.code}</span>
                      </td>
                      <td className="max-w-32 truncate px-2 py-2.5 text-xs text-muted-foreground">{c.industry || "—"}</td>
                      <td className="px-2 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {c.strategies.map((s) => (
                            <span key={s} className="rounded bg-muted/50 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                              {STRATEGY_NAME[s] || s}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className={cn("px-2 py-2.5 font-mono", color(c.pct))}>{pct(c.pct)}</td>
                      <td className="px-2 py-2.5 font-mono text-muted-foreground">{yi(c.amount)}</td>
                      <td className="px-2 py-2.5 font-mono text-muted-foreground">{c.turnover ?? "—"}</td>
                      <td className="px-2 py-2.5 font-mono text-muted-foreground">{c.vol_ratio ?? "—"}</td>
                      <td className="px-2 py-2.5 font-mono text-muted-foreground">{c.pe_ttm ?? "—"}</td>
                      <td className="px-2 py-2.5">
                        {c.flags.map((f) => (
                          <span key={f} className="mr-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] text-amber-500">{f}</span>
                        ))}
                      </td>
                      <td className="px-2 py-2.5">
                        {poolCodesToday.has(c.code) ? (
                          <span className="text-[11px] text-muted-foreground/60">已入池</span>
                        ) : (
                          <button
                            onClick={() => addToPool(c)}
                            className="inline-flex items-center gap-1 rounded-lg bg-primary/10 px-2 py-1 text-xs text-primary hover:bg-primary/20"
                            title="加入复盘池（记录当前价为入池价）"
                          >
                            <Plus className="h-3 w-3" /> 入池
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {candidates.length > 100 && (
                <p className="mt-2 text-center text-xs text-muted-foreground/60">只显示前 100 条（成交额降序），可用过滤条件收窄。</p>
              )}
            </div>
          )}
        </GlassCard>
      ) : (
        <>
          {/* 手动入池 */}
          <GlassCard className="mb-4">
            <label className="mb-1.5 block text-xs text-muted-foreground">
              手动入池 —— 粘贴一串 6 位代码（逗号 / 空格 / 换行都行），以当前价记为入池价
            </label>
            <div className="flex gap-2">
              <input
                value={manualInput}
                onChange={(e) => setManualInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addManual()}
                placeholder="如：600519 000858, 300750"
                className="flex-1 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
              />
              <button
                onClick={addManual}
                className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-primary/15 px-4 text-sm font-medium text-primary shadow-glow hover:bg-primary/25"
              >
                <Plus className="h-4 w-4" /> 入池
              </button>
            </div>
          </GlassCard>

          <GlassCard glow>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="flex items-center gap-1.5 font-semibold">
                <ClipboardList className="h-4 w-4 text-primary" /> 复盘池
                <span className="text-xs font-normal text-muted-foreground">
                  （{pool?.total ?? 0} 条 · 成熟 {pool?.mature_count ?? 0} · 满 10 个交易日为成熟）
                </span>
              </h3>
              <button
                onClick={() => loadPool(true)}
                disabled={poolLoading}
                className="text-muted-foreground hover:text-primary"
                title="刷新表现"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", poolLoading && "animate-spin")} />
              </button>
            </div>
            {!pool || pool.entries.length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground/60">
                复盘池还是空的——去「候选扫描」一键入池，或用上面的框手动添加。
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      {["名称", "入池日", "策略", "入池价", "现价", "1D", "3D", "5D", "10D", "状态", "标签", ""].map((h) => (
                        <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {pool.entries.map((e) => (
                      <tr key={e.id} className="border-b border-border/30">
                        <td className="px-2 py-2.5">
                          <span className="font-medium">{e.name}</span>
                          <span className="ml-1.5 font-mono text-xs text-muted-foreground">{e.code}</span>
                        </td>
                        <td className="px-2 py-2.5 font-mono text-xs text-muted-foreground">{e.entry_date}</td>
                        <td className="px-2 py-2.5">
                          {e.strategies.map((s) => (
                            <span key={s} className="mr-1 rounded bg-muted/50 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                              {STRATEGY_NAME[s] || s}
                            </span>
                          ))}
                        </td>
                        <td className="px-2 py-2.5 font-mono text-muted-foreground">{e.entry_price || "—"}</td>
                        <td className={cn("px-2 py-2.5 font-mono", color(e.change_pct))}>{e.price ?? "—"}</td>
                        {([e.perf.d1, e.perf.d3, e.perf.d5, e.perf.d10] as const).map((v, i) => (
                          <td key={i} className={cn("px-2 py-2.5 font-mono", color(v))}>{pct(v)}</td>
                        ))}
                        <td className="px-2 py-2.5">
                          <span className={cn(
                            "rounded px-1.5 py-0.5 text-[11px]",
                            e.mature ? "bg-success/15 text-success" : "bg-muted/50 text-muted-foreground",
                          )}>
                            {e.status}
                          </span>
                        </td>
                        <td className="px-2 py-2.5">
                          <div className="flex flex-wrap gap-1">
                            {(pool.tags || []).map((t) => (
                              <button
                                key={t}
                                onClick={() => setTag(e, t)}
                                className={cn(
                                  "rounded px-1.5 py-0.5 text-[11px] transition-colors",
                                  e.tag === t ? TAG_STYLE[t] : "bg-muted/30 text-muted-foreground/50 hover:text-muted-foreground",
                                )}
                                title={e.tag === t ? "点击取消标签" : `标为「${t}」`}
                              >
                                {e.tag === t && <Tag className="mr-0.5 inline h-2.5 w-2.5" />}
                                {t}
                              </button>
                            ))}
                          </div>
                        </td>
                        <td className="px-2 py-2.5">
                          <button
                            onClick={() => removeEntry(e)}
                            className="text-muted-foreground/50 hover:text-destructive"
                            title="移出复盘池"
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassCard>
        </>
      )}

      <Disclaimer />
    </div>
  );
}
