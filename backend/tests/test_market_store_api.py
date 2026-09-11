import os

from fastapi.testclient import TestClient

import app
from market_store import MarketStore


client = TestClient(app.app)


def seed():
    root = os.path.join(os.environ["VR_DATA_DIR"], "market-data")
    store = MarketStore(root)
    store.initialize()
    if store.status()["active_revision"]:
        return
    store.commit_ingest(
        "fixture",
        "2026-09-11",
        "api-test",
        [{
            "symbol": "sh.600001", "code": "600001", "exchange": "SH",
            "board": "main", "name_current": "测试股份",
            "list_date": None, "delist_date": None,
        }],
        [{
            "trade_date": "2026-09-11", "symbol": "sh.600001",
            "name_asof": "测试股份", "is_st": False, "trade_status": "1",
            "total_mcap_cny": 5e9, "eligible": True, "exclusion_reason": "",
        }],
        [{
            "trade_date": "2026-09-11", "symbol": "sh.600001",
            "open_raw": 9.8, "high_raw": 10.5, "low_raw": 9.5,
            "close_raw": 10, "preclose_raw": 9.7, "volume_shares": 1000,
            "amount_cny": 10000, "turnover_pct": 1.2,
            "trade_status": "1", "is_st": False,
        }],
        [{
            "trade_date": "2026-09-11", "symbol": "sh.600001",
            "qfq_factor": 1,
        }],
    )


def test_market_store_status_universe_and_bars():
    seed()

    status = client.get("/api/market-store/status")
    universe = client.get("/api/market-store/universe")
    bars = client.get(
        "/api/market-store/bars",
        params={"codes": "600001", "start": "2026-09-11", "end": "2026-09-11"},
    )
    trend = client.get(
        "/api/market-store/trend-snapshot",
        params={"date": "2026-09-11"},
    )

    assert status.status_code == 200
    assert status.json()["bars"] == 1
    assert universe.status_code == 200
    assert universe.json()["rows"][0]["symbol"] == "sh.600001"
    assert bars.status_code == 200
    assert bars.json()["revision"] == 1
    assert bars.json()["rows"][0]["vwap_qfq"] == 10
    assert trend.status_code == 200
    assert trend.json()["observed"] == 1


def test_market_store_api_rejects_bad_codes_and_revision():
    seed()

    assert client.get(
        "/api/market-store/bars",
        params={"codes": "bad", "start": "2026-09-11", "end": "2026-09-11"},
    ).status_code == 400
    assert client.get("/api/market-store/universe", params={"revision": 999}).status_code == 400
    assert client.get(
        "/api/market-store/trend-snapshot",
        params={"date": "2026-09-11", "mode": "bad"},
    ).status_code == 400
