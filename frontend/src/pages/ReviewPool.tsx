// 复盘工作台容器：tab 状态 + 复盘池数据 + AI 上下文汇集 + 视图组装。
// 各视图拆分在 features/review/*（ScanView / PoolView / StatsView / DetailDrawer）。
import { useEffect, useMemo, useState } from "react";
import { ScanSearch, ClipboardList, BarChart3 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { api, type PoolData, type ScanCandidate } from "@/lib/api";
import { cn } from "@/lib/utils";
import { pct, type AiCtx } from "@/features/review/shared";
import { ScanView } from "@/features/review/ScanView";
import { PoolView } from "@/features/review/PoolView";
import { StatsView } from "@/features/review/StatsView";
import { DetailDrawer } from "@/features/review/DetailDrawer";

type Tab = "scan" | "pool" | "stats";

export function ReviewPool() {
  const [tab, setTab] = useState<Tab>("scan");
  const [pool, setPool] = useState<PoolData | null>(null);
  const [poolLoading, setPoolLoading] = useState(false);
  const [detail, setDetail] = useState<ScanCandidate | null>(null);
  // 各视图上报的 AI 上下文（视图常驻挂载，按当前 tab 取用）
  const [aiCtxs, setAiCtxs] = useState<Partial<Record<Tab, AiCtx>>>({});

  const loadPool = (refresh = false) => {
    setPoolLoading(true);
    api.reviewPool(refresh)
      .then(setPool)
      .catch((e) => toast.error(e.message))
      .finally(() => setPoolLoading(false));
  };
  useEffect(() => { loadPool(); }, []);

  const poolCodesToday = useMemo(() => {
    const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
    return new Set((pool?.entries || []).filter((e) => e.entry_date === today).map((e) => e.code));
  }, [pool]);
  const inPoolToday = (code: string) => poolCodesToday.has(code);

  const addToPool = async (c: ScanCandidate) => {
    try {
      const r = await api.reviewPoolAdd([{
        code: c.code, name: c.name, price: c.price, secid: c.secid,
        market: c.market || "A", strategies: c.strategies,
      }]);
      toast[r.added ? "success" : "info"](r.added ? `${c.name} 已入复盘池` : `${c.name} 今日已在池中`);
      if (r.added) loadPool();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const setCtx = (k: Tab) => (ctx: AiCtx) => setAiCtxs((s) => ({ ...s, [k]: ctx }));

  // 复盘池的 AI 上下文由容器计算（池数据在容器）
  useEffect(() => {
    const es = pool?.entries || [];
    const context = !es.length ? "复盘池为空。" :
      `我的复盘池（入池后真实收盘的客观回看，${pool?.updated}）：\n` + es.map((e) =>
        `${e.name}(${e.code}) 入池${e.entry_date}@${e.entry_price} 现价${e.price ?? "—"} 1D:${pct(e.perf.d1)} 3D:${pct(e.perf.d3)} 5D:${pct(e.perf.d5)} 10D:${pct(e.perf.d10)} ${e.status}${e.tag ? " 标签:" + e.tag : ""}${e.note ? " 备注:" + e.note : ""}`).join("\n");
    setAiCtxs((s) => ({
      ...s,
      pool: { context, label: "让 AI 复盘", suggestions: ["帮我复盘这批票的整体表现", "哪类策略命中的票走得更好", "成熟样本里有什么共性"] },
    }));
  }, [pool]);

  const ai = aiCtxs[tab];

  return (
    <div>
      <PageHeader
        title="复盘工作台"
        subtitle="阈值硬筛候选 → 五因子综合分 → 入池记录 → 1D/3D/5D/10D 真实表现回看。个人复盘工具，评分算法公开可调，数据只存本地。"
        actions={ai && <AskAiButton context={ai.context} label={ai.label} suggestions={ai.suggestions} />}
      />

      {/* Tab 切换 + 状态条 */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-1.5">
          {([["scan", "候选扫描", ScanSearch], ["pool", "复盘池", ClipboardList], ["stats", "策略表现", BarChart3]] as const).map(([k, label, Icon]) => (
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
          {pool && <span>复盘样本 {pool.total} 条 · 成熟 {pool.mature_count}</span>}
        </div>
      </div>

      {/* 视图常驻挂载（CSS 隐藏切换）：保留各 tab 的过滤/排序/滚动状态 */}
      <div className={tab === "scan" ? "" : "hidden"}>
        <ScanView onDetail={setDetail} inPoolToday={inPoolToday} onAddToPool={addToPool} onAiCtx={setCtx("scan")} />
      </div>
      <div className={tab === "pool" ? "" : "hidden"}>
        <PoolView pool={pool} loading={poolLoading} onReload={loadPool} />
      </div>
      <div className={tab === "stats" ? "" : "hidden"}>
        <StatsView onAiCtx={setCtx("stats")} />
      </div>

      {detail && (
        <DetailDrawer detail={detail} onClose={() => setDetail(null)} inPoolToday={inPoolToday} onAddToPool={addToPool} />
      )}

      <Disclaimer />
    </div>
  );
}
