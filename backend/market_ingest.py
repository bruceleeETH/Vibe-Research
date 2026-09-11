"""Baostock 日线采集适配器：保存原始价格并推导日期级前复权因子。"""
from __future__ import annotations

import math


HISTORY_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "adjustflag,turn,tradestatus,pctChg,isST"
)


class BaoStockError(RuntimeError):
    """Baostock 登录、响应或数据契约不合法。"""


def _number(value, *, required=False):
    if value in (None, ""):
        if required:
            raise BaoStockError("必需数值字段为空")
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BaoStockError(f"数值字段无效：{value!r}") from exc
    if not math.isfinite(result):
        raise BaoStockError("数值字段不是有限值")
    return result


def _rows(result) -> list[dict]:
    if str(getattr(result, "error_code", "")) != "0":
        raise BaoStockError(str(getattr(result, "error_msg", "")) or "Baostock 请求失败")
    fields = list(getattr(result, "fields", []) or [])
    if not fields:
        return []
    rows = []
    while result.next():
        values = result.get_row_data()
        if len(values) != len(fields):
            raise BaoStockError("Baostock 行字段数量不匹配")
        rows.append(dict(zip(fields, values)))
    return rows


class BaoStockSource:
    """管理 Baostock 会话并提供可验证的原始/前复权日线。"""

    def __init__(self, module=None):
        if module is None:
            try:
                import baostock as module
            except ImportError as exc:
                raise BaoStockError("缺少 baostock，请安装 backend/requirements.txt") from exc
        self.module = module
        self.logged_in = False

    def __enter__(self):
        result = self.module.login()
        if str(getattr(result, "error_code", "")) != "0":
            raise BaoStockError(str(getattr(result, "error_msg", "")) or "Baostock 登录失败")
        self.logged_in = True
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.logged_in:
            self.module.logout()
            self.logged_in = False

    def _history(self, symbol: str, start: str, end: str, adjustflag: str) -> list[dict]:
        result = self.module.query_history_k_data_plus(
            symbol,
            HISTORY_FIELDS,
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag=adjustflag,
        )
        return _rows(result)

    def fetch_symbol(self, symbol: str, start: str, end: str) -> dict:
        """抓取单票不复权/前复权日线，返回规范化 bars 与 qfq factors。"""
        raw_rows = self._history(symbol, start, end, "3")
        qfq_rows = self._history(symbol, start, end, "2")
        raw_by_date = {row["date"]: row for row in raw_rows}
        qfq_by_date = {row["date"]: row for row in qfq_rows}
        if len(raw_by_date) != len(raw_rows) or len(qfq_by_date) != len(qfq_rows):
            raise BaoStockError(f"{symbol} 存在重复日期")
        if set(raw_by_date) != set(qfq_by_date):
            raise BaoStockError(f"{symbol} 原始与前复权日期不一致")

        bars = []
        factors = []
        skipped = []
        for day in sorted(raw_by_date):
            raw = raw_by_date[day]
            qfq = qfq_by_date[day]
            try:
                close_raw = _number(raw.get("close"), required=True)
                close_qfq = _number(qfq.get("close"), required=True)
                if close_raw <= 0 or close_qfq <= 0:
                    raise BaoStockError("收盘价必须为正数")
                factor = close_qfq / close_raw
                bar = {
                    "trade_date": day,
                    "symbol": symbol,
                    "open_raw": _number(raw.get("open"), required=True),
                    "high_raw": _number(raw.get("high"), required=True),
                    "low_raw": _number(raw.get("low"), required=True),
                    "close_raw": close_raw,
                    "preclose_raw": _number(raw.get("preclose")),
                    "volume_shares": _number(raw.get("volume")),
                    "amount_cny": _number(raw.get("amount")),
                    "turnover_pct": _number(raw.get("turn")),
                    "trade_status": str(raw.get("tradestatus") or ""),
                    "is_st": str(raw.get("isST") or "0") == "1",
                }
                if min(bar["open_raw"], bar["high_raw"], bar["low_raw"]) <= 0:
                    raise BaoStockError("OHLC 必须为正数")
            except BaoStockError as exc:
                skipped.append({"trade_date": day, "reason": str(exc)})
                continue
            bars.append(bar)
            factors.append({
                "trade_date": day,
                "symbol": symbol,
                "qfq_factor": factor,
            })
        return {
            "symbol": symbol,
            "start": start,
            "end": end,
            "bars": bars,
            "factors": factors,
            "skipped": skipped,
        }

    def trade_dates(self, start: str, end: str) -> list[str]:
        """返回给定区间内的交易日。"""
        result = self.module.query_trade_dates(start_date=start, end_date=end)
        return [
            row["calendar_date"]
            for row in _rows(result)
            if str(row.get("is_trading_day")) == "1"
        ]
