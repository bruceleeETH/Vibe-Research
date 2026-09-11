import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "tools" / "trend_lab_data.py"
SPEC = importlib.util.spec_from_file_location("trend_lab_data", MODULE_PATH)
trend_lab_data = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(trend_lab_data)


def test_historical_average_is_mapped_to_qfq_price_range():
    bars = [{
        "date": "2025-01-02",
        "close": 26.66,
        "low": 25.95,
        "high": 27.66,
        "volume": 100,
    }]
    rows = [{
        "date": "2025-01-02",
        "close": 27.53,
        "low": 26.80,
        "high": 28.57,
        "volume": 1_000,
        "amount": 27_779,
    }]

    coverage = trend_lab_data.merge_historical_averages(bars, rows)

    assert coverage == {
        "added": 1,
        "rejected": 0,
        "covered": 1,
        "total": 1,
        "status": "history_complete",
    }
    assert bars[0]["average_adjustment_factor"] == pytest.approx(26.66 / 27.53)
    assert bars[0]["average"] == pytest.approx(27.779 * 26.66 / 27.53)
    assert bars[0]["low"] <= bars[0]["average"] <= bars[0]["high"]


def test_historical_average_rejects_invalid_or_out_of_range_rows():
    bars = [{
        "date": "2025-01-02",
        "close": 10,
        "low": 9,
        "high": 11,
        "volume": 100,
    }]
    rows = [{
        "date": "2025-01-02",
        "close": 10,
        "low": 9,
        "high": 11,
        "volume": 100,
        "amount": 50_000,
    }]

    coverage = trend_lab_data.merge_historical_averages(bars, rows)

    assert coverage["status"] == "missing"
    assert coverage["rejected"] == 1
    assert "average" not in bars[0]


def test_latest_quote_average_is_not_overwritten_by_history():
    bars = [{
        "date": "2026-09-11",
        "close": 10,
        "low": 9,
        "high": 11,
        "volume": 100,
        "average": 10.25,
        "average_source": "Tencent closing quote amount/volume",
    }]
    rows = [{
        "date": "2026-09-11",
        "close": 10,
        "low": 9,
        "high": 11,
        "volume": 100,
        "amount": 1_000,
    }]

    coverage = trend_lab_data.merge_historical_averages(bars, rows)

    assert coverage["status"] == "history_complete"
    assert coverage["added"] == 0
    assert bars[0]["average"] == 10.25
    assert bars[0]["average_source"] == "Tencent closing quote amount/volume"
