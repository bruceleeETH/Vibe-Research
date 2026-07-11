// 右侧详情栏：因子拆解条形图 / 迷你K线 / 关键数据 / 入池历史 / 近期公告 / 问 AI。
import { useEffect, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { api, type ScanCandidate, type Bar, type Announcement } from "@/lib/api";
import { cn } from "@/lib/utils";
import { color, pct, yi, fmtNet, scoreColor, candLine, FACTOR_NAME, TAG_STYLE, StrategyChips, PoolBtn } from "./shared";
import { MiniKline } from "./MiniKline";

interface Props {
  detail: ScanCandidate;
  onClose: () => void;
  inPoolToday: (code: string) => boolean;
  onAddToPool: (c: ScanCandidate) => void;
}

export function DetailDrawer({ detail, onClose, inPoolToday, onAddToPool }: Props) {
  const [bars, setBars] = useState<Bar[]>([]);
  const [anns, setAnns] = useState<Announcement[]>([]);

  // 打开/切换标的时拉迷你K线 + 近期公告（A股）
  useEffect(() => {
    setBars([]);
    setAnns([]);
    api.reviewKline(detail.code, detail.secid, detail.market || "A", 90).then(setBars).catch(() => {});
    if ((detail.market || "A") === "A") {
      api.announcements(detail.code).then((a) => setAnns(a.slice(0, 5))).catch(() => {});
    }
  }, [detail.code]);

  return (
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
          <div onClick={(e) => e.stopPropagation()}>
            <PoolBtn c={detail} inPool={inPoolToday(detail.code)} onAdd={onAddToPool} />
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground" title="关闭">
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
        <MiniKline bars={bars} />
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
        ] as [string, ReactNode][]).map(([label, val]) => (
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
      {anns.length > 0 && (
        <div className="rounded-lg border border-border/40 p-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">近期公告</p>
          <div className="space-y-1.5 text-xs">
            {anns.map((a) => (
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
  );
}
