"""复盘工作台单测：策略硬筛纯逻辑 + 收益计算纯函数 + 复盘池 CRUD + API 契约。全离线。"""
import pytest
from fastapi.testclient import TestClient

import app as app_module
import reviewpool as rp
import screener

client = TestClient(app_module.app)


# ---------------------------------------------------------------------------
# 策略硬筛（纯函数）
# ---------------------------------------------------------------------------

def _row(**kw):
    base = {"code": "000000", "name": "样本", "price": 10.0, "pct": 0.0, "vol_ratio": 1.0,
            "turnover": 1.0, "amount": 1e8, "pe_ttm": 20.0, "pe_dyn": 20.0, "pb": 2.0,
            "mcap": 1e10, "industry": ""}
    base.update(kw)
    return base


def test_match_volume_surge():
    assert "volume_surge" in screener.match_strategies(
        _row(pct=5, vol_ratio=1.5, turnover=4, amount=3e8))
    # 边界外：涨幅 9.5 超出 3-9 区间
    assert "volume_surge" not in screener.match_strategies(
        _row(pct=9.5, vol_ratio=1.5, turnover=4, amount=3e8))
    # 成交额不足 2 亿
    assert "volume_surge" not in screener.match_strategies(
        _row(pct=5, vol_ratio=1.5, turnover=4, amount=1.9e8))


def test_match_high_turnover():
    assert "high_turnover" in screener.match_strategies(
        _row(vol_ratio=2, turnover=5, amount=3e8))
    assert "high_turnover" not in screener.match_strategies(
        _row(vol_ratio=1.9, turnover=5, amount=3e8))


def test_match_value_breakout():
    assert "value_breakout" in screener.match_strategies(
        _row(pct=3, pe_ttm=30, turnover=2.5))
    # 负 PE / 超 50 不命中
    assert "value_breakout" not in screener.match_strategies(_row(pct=3, pe_ttm=-5, turnover=2.5))
    assert "value_breakout" not in screener.match_strategies(_row(pct=3, pe_ttm=51, turnover=2.5))


def test_match_none_fields_safe():
    # 停牌等场景字段为 None（东财 '-' 归一）→ 不命中且不抛异常
    assert screener.match_strategies(
        {"pct": None, "vol_ratio": None, "turnover": None, "amount": None, "pe_ttm": None}) == []


def test_objective_flags():
    assert "涨停附近" in screener.objective_flags(_row(pct=9.9))
    assert "换手过热" in screener.objective_flags(_row(turnover=25))
    assert "成交额不足" in screener.objective_flags(_row(amount=1e7))
    assert screener.objective_flags(_row(pct=5, turnover=5, amount=3e8)) == []


@pytest.fixture()
def scan_isolated(monkeypatch, tmp_path):
    """scan 离线隔离：资金兜底与复盘池文件都不出网/不读真实缓存。"""
    monkeypatch.setattr(screener, "fund_snapshot", lambda: {})
    monkeypatch.setattr(rp, "POOL_FILE", str(tmp_path / "reviewpool.json"))
    screener._CACHE.clear()
    return monkeypatch


def test_scan_filters_st_and_sorts(scan_isolated):
    snapshot = [
        _row(code="600001", name="正常股", pct=5, vol_ratio=1.5, turnover=4, amount=3e8, industry="半导体"),
        _row(code="600002", name="ST摆烂", pct=5, vol_ratio=1.5, turnover=4, amount=9e8),
        _row(code="600003", name="大成交", pct=5, vol_ratio=1.5, turnover=4, amount=8e8, industry="AI"),
        _row(code="600004", name="不命中", pct=0.5),
    ]
    scan_isolated.setattr(screener, "market_snapshot", lambda: snapshot)
    out = screener.scan(force=True)
    codes = [c["code"] for c in out["candidates"]]
    assert codes == ["600003", "600001"]          # ST 排除、不命中排除、成交额降序
    assert out["scanned"] == 4
    vs = next(s for s in out["strategies"] if s["key"] == "volume_surge")
    assert vs["count"] == 2
    assert out["candidates"][0]["pool_history"] == []   # 无历史 → 空列表（形状稳定）


def test_scan_fund_fallback_join(scan_isolated):
    """行情快照资金字段全空时，独立资金快照按代码补齐。"""
    snapshot = [_row(code="600001", name="甲", pct=5, vol_ratio=1.5, turnover=4, amount=3e8)]
    scan_isolated.setattr(screener, "market_snapshot", lambda: snapshot)
    scan_isolated.setattr(screener, "fund_snapshot",
                          lambda: {"600001": {"main_net": 2.5e8, "super_net": 1e8, "main_pct": 6.1}})
    c = screener.scan(force=True)["candidates"][0]
    assert c["main_net"] == 2.5e8 and c["main_pct"] == 6.1


def test_scan_attaches_pool_history(scan_isolated, tmp_path):
    """候选曾入池 → pool_history 带历次真实表现（新→旧）。"""
    snapshot = [_row(code="600001", name="甲", pct=5, vol_ratio=1.5, turnover=4, amount=3e8)]
    scan_isolated.setattr(screener, "market_snapshot", lambda: snapshot)
    import json, os
    os.makedirs(tmp_path, exist_ok=True)
    entries = [
        {"id": "a", "code": "600001", "name": "甲", "entry_date": "2026-07-01", "entry_price": 10.0,
         "strategies": [], "tag": "观察", "note": "", "added": "2026-07-01 15:00",
         "perf": {"d1": 1.0, "d3": 2.0, "d5": 3.0, "d10": 4.0}, "mature": True, "perf_asof": "2026-07-09"},
        {"id": "b", "code": "600001", "name": "甲", "entry_date": "2026-07-08", "entry_price": 12.0,
         "strategies": [], "tag": "", "note": "", "added": "2026-07-08 15:00",
         "perf": {"d1": -1.5, "d3": None, "d5": None, "d10": None}, "mature": False, "perf_asof": "2026-07-10"},
    ]
    with open(rp.POOL_FILE, "w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f, ensure_ascii=False)
    c = screener.scan(force=True)["candidates"][0]
    assert len(c["pool_history"]) == 2
    assert c["pool_history"][0]["entry_date"] == "2026-07-08"    # 新→旧
    assert c["pool_history"][1]["mature"] and c["pool_history"][1]["perf"]["d10"] == 4.0


def test_snapshot_paging_fallback(monkeypatch):
    """单次大页被服务端钳制/断连时，自动按成交额降序分页补齐 + 跨页去重。"""
    total = 250
    universe = [{"f12": f"{600000 + i}", "f14": f"股{i}", "f6": 1e8 * (total - i)} for i in range(total)]

    def fake_page(host, pn, pz, fid="f6", fields=""):
        if host != "push2delay.eastmoney.com":
            raise ConnectionError("host down")     # 前两个主机全挂
        pz = min(pz, 100)                          # 服务端钳页长到 100
        return universe[(pn - 1) * pz: pn * pz], total

    monkeypatch.setattr(screener, "_clist_page", fake_page)
    rows = screener.market_snapshot()
    assert len(rows) == total                      # 3 页补齐、无重复
    assert rows[0]["code"] == "600000"


# ---------------------------------------------------------------------------
# 收益计算（纯函数）
# ---------------------------------------------------------------------------

def test_calc_perf():
    p = rp.calc_perf(10.0, [10.5, 11.0, 9.0, 12.0, 13.0])
    assert p["d1"] == 5.0
    assert p["d3"] == -10.0
    assert p["d5"] == 30.0
    assert p["d10"] is None                        # 不足 10 日 → 待
    assert rp.calc_perf(10.0, []) == {"d1": None, "d3": None, "d5": None, "d10": None}
    assert rp.calc_perf(0.0, [10.0])["d1"] is None  # 入池价异常不除零


def test_calc_perf_mature():
    closes = [10.0 + i for i in range(10)]
    assert rp.calc_perf(10.0, closes)["d10"] == 90.0


# ---------------------------------------------------------------------------
# 复盘池 CRUD（tmp 存储 + 打桩行情）
# ---------------------------------------------------------------------------

@pytest.fixture()
def pool(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "POOL_FILE", str(tmp_path / "reviewpool.json"))
    monkeypatch.setattr(rp, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(rp.astock, "tencent_quote",
                        lambda codes: {c: {"name": f"股{c}", "price": 10.0, "change_pct": 1.0} for c in codes})
    monkeypatch.setattr(rp, "_closes_after", lambda code, entry_date: [10.5, 11.0])
    return rp


def test_pool_add_tag_remove(pool):
    assert pool.add_batch([{"code": "600519", "strategies": ["volume_surge"]}])["added"] == 1
    # 同代码同日去重
    assert pool.add_batch([{"code": "600519"}])["added"] == 0

    d = pool.get_pool()
    assert d["total"] == 1
    e = d["entries"][0]
    assert e["entry_price"] == 10.0
    assert e["perf"]["d1"] == 5.0 and e["perf"]["d3"] is None
    assert e["status"] == "待成熟" and e["tag"] == ""

    assert pool.update_tag(e["id"], "重点关注", "缩量回踩")
    assert pool.get_pool()["entries"][0]["tag"] == "重点关注"
    assert not pool.update_tag("nonexistent", "观察", "")

    assert pool.remove(e["id"])
    assert pool.get_pool()["total"] == 0


def test_pool_mature_locks(pool, monkeypatch):
    pool.add_batch([{"code": "000001"}])
    monkeypatch.setattr(pool, "_closes_after", lambda code, entry_date: [10.0 + i * 0.1 for i in range(12)])
    e = pool.get_pool(refresh=True)["entries"][0]
    # 第 10 个收盘 = 10.0 + 9*0.1 = 10.9 → +9.0%
    assert e["mature"] and e["status"] == "成熟" and e["perf"]["d10"] == 9.0

    # 成熟后不再重拉 K 线（打桩成抛异常也不影响）
    def boom(code, entry_date):
        raise AssertionError("成熟样本不应重拉行情")
    monkeypatch.setattr(pool, "_closes_after", boom)
    assert pool.get_pool(refresh=True)["entries"][0]["perf"]["d10"] == 9.0


# ---------------------------------------------------------------------------
# 真实数据源 shape 冒烟（联网，pytest -m live 运行）
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_live_market_snapshot_shape():
    rows = screener.market_snapshot()
    assert len(rows) > 4000                      # 全 A ~5000+，一次请求拿全
    r = rows[0]
    assert {"code", "name", "pct", "amount", "turnover", "vol_ratio", "pe_ttm", "industry",
            "main_net", "super_net", "main_pct"} <= set(r)
    # 资金字段联通性：成交额头部 100 只里应有相当比例非空（上游偶发置空则走 fund_snapshot 兜底）
    top = rows[:100]
    hit = sum(1 for x in top if x["main_net"] is not None)
    if hit < 50:
        fund = screener.fund_snapshot()
        assert len(fund) > 3000 and any(v["main_net"] is not None for v in fund.values())


@pytest.mark.live
def test_live_tencent_daily_kline_shape():
    import astock
    bars = astock.tencent_daily_kline("600519", count=15)
    assert len(bars) >= 10
    assert {"date", "close"} <= set(bars[0])
    assert bars[0]["date"] < bars[-1]["date"]    # 升序


# ---------------------------------------------------------------------------
# API 契约（校验层，不联网）
# ---------------------------------------------------------------------------

def test_api_pool_add_bad_code_400():
    assert client.post("/api/review/pool", json={"items": [{"code": "abc"}]}).status_code == 400
    assert client.post("/api/review/pool", json={"items": []}).status_code == 400


def test_api_pool_tag_validation():
    r = client.post("/api/review/pool/tag", json={"id": "x", "tag": "乱写的标签"})
    assert r.status_code == 400
    r = client.post("/api/review/pool/tag", json={"id": "no-such-id", "tag": "观察"})
    assert r.status_code == 404


def test_api_pool_remove_404():
    assert client.delete("/api/review/pool/no-such-id").status_code == 404


def test_api_scan_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(screener, "market_snapshot",
                        lambda: [_row(code="600001", name="甲", pct=5, vol_ratio=1.5, turnover=4, amount=3e8)])
    monkeypatch.setattr(screener, "fund_snapshot", lambda: {})
    monkeypatch.setattr(rp, "POOL_FILE", str(tmp_path / "reviewpool.json"))
    screener._CACHE.clear()
    r = client.get("/api/review/scan?refresh=1")
    assert r.status_code == 200
    d = r.json()["data"]
    assert set(d) == {"generated_at", "scanned", "strategies", "candidates"}
    c = d["candidates"][0]
    assert {"code", "name", "pct", "amount", "turnover", "vol_ratio", "pe_ttm",
            "industry", "strategies", "flags", "main_net", "super_net", "main_pct",
            "pool_history"} <= set(c)
