import importlib.util
from datetime import date
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "tools" / "market_data.py"
SPEC = importlib.util.spec_from_file_location("market_data_cli", MODULE_PATH)
market_data = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(market_data)


def item(code, exchange, mcap):
    return {
        "symbol": ("sh." if exchange == "SH" else "sz.") + code,
        "code": code,
        "exchange": exchange,
        "total_mcap_cny": mcap,
    }


def test_months_before_clamps_end_of_month():
    assert market_data.months_before(date(2026, 5, 31), 3) == date(2026, 2, 28)
    assert market_data.months_before(date(2024, 5, 31), 3) == date(2024, 2, 29)


def test_stratified_sample_covers_both_exchanges_and_cap_ranges():
    rows = [
        *(item(f"6000{i:02d}", "SH", (i + 1) * 1e9) for i in range(20)),
        *(item(f"0000{i:02d}", "SZ", (i + 1) * 1e9) for i in range(20)),
    ]

    selected = market_data.stratified_sample(rows, 10)

    assert len(selected) == 10
    assert sum(row["exchange"] == "SH" for row in selected) == 5
    assert sum(row["exchange"] == "SZ" for row in selected) == 5
    assert min(row["total_mcap_cny"] for row in selected) == 1e9
    assert max(row["total_mcap_cny"] for row in selected) == 20e9


def test_date_window_keeps_three_month_analysis_plus_warmup():
    class Source:
        def trade_dates(self, start, end):
            base = date(2026, 4, 15)
            return [
                date.fromordinal(base.toordinal() + index).isoformat()
                for index in range(150)
                if date.fromordinal(base.toordinal() + index).weekday() < 5
            ]

    window = market_data.date_window(Source(), date(2026, 9, 11), 3, 30)

    assert window["analysis_start"] == "2026-06-11"
    assert window["warmup_days"] == 30
    assert window["fetch_start"] < window["analysis_start"]
    assert window["end"] == "2026-09-11"
