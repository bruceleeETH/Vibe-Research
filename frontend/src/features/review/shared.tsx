// 复盘工作台共享层：格式化函数 / 常量 / 小组件。拆分自 pages/ReviewPool.tsx。
import { Plus } from "lucide-react";
import type { ScanCandidate, PerfAgg } from "@/lib/api";

// A 股红涨绿跌（全站一致）
export const color = (v: number | null | undefined) =>
  v == null ? "text-muted-foreground" : v > 0 ? "text-danger" : v < 0 ? "text-success" : "text-muted-foreground";
export const pct = (v: number | null | undefined) => (v == null ? "待" : `${v > 0 ? "+" : ""}${v}%`);
export const yi = (v: number | null | undefined) => (v == null ? "—" : `${(v / 1e8).toFixed(v >= 1e9 ? 0 : 1)}亿`);
// 主力净额：带符号，亿/万自适应
export const fmtNet = (v: number | null | undefined) => {
  if (v == null) return "—";
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  const a = Math.abs(v);
  return a >= 1e8 ? `${sign}${(a / 1e8).toFixed(1)}亿` : `${sign}${(a / 1e4).toFixed(0)}万`;
};

export const STRATEGY_NAME: Record<string, string> = {
  volume_surge: "放量上涨",
  high_turnover: "高换手",
  value_breakout: "估值突破",
};

export const TAG_STYLE: Record<string, string> = {
  重点关注: "bg-primary/15 text-primary",
  观察: "bg-sky-500/15 text-sky-500",
  备选: "bg-violet-500/15 text-violet-400",
  谨慎: "bg-amber-500/15 text-amber-500",
};

// 四个视角：同一份候选集的四种客观投影
export type View = "rank" | "industry" | "fund" | "review";
export const VIEWS: { key: View; label: string }[] = [
  { key: "rank", label: "综合排序" },
  { key: "industry", label: "行业视角" },
  { key: "fund", label: "资金视角" },
  { key: "review", label: "复盘视角" },
];

// 可点击排序的数值列
export type SortKey = "score" | "price" | "pct" | "open_pct" | "pct_5d" | "amount" | "turnover" | "vol_ratio" | "pe_ttm" | "main_net" | "mcap" | "pct_60d";

export const FACTOR_NAME: Record<string, string> = {
  trend: "趋势", volume: "量能", fund: "资金", valuation: "估值", industry: "行业",
};
export const factorText = (c: ScanCandidate) =>
  Object.entries(c.factors || {}).map(([k, v]) => `${FACTOR_NAME[k]}${v}`).join(" · ");
export const scoreColor = (s: number) =>
  s >= 80 ? "text-danger" : s >= 60 ? "text-primary" : "text-muted-foreground";

// 表格样式：数值列右对齐 + 等宽字体；行 hover 高亮 + 斑马纹；表头吸顶（配合内滚容器）
export const numTd = "px-2 py-2.5 text-right font-mono";
export const rowCls = "border-b border-border/30 even:bg-white/[0.02] hover:bg-primary/5 cursor-pointer transition-colors";
export const theadCls = "sticky top-0 z-10 bg-background/95 backdrop-blur";
export const scrollWrap = "max-h-[calc(100vh-400px)] overflow-auto";

// 市场/股票池静态兜底（首个响应返回前渲染按钮用；以后端返回为准）
export const MARKETS_FALLBACK = [
  { key: "A", name: "A股" }, { key: "HK", name: "港股" },
  { key: "US", name: "美股" }, { key: "ETF", name: "ETF" },
];
export const POOLS_FALLBACK = [
  { key: "all", name: "全市场" }, { key: "hs300", name: "沪深300" },
  { key: "zz500", name: "中证500" }, { key: "hs300zz500", name: "沪深300+中证500" },
  { key: "cyb", name: "创业板" }, { key: "kcb", name: "科创板" },
];

// AskAI 上下文：各视图自行计算并上报给容器
export interface AiCtx { context: string; label: string; suggestions: string[] }

export const candLine = (c: ScanCandidate) =>
  `${c.name}(${c.code}) ${c.industry} 综合${c.score ?? "—"}分(${factorText(c)}) 价${c.price ?? "—"} 涨${pct(c.pct)} 开盘${pct(c.open_pct)} 5日${pct(c.pct_5d)} 成交${yi(c.amount)} 换手${c.turnover ?? "—"}% 量比${c.vol_ratio ?? "—"} PE${c.pe_ttm ?? "—"} 主力${fmtNet(c.main_net)} 60日${pct(c.pct_60d)} 命中[${c.strategies.map((s) => STRATEGY_NAME[s]).join("/")}]`;

export const aggLine = (label: string, a?: PerfAgg | null) =>
  a ? `${label}: 样本${a.n} 成熟${a.mature_n} 均值1D:${pct(a.avg.d1)} 3D:${pct(a.avg.d3)} 5D:${pct(a.avg.d5)} 10D:${pct(a.avg.d10)} d5胜率:${a.win5 ?? "待"}% 盈亏比:${a.pf5 ?? "待"} 超额d5:${pct(a.excess5)} MFE:${pct(a.mfe)} MAE:${pct(a.mae)}` : `${label}: 无`;

// ---- 复用小组件 ----

export function NameCell({ c }: { c: ScanCandidate }) {
  return (
    <td className="px-2 py-2.5">
      <span className="font-medium">{c.name}</span>
      <span className="ml-1.5 font-mono text-xs text-muted-foreground">{c.code}</span>
    </td>
  );
}

export function StrategyChips({ c }: { c: ScanCandidate }) {
  return (
    <div className="flex flex-wrap gap-1">
      {c.strategies.map((s) => (
        <span key={s} className="rounded bg-muted/50 px-1.5 py-0.5 text-[11px] text-muted-foreground">
          {STRATEGY_NAME[s] || s}
        </span>
      ))}
      {c.first_hit ? (
        <span className="rounded bg-success/15 px-1.5 py-0.5 text-[11px] text-success" title="近 5 个存档日内首次命中">首次</span>
      ) : c.hit_streak > 1 ? (
        <span className="rounded bg-muted/40 px-1.5 py-0.5 text-[11px] text-muted-foreground" title={`连续 ${c.hit_streak} 天命中`}>续{c.hit_streak}</span>
      ) : null}
    </div>
  );
}

export function PoolBtn({ c, inPool, onAdd }: { c: ScanCandidate; inPool: boolean; onAdd: (c: ScanCandidate) => void }) {
  return inPool ? (
    <span className="text-[11px] text-muted-foreground/60">已入池</span>
  ) : (
    <button
      onClick={() => onAdd(c)}
      className="inline-flex items-center gap-1 rounded-lg bg-primary/10 px-2 py-1 text-xs text-primary hover:bg-primary/20"
      title="加入复盘池（记录当前价为入池价）"
    >
      <Plus className="h-3 w-3" /> 入池
    </button>
  );
}
