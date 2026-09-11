"""沪深主板股票池定义；当前快照只用于首期管线验证。"""
from __future__ import annotations

from datetime import date


SH_MAIN_PREFIXES = ("600", "601", "603", "605")
SZ_MAIN_PREFIXES = ("000", "001", "002", "003")


def is_mainboard_code(code: str) -> bool:
    """判断六位证券代码是否属于沪深主板股票代码段。"""
    return (
        isinstance(code, str)
        and len(code) == 6
        and code.isdigit()
        and code.startswith(SH_MAIN_PREFIXES + SZ_MAIN_PREFIXES)
    )


def symbol_for(code: str) -> str:
    """将六位代码转成 Baostock 的交易所前缀格式。"""
    if not is_mainboard_code(code):
        raise ValueError(f"不是沪深主板代码：{code}")
    return ("sh." if code.startswith("6") else "sz.") + code


def build_current_universe(rows: list[dict], as_of: str, min_mcap: float = 3_000_000_000) -> dict:
    """从东财当前快照构造首期固定池，并保留全部排除原因。"""
    day = date.fromisoformat(as_of).isoformat()
    if min_mcap <= 0:
        raise ValueError("总市值门槛必须为正数")
    universe_rows = []
    eligible = []
    counts = {
        "snapshot": len(rows),
        "mainboard": 0,
        "eligible": 0,
        "st_or_retiring": 0,
        "below_mcap": 0,
        "missing_mcap": 0,
    }
    seen = set()
    for row in rows:
        code = str(row.get("code") or "")
        if not is_mainboard_code(code) or code in seen:
            continue
        seen.add(code)
        counts["mainboard"] += 1
        name = str(row.get("name") or "").strip()
        upper = name.upper()
        mcap = row.get("mcap")
        try:
            mcap = float(mcap) if mcap is not None else None
        except (TypeError, ValueError):
            mcap = None

        if "ST" in upper or "退" in name:
            reason = "st_or_retiring"
        elif mcap is None or mcap <= 0:
            reason = "missing_mcap"
        elif mcap < min_mcap:
            reason = "below_mcap"
        else:
            reason = ""
        if reason:
            counts[reason] += 1
        else:
            counts["eligible"] += 1

        symbol = symbol_for(code)
        item = {
            "trade_date": day,
            "symbol": symbol,
            "code": code,
            "name_asof": name,
            "is_st": "ST" in upper,
            "trade_status": "1" if row.get("price") not in (None, 0) else "0",
            "total_mcap_cny": mcap,
            "eligible": not reason,
            "exclusion_reason": reason,
        }
        universe_rows.append(item)
        if not reason:
            eligible.append({
                "symbol": symbol,
                "code": code,
                "exchange": "SH" if code.startswith("6") else "SZ",
                "board": "main",
                "name_current": name,
                "list_date": None,
                "delist_date": None,
                "total_mcap_cny": mcap,
            })

    eligible.sort(key=lambda item: item["code"])
    universe_rows.sort(key=lambda item: item["code"])
    return {
        "as_of": day,
        "market_cap_asof": day,
        "min_mcap_cny": min_mcap,
        "universe_mode": "current_snapshot",
        "counts": counts,
        "eligible": eligible,
        "universe_rows": universe_rows,
    }
