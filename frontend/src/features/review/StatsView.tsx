// 策略表现视图：影子vs手动 / 分策略 / 分数段统计 + 存档回看 + 数据与存储。
import { useEffect, useState } from "react";
import { BarChart3, RefreshCw, Copy, Database } from "lucide-react";
import { toast } from "sonner";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, authHeaders, type ReviewStats, type PerfAgg, type SampleDaySummary, type SampleEntry, type StorageInfo } from "@/lib/api";
import { cn } from "@/lib/utils";
import { color, pct, yi, scoreColor, aggLine, numTd, theadCls, STRATEGY_NAME, type AiCtx } from "./shared";

const fmtBytes = (n: number) =>
  n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${(n / 1e3).toFixed(0)} KB` : `${n} B`;

interface Props {
  onAiCtx: (ctx: AiCtx) => void;
}

export function StatsView({ onAiCtx }: Props) {
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [sampleDays, setSampleDays] = useState<SampleDaySummary[]>([]);
  const [sampleDay, setSampleDay] = useState<string | null>(null);
  const [sampleEntries, setSampleEntries] = useState<SampleEntry[]>([]);
  const [storage, setStorage] = useState<StorageInfo | null>(null);

  const loadStats = () => {
    setLoading(true);
    api.reviewStats().then(setStats).catch((e) => toast.error(e.message)).finally(() => setLoading(false));
    api.reviewSampleDays().then(setSampleDays).catch(() => {});
    api.reviewStorage().then(setStorage).catch(() => {});
  };
  useEffect(loadStats, []);

  const openSampleDay = (d: string) => {
    if (sampleDay === d) { setSampleDay(null); return; }
    setSampleDay(d);
    api.reviewSampleDay(d).then(setSampleEntries).catch((e) => toast.error(e.message));
  };

  // AskAI 上下文上报
  useEffect(() => {
    const context = !stats ? "统计尚未加载。" : [
      `策略表现统计（${stats.updated}，覆盖 ${stats.days} 个交易日，基准 ${stats.bench_name}）。${stats.note}`,
      aggLine("影子样本(无选择偏差)", stats.shadow),
      aggLine(`手动入池(${stats.manual_n}条)`, stats.manual),
      ...Object.values(stats.by_strategy).map((s) => aggLine(`策略·${s.name}`, s)),
      ...stats.by_score.map((b) => aggLine(`综合分${b.band}`, b)),
    ].join("\n");
    onAiCtx({
      context,
      label: "让 AI 解读统计",
      suggestions: ["哪个策略的风险收益比最好", "手动挑选比影子样本强吗", "高分段是否显著跑赢低分段", "根据统计建议怎么调因子权重"],
    });
  }, [stats]);

  const backup = async () => {
    try {
      const resp = await fetch("/api/review/storage/backup", { headers: authHeaders() });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = resp.headers.get("Content-Disposition")?.match(/filename="(.+)"/)?.[1] || "backup.zip";
      a.click();
      URL.revokeObjectURL(a.href);
      toast.success("备份已下载");
    } catch (e) {
      toast.error(`备份失败：${(e as Error).message}`);
    }
  };

  const clearCaches = async () => {
    if (!window.confirm("清理可再生缓存（扫描/资讯雷达）？资产数据不受影响，下次访问自动重建。")) return;
    try {
      const r = await api.reviewStorageClear();
      toast.success(`已清理 ${r.removed.join("、") || "0 项"}，释放 ${fmtBytes(r.freed)}`);
      api.reviewStorage().then(setStorage).catch(() => {});
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
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
          <button onClick={loadStats} disabled={loading} className="text-muted-foreground hover:text-primary" title="刷新">
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
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

      {/* 数据与存储：大小 / 位置一目了然，资产可备份、缓存可清理 */}
      {storage && (
        <div className="mt-6 border-t border-border/40 pt-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h4 className="flex items-center gap-1.5 text-sm font-semibold">
              <Database className="h-4 w-4 text-primary" /> 数据与存储
              <span className="text-xs font-normal text-muted-foreground">
                共 {fmtBytes(storage.total_size)}（资产 {fmtBytes(storage.asset_size)}）·
                <button
                  onClick={() => { navigator.clipboard.writeText(storage.dir); toast.success("目录已复制"); }}
                  className="ml-1 inline-flex items-center gap-0.5 font-mono hover:text-primary"
                  title={storage.dir}
                >
                  {storage.dir.length > 48 ? "…" + storage.dir.slice(-48) : storage.dir}
                  <Copy className="h-3 w-3" />
                </button>
              </span>
            </h4>
            <div className="flex items-center gap-2">
              <button onClick={backup} className="rounded-lg bg-primary/10 px-2.5 py-1 text-xs text-primary hover:bg-primary/20"
                title="打包全部资产类数据为 zip 下载">
                备份资产
              </button>
              <button onClick={clearCaches} className="rounded-lg bg-muted/40 px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
                title="删除可再生缓存，下次访问自动重建">
                清理缓存
              </button>
            </div>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                {["类型", "名称", "说明", "大小", "文件数", "最后更新", "路径"].map((h) => (
                  <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {storage.items.filter((i) => i.exists || i.kind === "asset").map((i) => (
                <tr key={i.key} className="border-b border-border/30 even:bg-white/[0.02]">
                  <td className="px-2 py-2">
                    <span className={cn("rounded px-1.5 py-0.5 text-[11px]",
                      i.kind === "asset" ? "bg-primary/15 text-primary" : i.kind === "cache" ? "bg-muted/50 text-muted-foreground" : "bg-muted/30 text-muted-foreground/60")}>
                      {i.kind === "asset" ? "资产" : i.kind === "cache" ? "缓存" : "其他"}
                    </span>
                  </td>
                  <td className="px-2 py-2 font-medium">{i.name}</td>
                  <td className="px-2 py-2 text-xs text-muted-foreground">{i.desc}</td>
                  <td className="px-2 py-2 text-right font-mono text-xs">{i.exists ? fmtBytes(i.size) : "—"}</td>
                  <td className="px-2 py-2 text-right font-mono text-xs text-muted-foreground">{i.exists ? i.files : "—"}</td>
                  <td className="px-2 py-2 font-mono text-xs text-muted-foreground">{i.mtime ?? "未创建"}</td>
                  <td className="px-2 py-2">
                    <button
                      onClick={() => { navigator.clipboard.writeText(i.path); toast.success("路径已复制"); }}
                      className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground/70 hover:text-primary"
                      title={i.path}
                    >
                      …/{i.key} <Copy className="h-3 w-3" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-muted-foreground/70">
            「资产」是唯一不可再生的数据（复盘池 / 影子样本 / 权重 / 持仓 / 研报），建议定期点「备份资产」或把上面的目录纳入 Time Machine；「缓存」可随时清理，自动重建。
          </p>
        </div>
      )}
    </GlassCard>
  );
}
