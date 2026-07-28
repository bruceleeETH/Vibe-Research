"""资讯雷达缓存与降级行为，全部离线。"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

import app as app_module
import newsradar


client = TestClient(app_module.app)


def _cfg(tmp_path):
    p = tmp_path / "sources.json"
    p.write_text(json.dumps({
        "fetch": {"recent_days": 7, "per_source": 6},
        "redline_keywords": [],
        "industries": [{"key": "ai", "name": "AI", "accent": "#f00"}],
        "sources": [{"hint": "ai", "name": "one", "url": "https://example.test/rss"}],
    }), encoding="utf-8")
    return str(p)


def test_concurrent_refreshes_are_serialized(monkeypatch, tmp_path):
    monkeypatch.setattr(newsradar, "SOURCES_FILE", _cfg(tmp_path))
    monkeypatch.setattr(newsradar, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(newsradar, "CACHE_FILE", str(tmp_path / "radar.json"))
    active = 0
    max_active = 0
    guard = threading.Lock()

    def fake_fetch(*_args):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        with guard:
            active -= 1
        return []

    monkeypatch.setattr(newsradar, "_fetch_source", fake_fetch)
    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(lambda _: newsradar.fetch_radar(), range(2)))

    assert max_active == 1
    assert len(results) == 2
    assert json.loads((tmp_path / "radar.json").read_text(encoding="utf-8"))["industries"][0]["key"] == "ai"


def test_refresh_failure_returns_stale_cache(monkeypatch):
    cached = {
        "generated_at": "2026-07-10 18:27",
        "recent_days": 7,
        "industries": [],
        "stats": {"industries": 12, "total_sources": 108},
    }
    monkeypatch.setattr(newsradar, "fetch_radar", lambda: (_ for _ in ()).throw(OSError("temporary failure")))
    monkeypatch.setattr(newsradar, "load_cache", lambda: cached)

    response = client.post("/api/radar/refresh")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["stale"] is True
    assert data["generated_at"] == "2026-07-10 18:27"
    assert "temporary failure" in data["refresh_error"]
