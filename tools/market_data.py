#!/usr/bin/env python3
"""主板历史行情库管理命令：初始化、状态、样本验证与增量回填。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import market_universe
import screener
from market_ingest import BaoStockSource
from market_store import MarketStore


TZ = ZoneInfo("Asia/Shanghai")


def months_before(day: date, months: int) -> date:
    """按自然月回退并把日期限制到目标月份的有效日。"""
    total = day.year * 12 + day.month - 1 - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    last_day = (next_month - timedelta(days=1)).day
    return date(year, month, min(day.day, last_day))


def stratified_sample(items: list[dict], size: int) -> list[dict]:
    """按交易所和市值分位抽样，避免样本只集中在代码或市值头部。"""
    if size <= 0 or size >= len(items):
        return list(items)
    groups = {
        "SH": sorted((item for item in items if item["exchange"] == "SH"), key=lambda item: item["total_mcap_cny"]),
        "SZ": sorted((item for item in items if item["exchange"] == "SZ"), key=lambda item: item["total_mcap_cny"]),
    }
    selected = []
    quotas = {"SH": size // 2, "SZ": size - size // 2}
    for exchange, group in groups.items():
        quota = min(quotas[exchange], len(group))
        if quota == 1:
            selected.append(group[len(group) // 2])
        elif quota > 1:
            indices = {round(index * (len(group) - 1) / (quota - 1)) for index in range(quota)}
            selected.extend(group[index] for index in sorted(indices))
    if len(selected) < size:
        seen = {item["symbol"] for item in selected}
        selected.extend(item for item in items if item["symbol"] not in seen)
    return sorted(selected[:size], key=lambda item: item["code"])


def date_window(source: BaoStockSource, as_of: date, months: int, warmup_days: int) -> dict:
    """计算分析窗口和额外交易日预热窗口。"""
    analysis_start = months_before(as_of, months)
    calendar_start = analysis_start - timedelta(days=max(60, warmup_days * 3))
    dates = source.trade_dates(calendar_start.isoformat(), as_of.isoformat())
    earlier = [date.fromisoformat(value) for value in dates if value < analysis_start.isoformat()]
    warmup = earlier[-warmup_days:] if warmup_days else []
    start = warmup[0] if warmup else analysis_start
    active = [value for value in dates if analysis_start.isoformat() <= value <= as_of.isoformat()]
    if not active:
        raise RuntimeError("分析窗口内没有交易日")
    return {
        "fetch_start": start.isoformat(),
        "analysis_start": analysis_start.isoformat(),
        "end": active[-1],
        "warmup_days": len(warmup),
        "analysis_trade_days": len(active),
        "expected_trade_days": len(warmup) + len(active),
    }


def instruments_for(items: list[dict]) -> list[dict]:
    """去掉股票池筛选时的临时市值字段，生成存储契约。"""
    keys = ("symbol", "code", "exchange", "board", "name_current", "list_date", "delist_date")
    return [{key: item.get(key) for key in keys} for item in items]


def run_backfill(args) -> dict:
    """构造当前快照股票池并分批写入历史行情库。"""
    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(TZ).date()
    rows = screener.market_snapshot("A", force=True)
    if not rows:
        raise RuntimeError("东财全市场快照为空，未开始回填")
    universe = market_universe.build_current_universe(rows, as_of.isoformat(), args.min_mcap)
    selected = universe["eligible"] if args.all else stratified_sample(universe["eligible"], args.sample)
    selected_symbols = {item["symbol"] for item in selected}
    selected_universe = [
        row for row in universe["universe_rows"]
        if row["symbol"] in selected_symbols
    ]
    store = MarketStore(args.data_root)
    store.initialize()
    committed = []
    errors = []

    with BaoStockSource() as source:
        window = date_window(source, as_of, args.months, args.warmup_days)
        covered = store.covered_symbols(
            [item["symbol"] for item in selected],
            window["end"],
        )
        pending = [item for item in selected if item["symbol"] not in covered]
        if covered:
            print(f"[resume] 已覆盖到 {window['end']}：{len(covered)} 只，跳过重复采集", flush=True)
        for offset in range(0, len(pending), args.batch_size):
            batch = pending[offset:offset + args.batch_size]
            bars = []
            factors = []
            batch_errors = []
            for index, item in enumerate(batch, offset + 1):
                try:
                    result = source.fetch_symbol(
                        item["symbol"], window["fetch_start"], window["end"]
                    )
                    if not result["bars"]:
                        raise RuntimeError("没有有效日线")
                    bars.extend(result["bars"])
                    factors.extend(result["factors"])
                    if result["skipped"]:
                        batch_errors.append({
                            "symbol": item["symbol"],
                            "reason": "部分日期无效",
                            "details": result["skipped"],
                        })
                    print(
                        f"[{index}/{len(pending)}] {item['code']} {item['name_current']} "
                        f"{len(result['bars'])} rows",
                        flush=True,
                    )
                except Exception as exc:
                    error = {"symbol": item["symbol"], "reason": f"{type(exc).__name__}: {exc}"}
                    batch_errors.append(error)
                    print(f"[{index}/{len(pending)}] {item['code']} FAILED {exc}", flush=True)
            successful = {row["symbol"] for row in bars}
            batch_instruments = [item for item in batch if item["symbol"] in successful]
            if bars:
                result = store.commit_ingest(
                    source="baostock-0.9.3",
                    as_of=as_of.isoformat(),
                    scope="mainboard-current-mcap30b-" + ("all" if args.all else f"sample{len(selected)}"),
                    instruments=instruments_for(batch_instruments),
                    universe_rows=[
                        row for row in selected_universe
                        if row["symbol"] in successful
                    ],
                    bars=bars,
                    factors=factors,
                    summary={
                        "universe_mode": universe["universe_mode"],
                        "market_cap_asof": universe["market_cap_asof"],
                        "min_mcap_cny": universe["min_mcap_cny"],
                        "universe_counts": universe["counts"],
                        "window": window,
                        "batch_errors": batch_errors,
                    },
                )
                committed.append(result)
            errors.extend(batch_errors)

    return {
        "mode": "all" if args.all else f"sample{len(selected)}",
        "selected": len(selected),
        "already_covered": len(covered),
        "attempted": len(pending),
        "universe": universe["counts"],
        "window": window,
        "commits": committed,
        "errors": errors,
        "store": store.status(),
    }


def parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--data-root", help="覆盖 market-data 目录；默认 VR_DATA_DIR/market-data")
    sub = command.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    backfill = sub.add_parser("backfill")
    mode = backfill.add_mutually_exclusive_group()
    mode.add_argument("--sample", type=int, default=50, help="按交易所和市值分位抽样，默认 50")
    mode.add_argument("--all", action="store_true", help="回填全部符合条件证券")
    backfill.add_argument("--as-of", help="当前股票池与截止日 YYYY-MM-DD")
    backfill.add_argument("--months", type=int, default=3)
    backfill.add_argument("--warmup-days", type=int, default=30)
    backfill.add_argument("--min-mcap", type=float, default=3_000_000_000)
    backfill.add_argument("--batch-size", type=int, default=25)
    return command


def main() -> None:
    """执行数据仓管理命令并输出结构化结果。"""
    args = parser().parse_args()
    store = MarketStore(args.data_root)
    if args.command == "init":
        store.initialize()
        result = store.status()
    elif args.command == "status":
        result = store.status()
    else:
        if args.months <= 0 or args.warmup_days < 20 or args.batch_size <= 0:
            raise SystemExit("months 必须为正数，warmup-days 至少 20，batch-size 必须为正数")
        result = run_backfill(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
