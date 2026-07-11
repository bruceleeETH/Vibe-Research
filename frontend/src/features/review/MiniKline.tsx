// 迷你日K（SVG 蜡烛 + MA5/10/20 均线，A股红涨绿跌），零依赖。
// 多取 30 根作均线预热，显示近 60 根——窗口起点的 MA20 也是准的。
import type { Bar } from "@/lib/api";

const MA_DEFS = [
  { n: 5, col: "#f59e0b" },    // MA5 橙
  { n: 10, col: "#3b82f6" },   // MA10 蓝
  { n: 20, col: "#a855f7" },   // MA20 紫
] as const;

export function MiniKline({ bars }: { bars: Bar[] }) {
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
