// 复盘池视图：手动入池 / 收益跟踪表 / 标签 / 导出 CSV。拆分自 pages/ReviewPool.tsx。
import { useState } from "react";
import { Plus, RefreshCw, X, ClipboardList, Tag } from "lucide-react";
import { toast } from "sonner";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, type PoolData, type PoolEntry } from "@/lib/api";
import { cn } from "@/lib/utils";
import { color, pct, rowCls, STRATEGY_NAME, TAG_STYLE } from "./shared";

interface Props {
  pool: PoolData | null;
  loading: boolean;
  onReload: (refresh?: boolean) => void;
  onDetail: (e: PoolEntry) => void;
}

export function PoolView({ pool, loading, onReload, onDetail }: Props) {
  const [manualInput, setManualInput] = useState("");

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
      onReload();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const setTagFor = async (e: PoolEntry, tag: string) => {
    try {
      await api.reviewPoolTag(e.id, tag === e.tag ? "" : tag, e.note);
      onReload();
    } catch (er) {
      toast.error((er as Error).message);
    }
  };

  const removeEntry = async (e: PoolEntry) => {
    try {
      await api.reviewPoolRemove(e.id);
      onReload();
    } catch (er) {
      toast.error((er as Error).message);
    }
  };

  const exportCsv = () => {
    if (!pool) return;
    const head = "代码,名称,市场,入池日,信号收盘,点击价,次日开盘,现价,1D%,3D%,5D%,10D%,MFE%,MAE%,状态,策略,标签,备注";
    const rows = pool.entries.map((e) => [
      e.code, e.name, e.market, e.entry_date, e.signal_close ?? "", e.entry_price ?? "",
      e.next_open ?? "", e.price ?? "", e.perf.d1 ?? "", e.perf.d3 ?? "", e.perf.d5 ?? "",
      e.perf.d10 ?? "", e.mfe ?? "", e.mae ?? "", e.status,
      e.strategies.map((s) => STRATEGY_NAME[s] || s).join("/"), e.tag, (e.note || "").replace(/[\n,]/g, " "),
    ].join(","));
    const blob = new Blob(["﻿" + [head, ...rows].join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `复盘池_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
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
          <div className="flex items-center gap-2">
            {pool && pool.entries.length > 0 && (
              <button onClick={exportCsv} className="rounded-lg bg-primary/10 px-2.5 py-1 text-xs text-primary hover:bg-primary/20">
                导出 CSV
              </button>
            )}
            <button
              onClick={() => onReload(true)}
              disabled={loading}
              className="text-muted-foreground hover:text-primary"
              title="刷新表现"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            </button>
          </div>
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
                  {["名称", "入池日", "策略", "信号收盘", "现价", "1D", "3D", "5D", "10D", "MFE", "MAE", "状态", "标签", ""].map((h) => (
                    <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pool.entries.map((e) => (
                  <tr key={e.id} className={rowCls} onClick={() => onDetail(e)} title="点击查看详情">
                    <td className="px-2 py-2.5">
                      <span className="font-medium">{e.name}</span>
                      <span className="ml-1.5 font-mono text-xs text-muted-foreground">{e.code}</span>
                      {e.market && e.market !== "A" && (
                        <span className="ml-1.5 rounded bg-sky-500/15 px-1 py-0.5 text-[10px] text-sky-500">{e.market}</span>
                      )}
                    </td>
                    <td className="px-2 py-2.5 font-mono text-xs text-muted-foreground">{e.entry_date}</td>
                    <td className="px-2 py-2.5">
                      {e.strategies.map((s) => (
                        <span key={s} className="mr-1 rounded bg-muted/50 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                          {STRATEGY_NAME[s] || s}
                        </span>
                      ))}
                    </td>
                    <td className="px-2 py-2.5 font-mono text-muted-foreground" title={`点击入池价 ${e.entry_price || "—"} · 次日开盘 ${e.next_open ?? "待"}`}>
                      {e.signal_close ?? "待"}
                    </td>
                    <td className={cn("px-2 py-2.5 font-mono", color(e.change_pct))}>{e.price ?? "—"}</td>
                    {([e.perf.d1, e.perf.d3, e.perf.d5, e.perf.d10] as const).map((v, i) => (
                      <td key={i} className={cn("px-2 py-2.5 font-mono", color(v))}>{pct(v)}</td>
                    ))}
                    <td className={cn("px-2 py-2.5 font-mono text-xs", color(e.mfe))}>{pct(e.mfe)}</td>
                    <td className={cn("px-2 py-2.5 font-mono text-xs", color(e.mae))}>{pct(e.mae)}</td>
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
                            onClick={(ev) => { ev.stopPropagation(); setTagFor(e, t); }}
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
                        onClick={(ev) => { ev.stopPropagation(); removeEntry(e); }}
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
  );
}
