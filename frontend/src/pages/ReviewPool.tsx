import { Fragment, useEffect, useMemo, useState } from "react";
import {
  Plus, RefreshCw, X, ClipboardList, ScanSearch, Tag,
  ArrowUpDown, ArrowUp, ArrowDown, ChevronDown, ChevronRight,
} from "lucide-react";
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
type SortKey = "score" | "pct" | "amount" | "turnover" | "vol_ratio" | "pe_ttm" | "main_net" | "mcap" | "pct_60d";

const FACTOR_NAME: Record<string, string> = {
  trend: "趋势", volume: "量能", fund: "资金", valuation: "估值", industry: "行业",
};
const factorText = (c: ScanCandidate) =>
  Object.entries(c.factors || {}).map(([k, v]) => `${FACTOR_NAME[k]}${v}`).join(" · ");
const scoreColor = (s: number) =>
  s >= 80 ? "text-danger" : s >= 60 ? "text-primary" : "text-muted-foreground";

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
  const [tab, setTab] = useState<"scan" | "pool">("scan");
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
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [manualInput, setManualInput] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const loadScan = (refresh = false, m = market, p = stockPool) => {
    setScanLoading(true);
    setErr(null);
    api.reviewScan(m, p, refresh)
      .then(setScan)
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
  useEffect(() => {
    loadScan();
    loadPool();
  }, []);

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
    const q = search.trim().toLowerCase();
    if (q) rows = rows.filter((c) => c.code.toLowerCase().includes(q) || c.name.toLowerCase().includes(q));
    return rows;
  }, [scan, strategy, hideFlagged, minAmount3, minScore, search]);

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
    `${c.name}(${c.code}) ${c.industry} 综合${c.score ?? "—"}分(${factorText(c)}) 涨${pct(c.pct)} 成交${yi(c.amount)} 换手${c.turnover ?? "—"}% 量比${c.vol_ratio ?? "—"} PE${c.pe_ttm ?? "—"} 主力${fmtNet(c.main_net)} 60日${pct(c.pct_60d)} 命中[${c.strategies.map((s) => STRATEGY_NAME[s]).join("/")}]`;
  const aiContext = useMemo(() => {
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
  }, [tab, view, sorted, groups, reviewRows, scan, pool]);

  const aiSuggestions =
    tab === "pool"
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
    <th className="whitespace-nowrap px-2 py-2 font-medium">
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
  // 综合分单元格：悬停显示五因子拆解
  const ScoreCell = ({ c }: { c: ScanCandidate }) => (
    <td className="px-2 py-2.5">
      <span
        className={cn("cursor-help font-mono text-base font-bold", scoreColor(c.score ?? 0))}
        title={`因子拆解：${factorText(c)}（权重：趋势25 量能25 资金20 估值15 行业15）`}
      >
        {c.score ?? "—"}
      </span>
    </td>
  );
  const DetailRow = ({ c, showIndustry = true }: { c: ScanCandidate; showIndustry?: boolean }) => (
    <tr className="border-b border-border/30">
      <NameCell c={c} />
      {showIndustry && <td className="max-w-32 truncate px-2 py-2.5 text-xs text-muted-foreground">{c.industry || "—"}</td>}
      <td className="px-2 py-2.5"><StrategyChips c={c} /></td>
      <ScoreCell c={c} />
      <td className={cn("px-2 py-2.5 font-mono", color(c.pct))}>{pct(c.pct)}</td>
      <td className="px-2 py-2.5 font-mono text-muted-foreground">{yi(c.amount)}</td>
      <td className="px-2 py-2.5 font-mono text-muted-foreground">{c.turnover ?? "—"}</td>
      <td className="px-2 py-2.5 font-mono text-muted-foreground">{c.vol_ratio ?? "—"}</td>
      <td className="px-2 py-2.5 font-mono text-muted-foreground">{c.pe_ttm ?? "—"}</td>
      <td className={cn("px-2 py-2.5 font-mono text-xs", color(c.main_net))}>{fmtNet(c.main_net)}</td>
      <td className={cn("px-2 py-2.5 font-mono text-xs", color(c.pct_60d))}>{pct(c.pct_60d)}</td>
      <td className="px-2 py-2.5 font-mono text-xs text-muted-foreground">{yi(c.mcap)}</td>
      <td className="px-2 py-2.5">
        {c.flags.map((f) => (
          <span key={f} className="mr-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] text-amber-500">{f}</span>
        ))}
      </td>
      <td className="px-2 py-2.5"><PoolBtn c={c} /></td>
    </tr>
  );
  const DetailHead = ({ showIndustry = true }: { showIndustry?: boolean }) => (
    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
      <th className="whitespace-nowrap px-2 py-2 font-medium">名称</th>
      {showIndustry && <th className="whitespace-nowrap px-2 py-2 font-medium">行业</th>}
      <th className="whitespace-nowrap px-2 py-2 font-medium">命中策略</th>
      <SortTh k="score" label="综合" />
      <SortTh k="pct" label="涨跌%" />
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
        actions={<AskAiButton context={aiContext} label={tab === "pool" ? "让 AI 复盘" : "让 AI 读候选"} suggestions={aiSuggestions} />}
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
              onClick={() => loadScan(true)}
              disabled={scanLoading}
              className="ml-auto text-muted-foreground hover:text-primary"
              title="重新扫描"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", scanLoading && "animate-spin")} />
            </button>
          </div>

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
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><DetailHead /></thead>
                  <tbody>{sorted.slice(0, 100).map((c) => <DetailRow key={c.code} c={c} />)}</tbody>
                </table>
                {sorted.length > 100 && (
                  <p className="mt-2 text-center text-xs text-muted-foreground/60">只显示前 100 条，可用过滤条件收窄。</p>
                )}
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
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      <th className="whitespace-nowrap px-2 py-2 font-medium">名称</th>
                      <th className="whitespace-nowrap px-2 py-2 font-medium">行业</th>
                      <SortTh k="score" label="综合" />
                      <SortTh k="main_net" label="主力净额" />
                      <th className="whitespace-nowrap px-2 py-2 font-medium">超大单</th>
                      <th className="whitespace-nowrap px-2 py-2 font-medium">净占比%</th>
                      <th className="whitespace-nowrap px-2 py-2 font-medium">资金</th>
                      <SortTh k="pct" label="涨跌%" />
                      <SortTh k="amount" label="成交额" />
                      <th className="whitespace-nowrap px-2 py-2 font-medium">命中策略</th>
                      <th className="px-2 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.slice(0, 100).map((c) => (
                      <tr key={c.code} className="border-b border-border/30">
                        <NameCell c={c} />
                        <td className="max-w-32 truncate px-2 py-2.5 text-xs text-muted-foreground">{c.industry || "—"}</td>
                        <ScoreCell c={c} />
                        <td className={cn("px-2 py-2.5 font-mono", color(c.main_net))}>{fmtNet(c.main_net)}</td>
                        <td className={cn("px-2 py-2.5 font-mono text-xs", color(c.super_net))}>{fmtNet(c.super_net)}</td>
                        <td className={cn("px-2 py-2.5 font-mono text-xs", color(c.main_pct))}>{c.main_pct == null ? "—" : `${c.main_pct}%`}</td>
                        <td className="px-2 py-2.5"><FundBar v={c.main_net} /></td>
                        <td className={cn("px-2 py-2.5 font-mono", color(c.pct))}>{pct(c.pct)}</td>
                        <td className="px-2 py-2.5 font-mono text-muted-foreground">{yi(c.amount)}</td>
                        <td className="px-2 py-2.5"><StrategyChips c={c} /></td>
                        <td className="px-2 py-2.5"><PoolBtn c={c} /></td>
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
                        <tr className="border-b border-border/20">
                          <NameCell c={c} />
                          <td className="max-w-32 truncate px-2 py-2.5 text-xs text-muted-foreground">{c.industry || "—"}</td>
                          <td className="px-2 py-2.5"><StrategyChips c={c} /></td>
                          <td className={cn("px-2 py-2.5 font-mono", color(c.pct))}>{pct(c.pct)}</td>
                          <td className="px-2 py-2.5 font-mono text-muted-foreground">{yi(c.amount)}</td>
                          <td className="px-2 py-2.5 text-xs text-muted-foreground">
                            {c.pool_history.length} 次 · 成熟 {c.pool_history.filter((h) => h.mature).length}
                          </td>
                          <td className="px-2 py-2.5"><PoolBtn c={c} /></td>
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

      <Disclaimer />
    </div>
  );
}
