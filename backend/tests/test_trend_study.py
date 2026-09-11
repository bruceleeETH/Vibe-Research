from datetime import date, timedelta

import pytest

from market_store import MarketStore
from trend_study import date_snapshot


def seed(store):
    symbols = [("sh.600001", "强势股"), ("sz.000001", "历史ST股")]
    instruments = [{
        "symbol": symbol,
        "code": symbol.split(".")[1],
        "exchange": "SH" if symbol.startswith("sh") else "SZ",
        "board": "main",
        "name_current": name,
        "list_date": None,
        "delist_date": None,
    } for symbol, name in symbols]
    bars = []
    factors = []
    start = date(2026, 8, 1)
    for symbol, _ in symbols:
        for index in range(22):
            day = start + timedelta(days=index)
            close = 10 + index * 0.1
            volume = 2000 if index == 20 else 1000
            bars.append({
                "trade_date": day.isoformat(),
                "symbol": symbol,
                "open_raw": close,
                "high_raw": close * 1.01,
                "low_raw": close * 0.99,
                "close_raw": close,
                "preclose_raw": close - 0.1,
                "volume_shares": volume,
                "amount_cny": close * volume,
                "turnover_pct": 1,
                "trade_status": "1",
                "is_st": symbol == "sz.000001" and index == 20,
            })
            factors.append({
                "trade_date": day.isoformat(),
                "symbol": symbol,
                "qfq_factor": 1,
            })
    universe = [{
        "trade_date": (start + timedelta(days=21)).isoformat(),
        "symbol": symbol,
        "name_asof": name,
        "is_st": False,
        "trade_status": "1",
        "total_mcap_cny": 5e9,
        "eligible": True,
        "exclusion_reason": "",
    } for symbol, name in symbols]
    store.commit_ingest(
        "fixture", (start + timedelta(days=21)).isoformat(), "trend-test",
        instruments, universe, bars, factors,
    )
    return (start + timedelta(days=20)).isoformat(), (start + timedelta(days=21)).isoformat()


def test_date_snapshot_uses_prior_volume_and_excludes_historical_st(tmp_path):
    store = MarketStore(tmp_path)
    store.initialize()
    selected, next_day = seed(store)

    result = date_snapshot(store, selected, volume=1.5, mode="day")

    assert result["observed"] == 2
    assert result["universe_total"] == 2
    assert result["hits"] == 1
    assert result["historical_st_excluded"] == 1
    assert result["next_date"] == next_day
    hit = next(row for row in result["rows"] if row["hit"])
    assert hit["code"] == "600001"
    assert hit["volume_ratio"] == pytest.approx(2)
    assert hit["next_average"] == pytest.approx(12.1)


def test_date_snapshot_supports_hit_filter_and_revision_validation(tmp_path):
    store = MarketStore(tmp_path)
    store.initialize()
    selected, _ = seed(store)

    result = date_snapshot(store, selected, mode="none", only_hits=True, page_size=1)

    assert result["total"] == 1
    assert len(result["rows"]) == 1
    with pytest.raises(ValueError, match="revision"):
        date_snapshot(store, selected, revision=999)
