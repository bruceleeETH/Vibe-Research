import subprocess
import sys
import time
from pathlib import Path

import pytest

from market_store import MarketStore, StoreValidationError


def sample_batch(close=10.0):
    instruments = [{
        "symbol": "sh.600001",
        "code": "600001",
        "exchange": "SH",
        "board": "main",
        "name_current": "测试股份",
        "list_date": "2000-01-01",
        "delist_date": None,
    }]
    universe = [{
        "trade_date": "2026-09-11",
        "symbol": "sh.600001",
        "name_asof": "测试股份",
        "is_st": False,
        "trade_status": "1",
        "total_mcap_cny": 5_000_000_000,
        "eligible": True,
        "exclusion_reason": "",
    }]
    bars = [{
        "trade_date": "2026-09-11",
        "symbol": "sh.600001",
        "open_raw": 9.8,
        "high_raw": 10.5,
        "low_raw": 9.5,
        "close_raw": close,
        "preclose_raw": 9.7,
        "volume_shares": 1_000,
        "amount_cny": 10_000,
        "turnover_pct": 1.2,
        "trade_status": "1",
        "is_st": False,
    }]
    factors = [{
        "trade_date": "2026-09-11",
        "symbol": "sh.600001",
        "qfq_factor": 1.0,
    }]
    return instruments, universe, bars, factors


def test_initialize_and_commit_revision(tmp_path):
    store = MarketStore(tmp_path)
    store.initialize()
    store.initialize()
    instruments, universe, bars, factors = sample_batch()

    result = store.commit_ingest(
        source="fixture",
        as_of="2026-09-11",
        scope="test",
        instruments=instruments,
        universe_rows=universe,
        bars=bars,
        factors=factors,
    )

    assert result["revision"] == 1
    assert result["bar_rows"] == 1
    status = store.status()
    assert status["active_revision"] == 1
    assert status["bars"] == 1
    assert status["eligible_symbols"] == 1
    assert store.covered_symbols(["sh.600001", "sz.000002"], "2026-09-11") == {"sh.600001"}
    assert store.covered_symbols(["sh.600001"], "2026-09-12") == set()
    assert store.bars(["600001"], "2026-09-11", "2026-09-11")[0]["vwap_qfq"] == pytest.approx(10)


def test_repeated_ingest_updates_without_duplicate_rows(tmp_path):
    store = MarketStore(tmp_path)
    store.initialize()
    batch = sample_batch()
    store.commit_ingest("fixture", "2026-09-11", "test", *batch)
    updated = sample_batch(close=10.1)

    result = store.commit_ingest("fixture", "2026-09-11", "test", *updated)

    assert result["revision"] == 2
    assert store.status()["bars"] == 1
    assert store.bars(["600001"], "2026-09-11", "2026-09-11")[0]["close_raw"] == pytest.approx(10.1)
    assert store.bars(
        ["600001"], "2026-09-11", "2026-09-11", revision=1
    )[0]["close_raw"] == pytest.approx(10.0)


def test_invalid_batch_does_not_advance_active_revision(tmp_path):
    store = MarketStore(tmp_path)
    store.initialize()
    instruments, universe, bars, factors = sample_batch()
    bars[0]["low_raw"] = 10.2

    with pytest.raises(StoreValidationError, match="OHLC"):
        store.commit_ingest(
            "fixture", "2026-09-11", "test",
            instruments, universe, bars, factors,
        )

    status = store.status()
    assert status["active_revision"] == 0
    assert status["bars"] == 0
    assert status["failed_runs"] == 1


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl 共享锁仅适用于 Unix")
def test_reader_waits_for_writer_process_lock(tmp_path):
    store = MarketStore(tmp_path)
    store.initialize()
    script = (
        "from market_store import MarketStore;"
        f"print(MarketStore({str(tmp_path)!r}).status()['active_revision'])"
    )

    with store._writer():
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.2)
        assert process.poll() is None

    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stderr
    assert stdout.strip() == "0"
