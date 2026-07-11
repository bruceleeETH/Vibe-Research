// 候选扫描视图：市场/股票池切换、过滤、四视角、权重面板。拆分自 pages/ReviewPool.tsx。
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, ArrowUpDown, ArrowUp, ArrowDown, ChevronDown, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, type ScanResult, type ScanCandidate, type FactorWeights } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  color, pct, yi, fmtNet, factorText, scoreColor, candLine,
  numTd, rowCls, theadCls, scrollWrap,
  TAG_STYLE, FACTOR_NAME, VIEWS, MARKETS_FALLBACK, POOLS_FALLBACK,
  NameCell, StrategyChips, PoolBtn,
  type View, type SortKey, type AiCtx,
} from "./shared";

interface Props {
  onDetail: (c: ScanCandidate) => void;
  inPoolToday: (code: string) => boolean;
  onAddToPool: (c: ScanCandidate) => void;
  onAiCtx: (ctx: AiCtx) => void;
}

export function ScanView({ onDetail, inPoolToday, onAddToPool, onAiCtx }: Props) {
  const [view, setView] = useState<View>("rank");
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [scanLoading, setScanLoading] = useState(false);
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
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [weights, setWeights] = useState<FactorWeights | null>(null);
  const [weightsOpen, setWeightsOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);

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
  useEffect(() => { loadScan(); }, []);

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

  // ---- AskAI 上下文：随视角变化上报给容器 ----
  useEffect(() => {
    const mkt = (scan?.markets || MARKETS_FALLBACK).find((m) => m.key === scan?.market)?.name || "A股";
    const pl = (scan?.pools || POOLS_FALLBACK).find((p) => p.key === scan?.pool)?.name || "全市场";
    const head = `候选扫描（${mkt} · ${pl} · 客观阈值硬筛，${scan?.generated_at}，扫描 ${scan?.scanned} 只）·`;
    let context: string;
    if (view === "industry") {
      context = !groups.length ? "今日候选扫描暂无结果。" :
        `${head} 行业视角：\n` + groups.map((g) =>
          `【${g.name}】${g.rows.length} 只 · 合计成交${yi(g.amountSum)} · 平均涨幅${g.avgPct.toFixed(2)}%${g.netSum != null ? " · 主力合计" + fmtNet(g.netSum) : ""}\n` +
          g.rows.slice(0, 8).map((c) => "  " + candLine(c)).join("\n")).join("\n");
    } else if (view === "review") {
      context = !reviewRows.length ? "今日候选中没有带复盘池历史的标的。" :
        `${head} 复盘视角（候选×历史入池真实表现）：\n` + reviewRows.map((c) =>
          candLine(c) + "\n" + c.pool_history.map((h) =>
            `  ↳ ${h.entry_date} 入池@${h.entry_price} 1D:${pct(h.perf.d1)} 3D:${pct(h.perf.d3)} 5D:${pct(h.perf.d5)} 10D:${pct(h.perf.d10)}${h.mature ? " 成熟" : ""}${h.tag ? " 标签:" + h.tag : ""}`).join("\n")).join("\n");
    } else if (!sorted.length) {
      context = "今日候选扫描暂无结果。";
    } else {
      context = `${head} ${view === "fund" ? "资金视角（按主力净额降序）" : "综合排序（命中策略数→成交额）"}，当前视图 ${sorted.length} 只：\n` +
        sorted.slice(0, 40).map(candLine).join("\n");
    }
    const suggestions =
      view === "industry"
        ? ["哪个板块的候选最值得细看", "候选扎堆的行业和今天板块资金一致吗", "各板块候选的量价有什么差异"]
        : view === "fund"
          ? ["主力净流入靠前的票量价结构怎么样", "资金流入但涨幅不大的有哪些", "这批票的资金面风险在哪"]
          : view === "review"
            ? ["历史样本的表现说明什么", "哪类策略的历史样本走得更好", "再次被筛出意味着什么"]
            : ["按行业帮我分组梳理", "这批票里哪些量价结构值得细看", "各自的主要风险是什么"];
    onAiCtx({ context, suggestions, label: "让 AI 读候选" });
  }, [view, sorted, groups, reviewRows, scan]);

  // ---- 复用小组件（依赖本视图状态的闭包版本）----
  const SortTh = ({ k, label }: { k: SortKey; label: string }) => (
    <th className="whitespace-nowrap px-2 py-2 text-right font-medium">
      <button onClick={() => clickSort(k)} className="inline-flex items-center gap-0.5 hover:text-primary" title="点击排序">
        {label}
        {sortKey === k ? (sortAsc ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />) : <ArrowUpDown className="h-3 w-3 opacity-40" />}
      </button>
    </th>
  );
  const Btn = ({ c }: { c: ScanCandidate }) => <PoolBtn c={c} inPool={inPoolToday(c.code)} onAdd={onAddToPool} />;
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
  // 综合排序 / 行业视角共用的明细行
  const DetailRow = ({ c, showIndustry = true }: { c: ScanCandidate; showIndustry?: boolean }) => (
    <tr className={rowCls} onClick={() => onDetail(c)} title="点击查看详情">
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
      <td className="px-2 py-2.5" onClick={(e) => e.stopPropagation()}><Btn c={c} /></td>
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
    <GlassCard glow>
      {err && <p className="mb-2 text-sm text-destructive">{err}</p>}

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
        <div className="ml-auto flex items-center gap-3">
          {scan?.stale && <span className="text-xs text-amber-500">数据更新中，先展示上次结果…</span>}
          {scan && <span className="text-xs text-muted-foreground">扫描 {scan.generated_at} · 全市场 {scan.scanned} 只</span>}
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索代码 / 名称"
            className="w-44 rounded-lg border border-border bg-black/20 px-2.5 py-1.5 text-sm outline-none focus:border-primary/50"
          />
        </div>
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
                  <tr key={c.code} className={rowCls} onClick={() => onDetail(c)} title="点击查看详情">
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
                    <td className="px-2 py-2.5" onClick={(e) => e.stopPropagation()}><Btn c={c} /></td>
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
                    <tr className={rowCls} onClick={() => onDetail(c)} title="点击查看详情">
                      <NameCell c={c} />
                      <td className="max-w-32 truncate px-2 py-2.5 text-xs text-muted-foreground">{c.industry || "—"}</td>
                      <td className="px-2 py-2.5"><StrategyChips c={c} /></td>
                      <td className={cn("px-2 py-2.5 font-mono", color(c.pct))}>{pct(c.pct)}</td>
                      <td className="px-2 py-2.5 font-mono text-muted-foreground">{yi(c.amount)}</td>
                      <td className="px-2 py-2.5 text-xs text-muted-foreground">
                        {c.pool_history.length} 次 · 成熟 {c.pool_history.filter((h) => h.mature).length}
                      </td>
                      <td className="px-2 py-2.5" onClick={(e) => e.stopPropagation()}><Btn c={c} /></td>
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
  );
}
