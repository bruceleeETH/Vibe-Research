"""基于版本化主板行情库的服务端趋势日期快照。"""
from __future__ import annotations

from datetime import date

from market_store import MarketStore


MODES = {"day", "recent", "none"}


def _resolve_revision(connection, revision: int | None) -> int:
    active = int(connection.execute(
        "SELECT value FROM store_meta WHERE key='active_revision'"
    ).fetchone()[0])
    selected = active if revision is None else int(revision)
    if selected < 1 or selected > active:
        raise ValueError(f"revision 必须在 1..{active} 范围内")
    return selected


def date_snapshot(store: MarketStore, selected_date: str, volume: float = 1.5,
                  mode: str = "day", only_hits: bool = False, page: int = 1,
                  page_size: int = 100, revision: int | None = None) -> dict:
    """计算指定日期的主板趋势特征与下一交易日价格，返回分页结果。"""
    day = date.fromisoformat(selected_date).isoformat()
    if mode not in MODES:
        raise ValueError("mode 必须为 day、recent 或 none")
    if not 1 <= float(volume) <= 10:
        raise ValueError("volume 必须在 1–10")
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 500))

    with store.read_connection() as connection:
        selected_revision = _resolve_revision(connection, revision)
        next_day = connection.execute("""
            SELECT min(trade_date) FROM daily_bars
            WHERE revision<=? AND trade_date>?
        """, [selected_revision, day]).fetchone()[0]
        cursor = connection.execute("""
            WITH bars AS (
                SELECT * FROM daily_bars WHERE revision<=?
                QUALIFY row_number() OVER (
                    PARTITION BY trade_date,symbol ORDER BY revision DESC
                )=1
            ), factors AS (
                SELECT * FROM adjust_factors WHERE revision<=?
                QUALIFY row_number() OVER (
                    PARTITION BY trade_date,symbol ORDER BY revision DESC
                )=1
            ), prices AS (
                SELECT b.trade_date,b.symbol,b.volume_shares,b.amount_cny,
                       b.trade_status,b.is_st,
                       b.open_raw*f.qfq_factor AS open_qfq,
                       b.high_raw*f.qfq_factor AS high_qfq,
                       b.low_raw*f.qfq_factor AS low_qfq,
                       b.close_raw*f.qfq_factor AS close_qfq,
                       CASE WHEN b.volume_shares>0 AND b.amount_cny>=0
                            THEN b.amount_cny/b.volume_shares*f.qfq_factor END AS vwap_qfq
                FROM bars b JOIN factors f USING(trade_date,symbol)
            ), lagged AS (
                SELECT *,
                       lag(close_qfq,1) OVER w AS close_1,
                       lag(close_qfq,5) OVER w AS close_5,
                       lag(close_qfq,10) OVER w AS close_10,
                       lag(close_qfq,20) OVER w AS close_20,
                       avg(volume_shares) OVER (
                           PARTITION BY symbol ORDER BY trade_date
                           ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                       ) AS volume_5,
                       count(*) OVER (
                           PARTITION BY symbol ORDER BY trade_date
                           ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                       ) AS volume_5_count
                FROM prices
                WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
            ), featured AS (
                SELECT *,
                       CASE WHEN close_5>0 THEN (close_qfq/close_5-1)*100 END AS r5,
                       CASE WHEN close_10>0 THEN (close_qfq/close_10-1)*100 END AS r10,
                       CASE WHEN close_20>0 THEN (close_qfq/close_20-1)*100 END AS r20,
                       CASE WHEN volume_5_count=5 AND volume_5>0
                            THEN volume_shares/volume_5 END AS volume_ratio
                FROM lagged
            ), recent AS (
                SELECT *,
                       max(CASE WHEN volume_ratio>=? AND close_qfq>close_1 THEN 1 ELSE 0 END)
                       OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)
                       AS recent_volume_hit
                FROM featured
            ), universe AS (
                SELECT * FROM universe_daily WHERE revision<=?
                QUALIFY row_number() OVER (
                    PARTITION BY trade_date,symbol ORDER BY revision DESC
                )=1
            ), latest_universe AS (
                SELECT * FROM universe
                WHERE trade_date=(SELECT max(trade_date) FROM universe) AND eligible
            )
            SELECT s.symbol,u.name_asof,u.total_mcap_cny,s.trade_date,
                   s.open_qfq,s.high_qfq,s.low_qfq,s.close_qfq,s.vwap_qfq,
                   s.volume_shares,s.r5,s.r10,s.r20,s.volume_ratio,
                   s.trade_status,s.is_st,s.recent_volume_hit,
                   n.trade_date AS next_date,n.open_qfq AS next_open,
                   n.low_qfq AS next_low,n.high_qfq AS next_high,
                   n.vwap_qfq AS next_average,n.close_qfq AS next_close,
                   n.volume_shares AS next_volume
            FROM recent s
            JOIN latest_universe u USING(symbol)
            LEFT JOIN prices n ON n.symbol=s.symbol AND n.trade_date=?
            WHERE s.trade_date=?
            ORDER BY s.symbol
        """, [
            selected_revision, selected_revision, float(volume),
            selected_revision, next_day, day,
        ])
        names = [column[0] for column in cursor.description]
        raw_rows = [dict(zip(names, row)) for row in cursor.fetchall()]
        universe_total = connection.execute("""
            WITH universe AS (
                SELECT * FROM universe_daily WHERE revision<=?
                QUALIFY row_number() OVER (
                    PARTITION BY trade_date,symbol ORDER BY revision DESC
                )=1
            )
            SELECT count(*) FROM universe
            WHERE trade_date=(SELECT max(trade_date) FROM universe) AND eligible
        """, [selected_revision]).fetchone()[0]

    rows = []
    historical_st = 0
    for row in raw_rows:
        if row["is_st"]:
            historical_st += 1
        trend_ok = row["r5"] is not None and row["r10"] is not None and row["r5"] > 0 and row["r10"] > 0
        tradable = row["trade_status"] == "1" and not row["is_st"] and row["volume_shares"] not in (None, 0)
        not_flat = row["high_qfq"] != row["low_qfq"]
        volume_ok = (
            True if mode == "none"
            else row["volume_ratio"] is not None and (
                row["volume_ratio"] >= volume if mode == "day"
                else row["recent_volume_hit"] == 1
            )
        )
        row["code"] = row["symbol"].split(".", 1)[1]
        row["hit"] = bool(trend_ok and tradable and not_flat and volume_ok)
        for key, value in list(row.items()):
            if isinstance(value, date):
                row[key] = value.isoformat()
        rows.append(row)

    rows.sort(key=lambda row: (-int(row["hit"]), -(row["volume_ratio"] or 0), row["code"]))
    hits = sum(row["hit"] for row in rows)
    filtered = [row for row in rows if row["hit"]] if only_hits else rows
    start_index = (page - 1) * page_size
    return {
        "revision": selected_revision,
        "universe_mode": "current_snapshot",
        "date": day,
        "next_date": next_day.isoformat() if next_day else None,
        "volume": volume,
        "mode": mode,
        "universe_total": universe_total,
        "observed": len(rows),
        "historical_st_excluded": historical_st,
        "hits": hits,
        "total": len(filtered),
        "page": page,
        "page_size": page_size,
        "rows": filtered[start_index:start_index + page_size],
    }
