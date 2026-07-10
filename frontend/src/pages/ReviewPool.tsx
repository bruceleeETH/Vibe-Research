import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  Plus, RefreshCw, X, ClipboardList, ScanSearch, Tag,
  ArrowUpDown, ArrowUp, ArrowDown, ChevronDown, ChevronRight, BarChart3,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { api, type ScanResult, type PoolData, type ScanCandidate, type PoolEntry, type ReviewStats, type PerfAgg, type Bar, type FactorWeights, type Announcement } from "@/lib/api";
import { cn } from "@/lib/utils";

// A 股红涨绿跌（全站一致）
const color = (v: number | null | undefined) =>
  v == null ? "text-muted-foreground" : v > 0 ? "text-danger" : v < 0 ? "text-success" : "text-muted-foreground";
const pct = (v: number | null | undefined) => (v == null ? "待" : `${v > 0 ? "+" : ""}${v}%`);
const yi = (v: number | null | undefined) => (v == null ? "—" : `${(v / 1e8).toFixed(v >= 1e9 ? 0 : 1)}亿`);
// 主力净额：带符号，亿/万自适应
const fmtNet = (v: number | null | undefined) => {
  if (v == null) return "—";
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  const a = Math.abs(v);
  return a >= 1e8 ? `${sign}${(a / 1e8).toFixed(1)}亿` : `${sign}${(a / 1e4).toFixed(0)}万`;
};

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

// 四个视角：同一份候选集的四种客观投影（无评分、无推荐）
type View = "rank" | "industry" | "fund" | "review";
const VIEWS: { key: View; label: string }[] = [
  { key: "rank", label: "综合排序" },
  { key: "industry", label: "行业视角" },
  { key: "fund", label: "资金视角" },
  { key: "review", label: "复盘视角" },
];

// 可点击排序的数值列
type SortKey = "score" | "price" | "pct" | "open_pct" | "pct_5d" | "amount" | "turnover" | "vol_ratio" | "pe_ttm" | "main_net" | "mcap" | "pct_60d";

const FACTOR_NAME: Record<string, string> = {
  trend: "趋势", volume: "量能", fund: "资金", valuation: "估值", industry: "行业",
};
const factorText = (c: ScanCandidate) =>
  Object.entries(c.factors || {}).map(([k, v]) => `${FACTOR_NAME[k]}${v}`).join(" · ");
const scoreColor = (s: number) =>
  s >= 80 ? "text-danger" : s >= 60 ? "text-primary" : "text-muted-foreground";

// 迷你日K（SVG 蜡烛 + MA5/10/20 均线，A股红涨绿跌），零依赖。
// 多取 30 根作均线预热，显示近 60 根——窗口起点的 MA20 也是准的。
const MA_DEFS = [
  { n: 5, col: "#f59e0b" },    // MA5 橙
  { n: 10, col: "#3b82f6" },   // MA10 蓝
  { n: 20, col: "#a855f7" },   // MA20 紫
] as const;

function MiniKline({ bars }: { bars: Bar[] }) {
  if (!bars.length) return <p className="py-4 text-center text-xs text-muted-foreground/60">K线加载中…</p>;
  const SHOW = 60;
  const closes = bars.map((b) => b.close);
  const maSeries = (n: number) =>
    closes.map((_, i) => (i >= n - 1 ? closes.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n : null));
  const mas = MA_DEFS.map((m) => ({ ...m, vals: maSeries(m.n) }));

  const off = Math.max(0, bars.length - SHOW);
  const view = bars.slice(off);
  const w = 360, h = 110, n = view.length;
  const allVals = [
    ...view.map((b) => b.high), ...view.map((b) => b.low),
    ...mas.flatMap((m) => m.vals.slice(off).filter((v): v is number => v != null)),
  ];
  const hi = Math.max(...allVals);
  const lo = Math.min(...allVals);
  const x = (i: number) => (i + 0.5) * (w / n);
  const y = (v: number) => h - ((v - lo) / (hi - lo || 1)) * (h - 6) - 3;
  const bw = Math.max(1.5, (w / n) * 0.6);
  const polyline = (vals: (number | null)[]) =>
    vals.slice(off).map((v, i) => (v == null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`))
      .filter(Boolean).join(" ");

  return (
    <div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full">
        {view.map((b, i) => {
          const col = b.close >= b.open ? "#ef4444" : "#10b981";
          return (
            <g key={b.date}>
              <line x1={x(i)} x2={x(i)} y1={y(b.high)} y2={y(b.low)} stroke={col} strokeWidth="1" />
              <rect x={x(i) - bw / 2} y={y(Math.max(b.open, b.close))} width={bw}
                height={Math.max(1, Math.abs(y(b.open) - y(b.close)))} fill={col} />
            </g>
          );
        })}
        {mas.map((m) => (
          <polyline key={m.n} points={polyline(m.vals)} fill="none" stroke={m.col}
            strokeWidth="1.2" opacity="0.9" strokeLinejoin="round" />
        ))}
      </svg>
      <div className="mt-1 flex flex-wrap gap-x-3 text-[10px]">
        {mas.map((m) => {
          const last = [...m.vals].reverse().find((v) => v != null);
          return (
            <span key={m.n} style={{ color: m.col }}>
              MA{m.n} {last != null ? last.toFixed(2) : "—"}
            </span>
          );
        })}
        <span className="text-muted-foreground/60">收 {closes[closes.length - 1]?.toFixed(2)}</span>
      </div>
    </div>
  );
}

// 表格样式：数值列右对齐 + 等宽字体；行 hover 高亮 + 斑马纹；表头吸顶（配合内滚容器）
const numTd = "px-2 py-2.5 text-right font-mono";
const rowCls = "border-b border-border/30 even:bg-white/[0.02] hover:bg-primary/5 cursor-pointer transition-colors";
const theadCls = "sticky top-0 z-10 bg-background/95 backdrop-blur";
const scrollWrap = "max-h-[calc(100vh-400px)] overflow-auto";

// 市场/股票池静态兜底（首个响应返回前渲染按钮用；以后端返回为准）
const MARKETS_FALLBACK = [
  { key: "A", name: "A股" }, { key: "HK", name: "港股" },
  { key: "US", name: "美股" }, { key: "ETF", name: "ETF" },
];
const POOLS_FALLBACK = [
  { key: "all", name: "全市场" }, { key: "hs300", name: "沪深300" },
  { key: "zz500", name: "中证500" }, { key: "hs300zz500", name: "沪深300+中证500" },
  { key: "cyb", name: "创业板" }, { key: "kcb", name: "科创板" },
];

export function ReviewPool() {
  const [tab, setTab] = useState<"scan" | "pool" | "stats">("scan");
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [view, setView] = useState<View>("rank");
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [pool, setPool] = useState<PoolData | null>(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [poolLoading, setPoolLoading] = useState(false);
  const [market, setMarket] = useState("A");
  const [stockPool, setStockPool] = useState("all");
  const [strategy, setStrategy] = useState<string>("all");
  const [hideFlagged, setHideFlagged] = useState(true);
  const [minAmount3, setMinAmount3] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortAsc, setSortAsc] = useState(false);
  const [minScore, setMinScore] = useState(0);
  const [firstOnly, setFirstOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [sampleDays, setSampleDays] = useState<import("@/lib/api").SampleDaySummary[]>([]);
  const [sampleDay, setSampleDay] = useState<string | null>(null);
  const [sampleEntries, setSampleEntries] = useState<import("@/lib/api").SampleEntry[]>([]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [manualInput, setManualInput] = useState("");
  const [detail, setDetail] = useState<ScanCandidate | null>(null);
  const [detailBars, setDetailBars] = useState<Bar[]>([]);
  const [detailAnns, setDetailAnns] = useState<Announcement[]>([]);
  const [weights, setWeights] = useState<FactorWeights | null>(null);
  const [weightsOpen, setWeightsOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // 详情栏打开时拉迷你K线 + 近期公告（A股）
  useEffect(() => {
    setDetailBars([]);
    setDetailAnns([]);
    if (!detail) return;
    api.reviewKline(detail.code, detail.secid, detail.market || "A", 90).then(setDetailBars).catch(() => {});
    if ((detail.market || "A") === "A") {
      api.announcements(detail.code).then((a) => setDetailAnns(a.slice(0, 5))).catch(() => {});
    }
  }, [detail?.code]);

  // 当前市场/池的引用：stale 自动重取时校验，避免切换市场后被旧请求覆盖
  const currentKey = useRef("A:all");

  const loadScan = (refresh = false, m = market, p = stockPool, retry = 0) => {
    currentKey.current = `${m}:${p}`;
    setScanLoading(true);
    setErr(null);
    api.reviewScan(m, p, refresh)
      .then((d) => {
        if (currentKey.current !== `${m}:${p}`) return;   // 已切换市场/池，丢弃
        setScan(d);
        // 后端返回 stale = 旧数据 + 正在后台刷新 → 几秒后自动重取（最多 3 次）
        if (d.stale && retry < 3) {
          setTimeout(() => {
            if (currentKey.current === `${m}:${p}`) loadScan(false, m, p, retry + 1);
          }, 6000);
        }
      })
      .catch((e) => setErr(e.message))
      .finally(() => setScanLoading(false));
  };
  const switchMarket = (m: string) => {
    setMarket(m);
    if (m !== "A") setStockPool("all");
    setStrategy("all");
    loadScan(false, m, m === "A" ? stockPool : "all");
  };
  const switchPool = (p: string) => {
    setStockPool(p);
    loadScan(false, market, p);
  };
  const loadPool = (refresh = false) => {
    setPoolLoading(true);
    api.reviewPool(refresh)
      .then(setPool)
      .catch((e) => setErr(e.message))
      .finally(() => setPoolLoading(false));
  };
  const loadStats = () => {
    setStatsLoading(true);
    api.reviewStats().then(setStats).catch((e) => setErr(e.message)).finally(() => setStatsLoading(false));
  };
  useEffect(() => {
    loadScan();
    loadPool();
    loadStats();
  }, []);
  useEffect(() => {
    if (tab === "stats") api.reviewSampleDays().then(setSampleDays).catch(() => {});
  }, [tab]);
  const openSampleDay = (d: string) => {
    if (sampleDay === d) { setSampleDay(null); return; }
    setSampleDay(d);
    api.reviewSampleDay(d).then(setSampleEntries).catch((e) => toast.error(e.message));
  };

  const poolCodesToday = useMemo(() => {
    const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
    return new Set((pool?.entries || []).filter((e) => e.entry_date === today).map((e) => e.code));
  }, [pool]);

  // 过滤（策略 chips + 提示项 + 成交额，对四个视角全局生效）
  const filtered = useMemo(() => {
    let rows = scan?.candidates || [];
    if (strategy !== "all") rows = rows.filter((c) => c.strategies.includes(strategy));
    if (hideFlagged) rows = rows.filter((c) => c.flags.length === 0);
    if (minAmount3) rows = rows.filter((c) => (c.amount ?? 0) >= 3e8);
    if (minScore > 0) rows = rows.filter((c) => (c.score ?? 0) >= minScore);
    if (firstOnly) rows = rows.filter((c) => c.first_hit);
    const q = search.trim().toLowerCase();
    if (q) rows = rows.filter((c) => c.code.toLowerCase().includes(q) || c.name.toLowerCase().includes(q));
    return rows;
  }, [scan, strategy, hideFlagged, minAmount3, minScore, firstOnly, search]);

  // 排序：表头点击优先；否则按视角默认（皆为公开的客观键，null 沉底）
  const sorted = useMemo(() => {
    const rows = [...filtered];
    const nul = (v: number | null) => (v == null ? -Infinity : v);
    if (sortKey) {
      rows.sort((a, b) => (sortAsc ? nul(a[sortKey]) - nul(b[sortKey]) : nul(b[sortKey]) - nul(a[sortKey])));
    } else if (view === "fund") {
      rows.sort((a, b) => nul(b.main_net) - nul(a.main_net));
    } else if (view === "rank") {
      rows.sort((a, b) => (b.score ?? 0) - (a.score ?? 0) || (b.amount ?? 0) - (a.amount ?? 0));
    } // industry / review 维持成交额降序（后端序）
    return rows;
  }, [filtered, sortKey, sortAsc, view]);

  // 行业分组聚合（客观计数与合计）
  const groups = useMemo(() => {
    if (view !== "industry") return [];
    const m = new Map<string, ScanCandidate[]>();
    for (const c of sorted) {
      const k = c.industry || "未分类";
      const arr = m.get(k) || [];
      arr.push(c);
      m.set(k, arr);
    }
    return [...m.entries()]
      .map(([name, rows]) => ({
        name,
        rows,
        amountSum: rows.reduce((s, r) => s + (r.amount ?? 0), 0),
        avgPct: rows.reduce((s, r) => s + (r.pct ?? 0), 0) / rows.length,
        netSum: rows.some((r) => r.main_net != null)
          ? rows.reduce((s, r) => s + (r.main_net ?? 0), 0)
          : null,
      }))
      .sort((a, b) => b.rows.length - a.rows.length || b.amountSum - a.amountSum);
  }, [sorted, view]);

  // 资金条：集合内相对比例（客观可视化，非评分）
  const maxAbsNet = useMemo(
    () => Math.max(1, ...sorted.map((c) => Math.abs(c.main_net ?? 0))),
    [sorted],
  );

  const reviewRows = useMemo(
    () => sorted.filter((c) => c.pool_history.length > 0),
    [sorted],
  );

  const addToPool = async (c: ScanCandidate) => {
    try {
      const r = await api.reviewPoolAdd([{
        code: c.code, name: c.name, price: c.price, secid: c.secid,
        market: c.market || market, strategies: c.strategies,
      }]);
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

  const setTagFor = async (e: PoolEntry, tag: string) => {
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

  const toggleGroup = (name: string) =>
    setCollapsed((s) => {
      const n = new Set(s);
      if (n.has(name)) n.delete(name);
      else n.add(name);
      return n;
    });

  const clickSort = (k: SortKey) => {
    if (sortKey === k) {
      if (!sortAsc) setSortAsc(true);
      else { setSortKey(null); setSortAsc(false); }        // 三态：降 → 升 → 还原默认
    } else { setSortKey(k); setSortAsc(false); }
  };

  // ---- AskAI 上下文：随视角切换喂当前投影（客观数据，结论由用户模型给出）----
  const candLine = (c: ScanCandidate) =>
    `${c.name}(${c.code}) ${c.industry} 综合${c.score ?? "—"}分(${factorText(c)}) 价${c.price ?? "—"} 涨${pct(c.pct)} 开盘${pct(c.open_pct)} 5日${pct(c.pct_5d)} 成交${yi(c.amount)} 换手${c.turnover ?? "—"}% 量比${c.vol_ratio ?? "—"} PE${c.pe_ttm ?? "—"} 主力${fmtNet(c.main_net)} 60日${pct(c.pct_60d)} 命中[${c.strategies.map((s) => STRATEGY_NAME[s]).join("/")}]`;
  const aggLine = (label: string, a?: PerfAgg | null) =>
    a ? `${label}: 样本${a.n} 成熟${a.mature_n} 均值1D:${pct(a.avg.d1)} 3D:${pct(a.avg.d3)} 5D:${pct(a.avg.d5)} 10D:${pct(a.avg.d10)} d5胜率:${a.win5 ?? "待"}% 盈亏比:${a.pf5 ?? "待"} 超额d5:${pct(a.excess5)} MFE:${pct(a.mfe)} MAE:${pct(a.mae)}` : `${label}: 无`;

  const aiContext = useMemo(() => {
    if (tab === "stats") {
      if (!stats) return "统计尚未加载。";
      return [
        `策略表现统计（${stats.updated}，覆盖 ${stats.days} 个交易日，基准 ${stats.bench_name}）。${stats.note}`,
        aggLine("影子样本(无选择偏差)", stats.shadow),
        aggLine(`手动入池(${stats.manual_n}条)`, stats.manual),
        ...Object.values(stats.by_strategy).map((s) => aggLine(`策略·${s.name}`, s)),
        ...stats.by_score.map((b) => aggLine(`综合分${b.band}`, b)),
      ].join("\n");
    }
    if (tab === "pool") {
      const es = pool?.entries || [];
      if (!es.length) return "复盘池为空。";
      return `我的复盘池（入池后真实收盘的客观回看，${pool?.updated}）：\n` + es.map((e) =>
        `${e.name}(${e.code}) 入池${e.entry_date}@${e.entry_price} 现价${e.price ?? "—"} 1D:${pct(e.perf.d1)} 3D:${pct(e.perf.d3)} 5D:${pct(e.perf.d5)} 10D:${pct(e.perf.d10)} ${e.status}${e.tag ? " 标签:" + e.tag : ""}${e.note ? " 备注:" + e.note : ""}`).join("\n");
    }
    const mkt = (scan?.markets || MARKETS_FALLBACK).find((m) => m.key === scan?.market)?.name || "A股";
    const pl = (scan?.pools || POOLS_FALLBACK).find((p) => p.key === scan?.pool)?.name || "全市场";
    const head = `候选扫描（${mkt} · ${pl} · 客观阈值硬筛，${scan?.generated_at}，扫描 ${scan?.scanned} 只）·`;
    if (view === "industry") {
      if (!groups.length) return "今日候选扫描暂无结果。";
      return `${head} 行业视角：\n` + groups.map((g) =>
        `【${g.name}】${g.rows.length} 只 · 合计成交${yi(g.amountSum)} · 平均涨幅${g.avgPct.toFixed(2)}%${g.netSum != null ? " · 主力合计" + fmtNet(g.netSum) : ""}\n` +
        g.rows.slice(0, 8).map((c) => "  " + candLine(c)).join("\n")).join("\n");
    }
    if (view === "review") {
      if (!reviewRows.length) return "今日候选中没有带复盘池历史的标的。";
      return `${head} 复盘视角（候选×历史入池真实表现）：\n` + reviewRows.map((c) =>
        candLine(c) + "\n" + c.pool_history.map((h) =>
          `  ↳ ${h.entry_date} 入池@${h.entry_price} 1D:${pct(h.perf.d1)} 3D:${pct(h.perf.d3)} 5D:${pct(h.perf.d5)} 10D:${pct(h.perf.d10)}${h.mature ? " 成熟" : ""}${h.tag ? " 标签:" + h.tag : ""}`).join("\n")).join("\n");
    }
    if (!sorted.length) return "今日候选扫描暂无结果。";
    return `${head} ${view === "fund" ? "资金视角（按主力净额降序）" : "综合排序（命中策略数→成交额）"}，当前视图 ${sorted.length} 只：\n` +
      sorted.slice(0, 40).map(candLine).join("\n");
  }, [tab, view, sorted, groups, reviewRows, scan, pool, stats]);

  const aiSuggestions =
    tab === "stats"
      ? ["哪个策略的风险收益比最好", "手动挑选比影子样本强吗", "高分段是否显著跑赢低分段", "根据统计建议怎么调因子权重"]
      : tab === "pool"
      ? ["帮我复盘这批票的整体表现", "哪类策略命中的票走得更好", "成熟样本里有什么共性"]
      : view === "industry"
        ? ["哪个板块的候选最值得细看", "候选扎堆的行业和今天板块资金一致吗", "各板块候选的量价有什么差异"]
        : view === "fund"
          ? ["主力净流入靠前的票量价结构怎么样", "资金流入但涨幅不大的有哪些", "这批票的资金面风险在哪"]
          : view === "review"
            ? ["历史样本的表现说明什么", "哪类策略的历史样本走得更好", "再次被筛出意味着什么"]
            : ["按行业帮我分组梳理", "这批票里哪些量价结构值得细看", "各自的主要风险是什么"];

  // ---- 复用小组件 ----
  const SortTh = ({ k, label }: { k: SortKey; label: string }) => (
    <th className="whitespace-nowrap px-2 py-2 text-right font-medium">
      <button onClick={() => clickSort(k)} className="inline-flex items-center gap-0.5 hover:text-primary" title="点击排序">
        {label}
        {sortKey === k ? (sortAsc ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />) : <ArrowUpDown className="h-3 w-3 opacity-40" />}
      </button>
    </th>
  );
  const NameCell = ({ c }: { c: ScanCandidate }) => (
    <td className="px-2 py-2.5">
      <span className="font-medium">{c.name}</span>
      <span className="ml-1.5 font-mono text-xs text-muted-foreground">{c.code}</span>
    </td>
  );
  const StrategyChips = ({ c }: { c: ScanCandidate }) => (
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
  const PoolBtn = ({ c }: { c: ScanCandidate }) =>
    poolCodesToday.has(c.code) ? (
      <span className="text-[11px] text-muted-foreground/60">已入池</span>
    ) : (
      <button
        onClick={() => addToPool(c)}
        className="inline-flex items-center gap-1 rounded-lg bg-primary/10 px-2 py-1 text-xs text-primary hover:bg-primary/20"
        title="加入复盘池（记录当前价为入池价）"
      >
        <Plus className="h-3 w-3" /> 入池
      </button>
    );
  const FundBar = ({ v }: { v: number | null }) => (
    <div className="h-1.5 w-24 overflow-hidden rounded bg-muted/40">
      {v != null && (
        <div
          className={cn("h-full rounded", v >= 0 ? "bg-danger/70" : "bg-success/70")}
          style={{ width: `${Math.min(100, (Math.abs(v) / maxAbsNet) * 100)}%` }}
        />
      )}
    </div>
  );

  // 综合排序 / 行业视角共用的明细行
  // 综合分单元格：悬停显示五因子拆解（点击行可打开详情栏看条形图）
  const ScoreCell = ({ c }: { c: ScanCandidate }) => (
    <td className="px-2 py-2.5 text-right">
      <span
        className={cn("cursor-help font-mono text-base font-bold", scoreColor(c.score ?? 0))}
        title={`因子拆解：${factorText(c)}（权重：趋势25 量能25 资金20 估值15 行业15）`}
      >
        {c.score ?? "—"}
      </span>
    </td>
  );
  const DetailRow = ({ c, showIndustry = true }: { c: ScanCandidate; showIndustry?: boolean }) => (
    <tr className={rowCls} onClick={() => setDetail(c)} title="点击查看详情">
      <NameCell c={c} />
      {showIndustry && <td className="max-w-32 truncate px-2 py-2.5 text-xs text-muted-foreground">{c.industry || "—"}</td>}
      <td className="px-2 py-2.5"><StrategyChips c={c} /></td>
      <ScoreCell c={c} />
      <td className={cn(numTd, "text-muted-foreground")}>{c.price ?? "—"}</td>
      <td className={cn(numTd, color(c.pct))}>{pct(c.pct)}</td>
      <td className={cn(numTd, "text-xs", color(c.open_pct))}>{pct(c.open_pct)}</td>
      <td className={cn(numTd, "text-xs", color(c.pct_5d))}>{pct(c.pct_5d)}</td>
      <td className={cn(numTd, "text-muted-foreground")}>{yi(c.amount)}</td>
      <td className={cn(numTd, "text-muted-foreground")}>{c.turnover ?? "—"}</td>
      <td className={cn(numTd, "text-muted-foreground")}>{c.vol_ratio ?? "—"}</td>
      <td className={cn(numTd, "text-muted-foreground")}>{c.pe_ttm ?? "—"}</td>
      <td className={cn(numTd, "text-xs", color(c.main_net))}>{fmtNet(c.main_net)}</td>
      <td className={cn(numTd, "text-xs", color(c.pct_60d))}>{pct(c.pct_60d)}</td>
      <td className={cn(numTd, "text-xs text-muted-foreground")}>{yi(c.mcap)}</td>
      <td className="px-2 py-2.5">
        {c.flags.map((f) => (
          <span key={f} className="mr-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] text-amber-500">{f}</span>
        ))}
      </td>
      <td className="px-2 py-2.5" onClick={(e) => e.stopPropagation()}><PoolBtn c={c} /></td>
    </tr>
  );
  const DetailHead = ({ showIndustry = true }: { showIndustry?: boolean }) => (
    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
      <th className="whitespace-nowrap px-2 py-2 font-medium">名称</th>
      {showIndustry && <th className="whitespace-nowrap px-2 py-2 font-medium">行业</th>}
      <th className="whitespace-nowrap px-2 py-2 font-medium">命中策略</th>
      <SortTh k="score" label="综合" />
      <SortTh k="price" label="股价" />
      <SortTh k="pct" label="涨跌%" />
      <SortTh k="open_pct" label="开盘%" />
      <SortTh k="pct_5d" label="5日%" />
      <SortTh k="amount" label="成交额" />
      <SortTh k="turnover" label="换手%" />
      <SortTh k="vol_ratio" label="量比" />
      <SortTh k="pe_ttm" label="PE(TTM)" />
      <SortTh k="main_net" label="主力净额" />
      <SortTh k="pct_60d" label="60日%" />
      <SortTh k="mcap" label="市值" />
      <th className="whitespace-nowrap px-2 py-2 font-medium">提示</th>
      <th className="px-2 py-2" />
    </tr>
  );

  const empty = (
    <p className="py-10 text-center text-sm text-muted-foreground/60">
      当前条件下没有候选（非交易时段量比/换手可能失真，可切换过滤条件或稍后重扫）。
    </p>
  );

  return (
    <div>
      <PageHeader
        title="复盘工作台"
        subtitle="阈值硬筛候选 → 五因子综合分 → 入池记录 → 1D/3D/5D/10D 真实表现回看。个人复盘工具，评分算法公开可调，数据只存本地。"
        actions={<AskAiButton context={aiContext} label={tab === "stats" ? "让 AI 解读统计" : tab === "pool" ? "让 AI 复盘" : "让 AI 读候选"} suggestions={aiSuggestions} />}
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
          {scan?.stale && <span className="text-amber-500">数据更新中，先展示上次结果…</span>}
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
          {/* 市场 + 股票池 + 搜索（对齐选股工作台左栏） */}
          <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-border/40 pb-3">
            <span className="text-xs text-muted-foreground">市场</span>
            {(scan?.markets || MARKETS_FALLBACK).map((m) => (
              <button
                key={m.key}
                onClick={() => switchMarket(m.key)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm transition-colors",
                  market === m.key ? "bg-primary/15 font-medium text-primary shadow-glow" : "text-muted-foreground hover:bg-muted/50",
                )}
              >
                {m.name}
              </button>
            ))}
            {market === "A" && (
              <>
                <span className="ml-2 text-xs text-muted-foreground">股票池</span>
                <select
                  value={stockPool}
                  onChange={(e) => switchPool(e.target.value)}
                  className="rounded-lg border border-border bg-transparent px-2 py-1.5 text-sm text-foreground outline-none"
                >
                  {(scan?.pools || POOLS_FALLBACK).map((p) => (
                    <option key={p.key} value={p.key}>{p.name}</option>
                  ))}
                </select>
              </>
            )}
            {market !== "A" && (
              <span className="text-[11px] text-muted-foreground/70">
                成交额单位为{market === "US" ? "美元" : market === "HK" ? "港元" : "人民币"}
              </span>
            )}
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索代码 / 名称"
              className="ml-auto w-44 rounded-lg border border-border bg-black/20 px-2.5 py-1.5 text-sm outline-none focus:border-primary/50"
            />
          </div>
          {scan?.pool_note && (
            <p className="mb-2 text-[11px] text-amber-500">{scan.pool_note}</p>
          )}
          {scan?.adaptive_note && (
            <p className="mb-2 text-[11px] text-sky-500">{scan.adaptive_note}</p>
          )}

          {/* 视角切换（同一候选集的四种客观投影） */}
          <div className="mb-3 flex flex-wrap items-center gap-1.5 border-b border-border/40 pb-3">
            {VIEWS.map((v) => (
              <button
                key={v.key}
                onClick={() => { setView(v.key); setSortKey(null); setSortAsc(false); }}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm transition-colors",
                  view === v.key ? "bg-primary/15 font-medium text-primary shadow-glow" : "text-muted-foreground hover:bg-muted/50",
                )}
              >
                {v.label}
                {v.key === "review" && reviewRows.length > 0 && <span className="ml-1 text-xs opacity-70">（{reviewRows.length}）</span>}
              </button>
            ))}
            <span className="ml-auto text-xs text-muted-foreground">{view === "review" ? reviewRows.length : sorted.length} 只</span>
          </div>

          {/* 策略 chips + 过滤（对四个视角全局生效） */}
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
              隐藏有提示项
            </label>
            <label className="flex cursor-pointer items-center gap-1 text-xs text-muted-foreground">
              <input type="checkbox" checked={minAmount3} onChange={(e) => setMinAmount3(e.target.checked)} />
              成交额＞3亿
            </label>
            <label className="flex cursor-pointer items-center gap-1 text-xs text-muted-foreground" title="近 5 个存档日内首次命中（启动信号，区别于连续放量第 N 天）">
              <input type="checkbox" checked={firstOnly} onChange={(e) => setFirstOnly(e.target.checked)} />
              只看首次命中
            </label>
            <select
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
              className="rounded border border-border bg-transparent px-1.5 py-0.5 text-xs text-muted-foreground outline-none"
              title="最低综合分"
            >
              <option value={0}>综合分不限</option>
              <option value={60}>综合分≥60</option>
              <option value={70}>综合分≥70</option>
              <option value={80}>综合分≥80</option>
            </select>
            <button
              onClick={() => {
                setWeightsOpen(!weightsOpen);
                if (!weights) api.reviewWeights().then(setWeights).catch((e) => toast.error(e.message));
              }}
              className={cn("rounded-full px-3 py-1 text-xs transition-colors",
                weightsOpen ? "bg-primary/15 text-primary" : "bg-muted/40 text-muted-foreground hover:text-foreground")}
            >
              因子权重
            </button>
            <button
              onClick={() => loadScan(true)}
              disabled={scanLoading}
              className="ml-auto text-muted-foreground hover:text-primary"
              title="重新扫描"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", scanLoading && "animate-spin")} />
            </button>
          </div>

          {/* 因子权重面板：保存后自动归一并重算分数 */}
          {weightsOpen && weights && (
            <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-border/40 bg-muted/10 px-3 py-2 text-xs">
              {(["trend", "volume", "fund", "valuation", "industry"] as const).map((k) => (
                <label key={k} className="flex items-center gap-1 text-muted-foreground">
                  {FACTOR_NAME[k]}
                  <input
                    type="number" min={0} max={100}
                    value={Math.round(weights[k] * 100)}
                    onChange={(e) => setWeights({ ...weights, [k]: Number(e.target.value) / 100 })}
                    className="w-14 rounded border border-border bg-black/20 px-1.5 py-0.5 text-right font-mono outline-none focus:border-primary/50"
                  />
                </label>
              ))}
              <button
                onClick={() =>
                  api.reviewWeightsSet(weights)
                    .then((w) => { setWeights(w); toast.success("权重已保存，重算分数中"); loadScan(true); })
                    .catch((e) => toast.error(e.message))}
                className="rounded-lg bg-primary/15 px-3 py-1 font-medium text-primary hover:bg-primary/25"
              >
                保存并重算
              </button>
              <span className="text-muted-foreground/60">保存时自动归一为 100%；建议等「策略表现」积累成熟样本后按数据调整</span>
            </div>
          )}

          <p className="mb-2 text-[11px] text-muted-foreground/70">
            {view === "rank" && "默认按综合分排序（五因子加权：趋势25 量能25 资金20 估值15 行业15，因子为候选集内百分位；悬停分数看拆解）；点击任意数值列表头改排序。"}
            {view === "industry" && "按行业分组：组头为候选数 / 合计成交额 / 平均涨幅 / 主力净额合计（客观聚合），按候选数排组。"}
            {view === "fund" && "按主力净额降序；资金条 = 该票主力净额在当前候选集内的相对比例（客观可视化，非评分）。"}
            {view === "review" && "只列今日候选中曾进过复盘池的票，附历次入池后的真实 1D/3D/5D/10D 表现（客观回放，不构成预测）。"}
          </p>

          {/* ---- 视角内容 ---- */}
          {scanLoading && !scan ? (
            <p className="py-10 text-center text-sm text-muted-foreground/60">扫描中…</p>
          ) : view === "rank" ? (
            sorted.length === 0 ? empty : (
              <div className={scrollWrap}>
                <table className="w-full text-sm">
                  <thead className={theadCls}><DetailHead /></thead>
                  <tbody>{sorted.map((c) => <DetailRow key={c.code} c={c} />)}</tbody>
                </table>
              </div>
            )
          ) : view === "industry" ? (
            groups.length === 0 ? empty : (
              <div className="space-y-2">
                {groups.map((g) => (
                  <div key={g.name} className="overflow-hidden rounded-lg border border-border/40">
                    <button
                      onClick={() => toggleGroup(g.name)}
                      className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 bg-muted/30 px-3 py-2 text-left text-sm hover:bg-muted/50"
                    >
                      {collapsed.has(g.name) ? <ChevronRight className="h-4 w-4 shrink-0" /> : <ChevronDown className="h-4 w-4 shrink-0" />}
                      <span className="font-medium">{g.name}</span>
                      <span className="text-xs text-muted-foreground">{g.rows.length} 只</span>
                      <span className="text-xs text-muted-foreground">合计成交 {yi(g.amountSum)}</span>
                      <span className={cn("font-mono text-xs", color(g.avgPct))}>平均 {pct(Number(g.avgPct.toFixed(2)))}</span>
                      {g.netSum != null && (
                        <span className={cn("font-mono text-xs", color(g.netSum))}>主力合计 {fmtNet(g.netSum)}</span>
                      )}
                    </button>
                    {!collapsed.has(g.name) && (
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead><DetailHead showIndustry={false} /></thead>
                          <tbody>{g.rows.map((c) => <DetailRow key={c.code} c={c} showIndustry={false} />)}</tbody>
                        </table>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )
          ) : view === "fund" ? (
            sorted.length === 0 ? empty : (
              <div className={scrollWrap}>
                <table className="w-full text-sm">
                  <thead className={theadCls}>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      <th className="whitespace-nowrap px-2 py-2 font-medium">名称</th>
                      <th className="whitespace-nowrap px-2 py-2 font-medium">行业</th>
                      <SortTh k="score" label="综合" />
                      <SortTh k="main_net" label="主力净额" />
                      <th className="whitespace-nowrap px-2 py-2 text-right font-medium">超大单</th>
                      <th className="whitespace-nowrap px-2 py-2 text-right font-medium">净占比%</th>
                      <th className="whitespace-nowrap px-2 py-2 font-medium">资金</th>
                      <SortTh k="pct" label="涨跌%" />
                      <SortTh k="amount" label="成交额" />
                      <th className="whitespace-nowrap px-2 py-2 font-medium">命中策略</th>
                      <th className="px-2 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((c) => (
                      <tr key={c.code} className={rowCls} onClick={() => setDetail(c)} title="点击查看详情">
                        <NameCell c={c} />
                        <td className="max-w-32 truncate px-2 py-2.5 text-xs text-muted-foreground">{c.industry || "—"}</td>
                        <ScoreCell c={c} />
                        <td className={cn(numTd, color(c.main_net))}>{fmtNet(c.main_net)}</td>
                        <td className={cn(numTd, "text-xs", color(c.super_net))}>{fmtNet(c.super_net)}</td>
                        <td className={cn(numTd, "text-xs", color(c.main_pct))}>{c.main_pct == null ? "—" : `${c.main_pct}%`}</td>
                        <td className="px-2 py-2.5"><FundBar v={c.main_net} /></td>
                        <td className={cn(numTd, color(c.pct))}>{pct(c.pct)}</td>
                        <td className={cn(numTd, "text-muted-foreground")}>{yi(c.amount)}</td>
                        <td className="px-2 py-2.5"><StrategyChips c={c} /></td>
                        <td className="px-2 py-2.5" onClick={(e) => e.stopPropagation()}><PoolBtn c={c} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          ) : (
            /* 复盘视角 */
            reviewRows.length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground/60">
                今日候选中还没有带复盘池历史的票——从候选入池，之后同一只票再次被筛出时，这里会显示它历次入池的真实表现。
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      {["名称", "行业", "命中策略", "涨跌%", "成交额", "历史入池", ""].map((h) => (
                        <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {reviewRows.map((c) => (
                      <Fragment key={c.code}>
                        <tr className={rowCls} onClick={() => setDetail(c)} title="点击查看详情">
                          <NameCell c={c} />
                          <td className="max-w-32 truncate px-2 py-2.5 text-xs text-muted-foreground">{c.industry || "—"}</td>
                          <td className="px-2 py-2.5"><StrategyChips c={c} /></td>
                          <td className={cn("px-2 py-2.5 font-mono", color(c.pct))}>{pct(c.pct)}</td>
                          <td className="px-2 py-2.5 font-mono text-muted-foreground">{yi(c.amount)}</td>
                          <td className="px-2 py-2.5 text-xs text-muted-foreground">
                            {c.pool_history.length} 次 · 成熟 {c.pool_history.filter((h) => h.mature).length}
                          </td>
                          <td className="px-2 py-2.5" onClick={(e) => e.stopPropagation()}><PoolBtn c={c} /></td>
                        </tr>
                        {c.pool_history.map((h) => (
                          <tr key={`${c.code}-${h.entry_date}`} className="border-b border-border/30 bg-muted/20 text-xs">
                            <td className="py-1.5 pl-8 pr-2 text-muted-foreground" colSpan={2}>
                              ↳ {h.entry_date} 入池 @{h.entry_price}
                              {h.tag && <span className={cn("ml-2 rounded px-1.5 py-0.5 text-[11px]", TAG_STYLE[h.tag])}>{h.tag}</span>}
                            </td>
                            <td className="px-2 py-1.5" colSpan={2}>
                              <span className="mr-3 text-muted-foreground">1D <span className={cn("font-mono", color(h.perf.d1))}>{pct(h.perf.d1)}</span></span>
                              <span className="mr-3 text-muted-foreground">3D <span className={cn("font-mono", color(h.perf.d3))}>{pct(h.perf.d3)}</span></span>
                              <span className="mr-3 text-muted-foreground">5D <span className={cn("font-mono", color(h.perf.d5))}>{pct(h.perf.d5)}</span></span>
                              <span className="text-muted-foreground">10D <span className={cn("font-mono", color(h.perf.d10))}>{pct(h.perf.d10)}</span></span>
                            </td>
                            <td className="px-2 py-1.5 text-muted-foreground" colSpan={3}>
                              {h.mature ? "成熟" : "待成熟"}
                            </td>
                          </tr>
                        ))}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}
        </GlassCard>
      ) : tab === "stats" ? (
        <GlassCard glow>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-4 text-sm">
              <span className="flex items-center gap-1.5 font-semibold">
                <BarChart3 className="h-4 w-4 text-primary" /> 策略表现
              </span>
              {stats && (
                <span className="text-xs text-muted-foreground">
                  覆盖 {stats.days} 个交易日 · 影子样本 {stats.shadow_total}（成熟 {stats.shadow_mature}）· 手动入池 {stats.manual_n} · 基准 {stats.bench_name} · {stats.updated}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => api.reviewSamplesCapture().then((r) => { toast.info(r.note || `已存档 ${r.captured} 条`); loadStats(); }).catch((e) => toast.error(e.message))}
                className="rounded-lg bg-primary/10 px-2.5 py-1 text-xs text-primary hover:bg-primary/20"
                title="收盘后调度器会自动存档，这里手动兜底"
              >
                存档今日候选
              </button>
              <button
                onClick={() => api.reviewSamplesUpdate().then((r) => { toast.success(`已更新 ${r.updated} 条`); loadStats(); }).catch((e) => toast.error(e.message))}
                className="rounded-lg bg-primary/10 px-2.5 py-1 text-xs text-primary hover:bg-primary/20"
              >
                更新样本收益
              </button>
              <button onClick={loadStats} disabled={statsLoading} className="text-muted-foreground hover:text-primary" title="刷新">
                <RefreshCw className={cn("h-3.5 w-3.5", statsLoading && "animate-spin")} />
              </button>
            </div>
          </div>

          {!stats || (stats.shadow_total === 0 && stats.manual_n === 0) ? (
            <p className="py-10 text-center text-sm text-muted-foreground/60">
              还没有样本——影子样本会在每个交易日收盘后自动存档（也可点上方「存档今日候选」），满 10 个交易日开始出成熟统计。
            </p>
          ) : (
            <div className="space-y-6">
              {([
                ["影子 vs 手动（你的挑选是否创造价值）", [
                  ["影子样本（无选择偏差）", stats.shadow],
                  [`手动入池（${stats.manual_n} 条）`, stats.manual],
                ]],
                ["分策略", Object.values(stats.by_strategy).map((s) => [s.name, s])],
                ["分综合分段（验证评分有效性）", stats.by_score.map((b) => [`综合分 ${b.band}`, b])],
              ] as [string, [string, PerfAgg][]][]).map(([title, rows]) => (
                <div key={title}>
                  <h4 className="mb-1.5 text-sm font-semibold">{title}</h4>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                          <th className="px-2 py-2 font-medium">组</th>
                          {["样本", "成熟", "1D均", "3D均", "5D均", "10D均", "d5胜率", "盈亏比", "超额d5", "MFE均", "MAE均"].map((h) => (
                            <th key={h} className="whitespace-nowrap px-2 py-2 text-right font-medium">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map(([label, a]) => (
                          <tr key={label} className="border-b border-border/30 even:bg-white/[0.02]">
                            <td className="px-2 py-2.5 font-medium">{label}</td>
                            <td className={numTd}>{a.n}</td>
                            <td className={numTd}>{a.mature_n}</td>
                            {(["d1", "d3", "d5", "d10"] as const).map((k) => (
                              <td key={k} className={cn(numTd, color(a.avg[k]))}>{pct(a.avg[k])}</td>
                            ))}
                            <td className={numTd}>{a.win5 == null ? "待" : `${a.win5}%`}</td>
                            <td className={numTd}>{a.pf5 ?? "待"}</td>
                            <td className={cn(numTd, color(a.excess5))}>{pct(a.excess5)}</td>
                            <td className={cn(numTd, color(a.mfe))}>{pct(a.mfe)}</td>
                            <td className={cn(numTd, color(a.mae))}>{pct(a.mae)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
              <p className="text-[11px] leading-relaxed text-muted-foreground/70">{stats.note}</p>

              {/* 存档回看：那天筛出了什么、后来走得怎样 */}
              {sampleDays.length > 0 && (
                <div>
                  <h4 className="mb-1.5 text-sm font-semibold">存档回看</h4>
                  <div className="mb-2 flex flex-wrap gap-1.5">
                    {sampleDays.map((d) => (
                      <button
                        key={d.date}
                        onClick={() => openSampleDay(d.date)}
                        className={cn(
                          "rounded-full px-2.5 py-1 text-xs transition-colors",
                          sampleDay === d.date ? "bg-primary/15 font-medium text-primary" : "bg-muted/40 text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {d.date}（{d.n}{d.mature_n ? ` · 熟${d.mature_n}` : ""}）
                      </button>
                    ))}
                  </div>
                  {sampleDay && (
                    <div className="max-h-96 overflow-auto">
                      <table className="w-full text-sm">
                        <thead className={theadCls}>
                          <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                            <th className="px-2 py-2 font-medium">名称</th>
                            <th className="px-2 py-2 font-medium">行业</th>
                            <th className="px-2 py-2 font-medium">策略</th>
                            {["综合", "当日涨%", "成交额", "信号收盘", "1D", "3D", "5D", "10D", "MFE", "MAE"].map((h) => (
                              <th key={h} className="whitespace-nowrap px-2 py-2 text-right font-medium">{h}</th>
                            ))}
                            <th className="px-2 py-2 font-medium">状态</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sampleEntries.map((e) => (
                            <tr key={e.code} className="border-b border-border/30 even:bg-white/[0.02]">
                              <td className="px-2 py-2">
                                <span className="font-medium">{e.name}</span>
                                <span className="ml-1.5 font-mono text-xs text-muted-foreground">{e.code}</span>
                              </td>
                              <td className="max-w-28 truncate px-2 py-2 text-xs text-muted-foreground">{e.industry || "—"}</td>
                              <td className="px-2 py-2 text-xs text-muted-foreground">{e.strategies.map((s) => STRATEGY_NAME[s] || s).join("/")}</td>
                              <td className={cn(numTd, scoreColor(e.score ?? 0))}>{e.score ?? "—"}</td>
                              <td className={cn(numTd, color(e.pct))}>{pct(e.pct)}</td>
                              <td className={cn(numTd, "text-muted-foreground")}>{yi(e.amount)}</td>
                              <td className={cn(numTd, "text-muted-foreground")}>{e.signal_close ?? "—"}</td>
                              {(["d1", "d3", "d5", "d10"] as const).map((k) => (
                                <td key={k} className={cn(numTd, color(e.perf[k]))}>{pct(e.perf[k])}</td>
                              ))}
                              <td className={cn(numTd, color(e.mfe))}>{pct(e.mfe)}</td>
                              <td className={cn(numTd, color(e.mae))}>{pct(e.mae)}</td>
                              <td className="px-2 py-2 text-xs text-muted-foreground">{e.mature ? "成熟" : "待成熟"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
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
              <div className="flex items-center gap-2">
                {pool && pool.entries.length > 0 && (
                  <button
                    onClick={() => {
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
                    }}
                    className="rounded-lg bg-primary/10 px-2.5 py-1 text-xs text-primary hover:bg-primary/20"
                  >
                    导出 CSV
                  </button>
                )}
                <button
                  onClick={() => loadPool(true)}
                  disabled={poolLoading}
                  className="text-muted-foreground hover:text-primary"
                  title="刷新表现"
                >
                  <RefreshCw className={cn("h-3.5 w-3.5", poolLoading && "animate-spin")} />
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
                      <tr key={e.id} className="border-b border-border/30">
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
                                onClick={() => setTagFor(e, t)}
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

      {/* 右侧详情栏：点击候选行打开（因子拆解条形图 / 关键数据 / 入池历史 / 问 AI） */}
      {detail && (
        <aside className="fixed right-0 top-0 z-50 flex h-full w-[400px] flex-col gap-4 overflow-y-auto border-l border-border bg-background/95 p-5 shadow-2xl backdrop-blur">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-lg font-bold">
                {detail.name}
                <span className="ml-2 font-mono text-sm font-normal text-muted-foreground">{detail.code}</span>
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {detail.industry || "—"}
                {detail.market && detail.market !== "A" && <span className="ml-1.5 rounded bg-sky-500/15 px-1 py-0.5 text-[10px] text-sky-500">{detail.market}</span>}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <div onClick={(e) => e.stopPropagation()}><PoolBtn c={detail} /></div>
              <button onClick={() => setDetail(null)} className="text-muted-foreground hover:text-foreground" title="关闭">
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* 综合分 + 因子拆解条形图 */}
          <div className="rounded-lg border border-border/40 p-3">
            <div className="mb-2 flex items-baseline gap-2">
              <span className={cn("font-mono text-3xl font-bold", scoreColor(detail.score ?? 0))}>{detail.score ?? "—"}</span>
              <span className="text-xs text-muted-foreground">综合分 · 权重 趋势25 量能25 资金20 估值15 行业15</span>
            </div>
            <div className="space-y-1.5">
              {(["trend", "volume", "fund", "valuation", "industry"] as const).map((k) => (
                <div key={k} className="flex items-center gap-2">
                  <span className="w-8 shrink-0 text-xs text-muted-foreground">{FACTOR_NAME[k]}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded bg-muted/40">
                    <div className="h-full rounded bg-primary/70" style={{ width: `${detail.factors?.[k] ?? 0}%` }} />
                  </div>
                  <span className="w-8 shrink-0 text-right font-mono text-xs text-muted-foreground">{detail.factors?.[k] ?? "—"}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 迷你日K（近 60 交易日） */}
          <div className="rounded-lg border border-border/40 p-3">
            <p className="mb-1 text-xs font-medium text-muted-foreground">日K · 近 60 个交易日 · MA5/10/20</p>
            <MiniKline bars={detailBars} />
          </div>

          {/* 命中策略 + 提示 */}
          <div className="flex flex-wrap gap-1">
            <StrategyChips c={detail} />
            {detail.flags.map((f) => (
              <span key={f} className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] text-amber-500">{f}</span>
            ))}
          </div>

          {/* 关键数据 */}
          <div className="grid grid-cols-3 gap-x-3 gap-y-2 rounded-lg border border-border/40 p-3 text-sm">
            {([
              ["股价", <span className="font-mono">{detail.price ?? "—"}</span>],
              ["涨跌%", <span className={cn("font-mono", color(detail.pct))}>{pct(detail.pct)}</span>],
              ["开盘%", <span className={cn("font-mono", color(detail.open_pct))}>{pct(detail.open_pct)}</span>],
              ["5日%", <span className={cn("font-mono", color(detail.pct_5d))}>{pct(detail.pct_5d)}</span>],
              ["60日%", <span className={cn("font-mono", color(detail.pct_60d))}>{pct(detail.pct_60d)}</span>],
              ["年初至今", <span className={cn("font-mono", color(detail.pct_ytd))}>{pct(detail.pct_ytd)}</span>],
              ["成交额", <span className="font-mono">{yi(detail.amount)}</span>],
              ["换手%", <span className="font-mono">{detail.turnover ?? "—"}</span>],
              ["量比", <span className="font-mono">{detail.vol_ratio ?? "—"}</span>],
              ["PE(TTM)", <span className="font-mono">{detail.pe_ttm ?? "—"}</span>],
              ["PB", <span className="font-mono">{detail.pb ?? "—"}</span>],
              ["市值", <span className="font-mono">{yi(detail.mcap)}</span>],
              ["主力净额", <span className={cn("font-mono", color(detail.main_net))}>{fmtNet(detail.main_net)}</span>],
              ["超大单", <span className={cn("font-mono", color(detail.super_net))}>{fmtNet(detail.super_net)}</span>],
              ["净占比%", <span className={cn("font-mono", color(detail.main_pct))}>{detail.main_pct ?? "—"}</span>],
            ] as [string, React.ReactNode][]).map(([label, val]) => (
              <div key={label}>
                <p className="text-[11px] text-muted-foreground">{label}</p>
                {val}
              </div>
            ))}
          </div>

          {/* 入池历史 */}
          <div className="rounded-lg border border-border/40 p-3">
            <p className="mb-2 text-xs font-medium text-muted-foreground">历次入池表现</p>
            {detail.pool_history.length === 0 ? (
              <p className="text-xs text-muted-foreground/60">该票还没进过复盘池。</p>
            ) : (
              <div className="space-y-2 text-xs">
                {detail.pool_history.map((h) => (
                  <div key={h.entry_date} className="rounded bg-muted/20 px-2 py-1.5">
                    <p className="text-muted-foreground">
                      {h.entry_date} 入池 @{h.entry_price}
                      {h.tag && <span className={cn("ml-1.5 rounded px-1 py-0.5 text-[10px]", TAG_STYLE[h.tag])}>{h.tag}</span>}
                      <span className="ml-1.5">{h.mature ? "成熟" : "待成熟"}</span>
                    </p>
                    <p className="mt-0.5">
                      {(["d1", "d3", "d5", "d10"] as const).map((k, i) => (
                        <span key={k} className="mr-3 text-muted-foreground">
                          {["1D", "3D", "5D", "10D"][i]} <span className={cn("font-mono", color(h.perf[k]))}>{pct(h.perf[k])}</span>
                        </span>
                      ))}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 近期公告（A股） */}
          {detailAnns.length > 0 && (
            <div className="rounded-lg border border-border/40 p-3">
              <p className="mb-2 text-xs font-medium text-muted-foreground">近期公告</p>
              <div className="space-y-1.5 text-xs">
                {detailAnns.map((a) => (
                  <a key={a.url + a.title} href={a.url} target="_blank" rel="noreferrer"
                     className="block truncate text-muted-foreground hover:text-primary" title={a.title}>
                    <span className="mr-1.5 font-mono text-muted-foreground/60">{a.date}</span>{a.title}
                  </a>
                ))}
              </div>
            </div>
          )}

          <div onClick={(e) => e.stopPropagation()}>
            <AskAiButton
              context={`个股候选详情：\n${candLine(detail)}${detail.pool_history.length ? "\n历次入池：\n" + detail.pool_history.map((h) => `${h.entry_date}@${h.entry_price} 1D:${pct(h.perf.d1)} 3D:${pct(h.perf.d3)} 5D:${pct(h.perf.d5)} 10D:${pct(h.perf.d10)}`).join("\n") : ""}`}
              label="问 AI 这只票"
              suggestions={["这只票的量价结构怎么看", "它的主要风险点是什么", "和同行业候选比它突出在哪"]}
            />
          </div>
        </aside>
      )}

      <Disclaimer />
    </div>
  );
}
