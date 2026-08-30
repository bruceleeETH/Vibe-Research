#!/usr/bin/env python3
"""统一的本地交易记账命令。

示例：
  ./trade buy 603228 --name 景旺电子 --qty 1000 --price 76.46
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from trade_service import TradeError, TradeService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="覆盖本地数据目录（默认 ~/.vibe-research）")
    parser.add_argument("--ledger", help="覆盖私有交易台账路径")
    sub = parser.add_subparsers(dest="command", required=True)

    buy = sub.add_parser("buy", help="记录一笔买入并同步全部本地持仓档案")
    buy.add_argument("code", help="6位证券代码")
    buy.add_argument("--name", help="证券名称；新标的建议填写")
    buy.add_argument("--qty", type=int, required=True, help="买入股数")
    buy.add_argument("--price", required=True, help="成交价")
    buy.add_argument("--date", help="成交日期 YYYY-MM-DD，默认今天")
    buy.add_argument("--reported-at", help="报备或成交时间文本，默认当前时间")
    buy.add_argument("--id", dest="trade_id", help="幂等交易ID；重复执行同一ID不会重复记账")
    buy.add_argument("--dry-run", action="store_true", help="只预览结果，不写入目标档案")

    sell = sub.add_parser("sell", help="记录一笔卖出、毛收益及剩余持仓状态")
    sell.add_argument("code", help="6位证券代码")
    sell.add_argument("--name", help="证券名称")
    sell.add_argument("--qty", type=int, required=True, help="卖出股数")
    sell.add_argument("--price", required=True, help="成交价")
    sell.add_argument("--cost", required=True, help="本次卖出股份的成本价")
    sell.add_argument("--date", help="成交日期 YYYY-MM-DD，默认今天")
    sell.add_argument("--reported-at", help="报备或成交时间文本，默认当前时间")
    sell.add_argument("--id", dest="trade_id", help="幂等交易ID；重复执行同一ID不会重复记账")
    sell.add_argument("--close", action="store_true", help="确认全部清仓，并移入清仓排除项")
    sell.add_argument("--dry-run", action="store_true", help="只预览结果，不写入目标档案")

    args = parser.parse_args()
    service = TradeService(args.root, args.ledger)
    try:
        if args.command == "buy":
            result = service.buy(
                args.code,
                quantity=args.qty,
                price=args.price,
                name=args.name,
                trade_date=args.date,
                reported_at=args.reported_at,
                trade_id=args.trade_id,
                dry_run=args.dry_run,
            )
        elif args.command == "sell":
            result = service.sell(
                args.code,
                quantity=args.qty,
                price=args.price,
                cost=args.cost,
                name=args.name,
                trade_date=args.date,
                reported_at=args.reported_at,
                trade_id=args.trade_id,
                close_position=args.close,
                dry_run=args.dry_run,
            )
        else:  # pragma: no cover - argparse 已限制子命令
            parser.error(f"未知命令：{args.command}")
    except (TradeError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
