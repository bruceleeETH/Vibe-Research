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
    """scan 离线隔离：资金兜底/行业强度不出网，复盘池与磁盘缓存不碰真实文件。"""
    monkeypatch.setattr(screener, "fund_snapshot", lambda: {})
    monkeypatch.setattr(screener, "industry_strength", lambda: {})
    monkeypatch.setattr(rp, "POOL_FILE", str(tmp_path / "reviewpool.json"))
    monkeypatch.setattr(screener, "_SCAN_CACHE_FILE", str(tmp_path / "scancache.json"))
    monkeypatch.setattr(sp, "recent_hits", lambda days=5, before=None: [])
    screener._CACHE.clear()
    return monkeypatch


def test_scan_filters_st_and_sorts(scan_isolated):
    snapshot = [
        _row(code="600001", name="正常股", pct=5, vol_ratio=1.5, turnover=4, amount=3e8, industry="半导体"),
        _row(code="600002", name="ST摆烂", pct=5, vol_ratio=1.5, turnover=4, amount=9e8),
        _row(code="600003", name="大成交", pct=5, vol_ratio=1.5, turnover=4, amount=8e8, industry="AI"),
        _row(code="600004", name="不命中", pct=0.5),
    ]
    scan_isolated.setattr(screener, "market_snapshot", lambda market="A", force=False: snapshot)
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
    scan_isolated.setattr(screener, "market_snapshot", lambda market="A", force=False: snapshot)
    scan_isolated.setattr(screener, "fund_snapshot",
                          lambda: {"600001": {"main_net": 2.5e8, "super_net": 1e8, "main_pct": 6.1}})
    c = screener.scan(force=True)["candidates"][0]
    assert c["main_net"] == 2.5e8 and c["main_pct"] == 6.1


def test_scan_attaches_pool_history(scan_isolated, tmp_path):
    """候选曾入池 → pool_history 带历次真实表现（新→旧）。"""
    snapshot = [_row(code="600001", name="甲", pct=5, vol_ratio=1.5, turnover=4, amount=3e8)]
    scan_isolated.setattr(screener, "market_snapshot", lambda market="A", force=False: snapshot)
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

    def fake_page(host, pn, pz, fid="f6", fields="", fs=""):
        if host != "push2delay.eastmoney.com":
            raise ConnectionError("host down")     # 前两个主机全挂
        pz = min(pz, 100)                          # 服务端钳页长到 100
        return universe[(pn - 1) * pz: pn * pz], total

    monkeypatch.setattr(screener, "_clist_page", fake_page)
    rows = screener.market_snapshot()
    assert len(rows) == total                      # 3 页补齐、无重复
    assert rows[0]["code"] == "600000"


def test_scan_market_pool_params(scan_isolated):
    snapshot = [
        _row(code="300001", name="创股", pct=5, vol_ratio=1.5, turnover=4, amount=3e8),
        _row(code="600001", name="沪股", pct=5, vol_ratio=1.5, turnover=4, amount=3e8),
    ]
    scan_isolated.setattr(screener, "market_snapshot", lambda market="A", force=False: snapshot)
    out = screener.scan(pool="cyb", force=True)                 # 创业板池 = 30 开头前缀过滤
    assert [c["code"] for c in out["candidates"]] == ["300001"]
    assert out["market"] == "A" and out["pool"] == "cyb"
    assert {m["key"] for m in out["markets"]} == {"A", "HK", "US", "ETF"}
    out2 = screener.scan(market="HK", pool="cyb", force=True)   # 池仅对 A 股生效
    assert out2["pool"] == "all"


def test_in_session_and_ttl():
    from datetime import datetime as _dt
    fri_10 = _dt(2026, 7, 10, 10, 0, tzinfo=screener.BEIJING).timestamp()   # 周五盘中
    fri_16 = _dt(2026, 7, 10, 16, 0, tzinfo=screener.BEIJING).timestamp()   # 周五收盘后
    fri_22 = _dt(2026, 7, 10, 22, 0, tzinfo=screener.BEIJING).timestamp()   # 周五夜（美盘时段）
    sat_11 = _dt(2026, 7, 11, 11, 0, tzinfo=screener.BEIJING).timestamp()   # 周六
    assert screener._in_session("A", fri_10) and not screener._in_session("A", fri_16)
    assert not screener._in_session("A", sat_11)
    assert screener._in_session("US", fri_22) and not screener._in_session("US", fri_10)
    # TTL：盘中 5 分钟；盘中生成的缓存收盘后先按 5 分钟过期（刷收盘定格）；盘后缓存 6 小时
    assert screener._ttl_for("A", fri_10, fri_10 + 60) == screener._TTL
    assert screener._ttl_for("A", fri_10, fri_16) == screener._TTL
    assert screener._ttl_for("A", fri_16, sat_11) == screener._OFF_TTL


def test_scan_stale_while_revalidate(scan_isolated):
    """缓存过期 → 立即返回旧数据（带 stale 标记）并触发一次后台刷新（单飞）。"""
    import time as _time
    key = "scan:A:all"
    old = {"generated_at": "x", "scanned": 1, "market": "A", "pool": "all", "pool_note": "",
           "markets": [], "pools": [], "strategies": [], "candidates": []}
    screener._CACHE[key] = (_time.time() - 8 * 3600, old)     # 8 小时前 → 无论何时都过期
    calls = []
    scan_isolated.setattr(screener, "_bg_refresh", lambda k, m, p: calls.append(k))
    out = screener.scan()
    assert out.get("stale") is True and out["scanned"] == 1
    assert calls == [key]
    # 未过期 → 直接命中，无 stale
    screener._CACHE[key] = (_time.time(), old)
    scan_isolated.setattr(screener, "_in_session", lambda m, ts: True)
    assert "stale" not in screener.scan()


def test_snapshot_cache_reused_across_pools(scan_isolated):
    """切换股票池复用同一份市场快照：网络层只拉一次。"""
    calls = []

    def fake_clist_all(fid="f6", fields="", fs=""):
        calls.append(fs)
        return [{"f12": "300001", "f13": 0, "f14": "创股", "f2": 10.0, "f3": 5.0,
                 "f6": 3e8, "f8": 4.0, "f10": 1.5}]

    scan_isolated.setattr(screener, "_clist_all", fake_clist_all)
    scan_isolated.setattr(screener, "_in_session", lambda m, ts: True)
    screener.scan(pool="all", force=True)      # force → 拉一次
    screener.scan(pool="cyb", force=True)      # force 也重拉（语义：强制新数据）
    n = len(calls)
    out = screener.scan(pool="kcb")            # 非 force：复用快照缓存
    assert len(calls) == n
    assert [c["code"] for c in out["candidates"]] == []  # kcb 池过滤掉 30 开头


def test_open_pct():
    assert screener._open_pct(10.5, 10.0) == 5.0
    assert screener._open_pct(9.5, 10.0) == -5.0
    assert screener._open_pct(None, 10.0) is None
    assert screener._open_pct(0.0, 10.0) is None    # 停牌开盘 0 → None


def test_scan_hit_streak_and_first_hit(scan_isolated):
    snapshot = [
        _row(code="600001", name="连续股", pct=5, vol_ratio=1.5, turnover=4, amount=3e8),
        _row(code="600002", name="首次股", pct=5, vol_ratio=1.5, turnover=4, amount=3e8),
        _row(code="600003", name="断续股", pct=5, vol_ratio=1.5, turnover=4, amount=3e8),
    ]
    scan_isolated.setattr(screener, "market_snapshot", lambda market="A", force=False: snapshot)
    # 存档回看（新→旧）：600001 连续两日；600003 前日有、昨日无（断档）
    scan_isolated.setattr(sp, "recent_hits", lambda days=5, before=None: [
        ("2026-07-10", {"600001": ["volume_surge"]}),
        ("2026-07-09", {"600001": ["volume_surge"], "600003": ["high_turnover"]}),
    ])
    by_code = {c["code"]: c for c in screener.scan(force=True)["candidates"]}
    assert by_code["600001"]["hit_streak"] == 3 and not by_code["600001"]["first_hit"]
    assert by_code["600002"]["hit_streak"] == 1 and by_code["600002"]["first_hit"]
    assert by_code["600003"]["hit_streak"] == 1 and not by_code["600003"]["first_hit"]  # 断档但5日内出现过


def test_scan_adaptive_floor(scan_isolated):
    # 200 只命中放量上涨，成交额 2.1亿~22亿 → 过载触发流动性门槛上调
    snapshot = [_row(code=f"60{i:04d}", name=f"股{i}", pct=5, vol_ratio=1.5, turnover=4,
                     amount=2.1e8 + i * 1e7) for i in range(200)]
    scan_isolated.setattr(screener, "market_snapshot", lambda market="A", force=False: snapshot)
    out = screener.scan(force=True)
    assert len(out["candidates"]) <= screener.MAX_CANDIDATES
    assert "流动性门槛" in out["adaptive_note"]
    # 留下的都是成交额头部
    assert min((c["amount"] for c in out["candidates"])) >= 3e8


def test_set_weights_normalize_and_invalidate(scan_isolated, tmp_path):
    scan_isolated.setattr(screener, "_WEIGHTS_FILE", str(tmp_path / "w.json"))
    old = dict(screener.FACTOR_WEIGHTS)
    try:
        screener._CACHE["scan:A:all"] = (9e9, {"x": 1})
        w = screener.set_weights({"trend": 50, "volume": 30, "fund": 10, "valuation": 5, "industry": 5})
        assert abs(sum(w.values()) - 1.0) < 1e-6 and w["trend"] == 0.5
        assert "scan:A:all" not in screener._CACHE       # 扫描缓存作废
        with pytest.raises(ValueError):
            screener.set_weights({"trend": -1, "volume": 0, "fund": 0, "valuation": 0, "industry": 0})
    finally:
        screener.FACTOR_WEIGHTS.update(old)


def test_api_weights_and_kline(monkeypatch, tmp_path):
    monkeypatch.setattr(screener, "_WEIGHTS_FILE", str(tmp_path / "w.json"))
    old = dict(screener.FACTOR_WEIGHTS)
    try:
        r = client.get("/api/review/weights")
        assert r.status_code == 200 and set(r.json()["data"]) == set(screener.FACTOR_WEIGHTS)
        r = client.post("/api/review/weights", json={"trend": 40, "volume": 30, "fund": 10, "valuation": 10, "industry": 10})
        assert r.status_code == 200 and r.json()["data"]["trend"] == 0.4
        r = client.post("/api/review/weights", json={"trend": -5, "volume": 0, "fund": 0, "valuation": 0, "industry": 0})
        assert r.status_code == 400
    finally:
        screener.FACTOR_WEIGHTS.update(old)
    monkeypatch.setattr(rp, "_bars", lambda code, secid="", market="A", count=60: [_bar("2026-07-10", 10.0)])
    r = client.get("/api/review/kline?code=600519")
    assert r.status_code == 200 and r.json()["data"][0]["close"] == 10.0
    assert client.get("/api/review/kline?code=**bad**").status_code == 400


def test_sample_day_browse(shadow, monkeypatch):
    import os
    os.makedirs(sp.SAMPLES_DIR, exist_ok=True)
    sp._save_day("2026-06-01", {"date": "2026-06-01", "generated_at": "t", "entries": [
        dict(_cand("600001", ["volume_surge"], 5e8), mature=True, perf={}),
        dict(_cand("600002", ["high_turnover"], 9e8), mature=False, perf={}),
    ]})
    days = sp.day_summaries()
    assert days == [{"date": "2026-06-01", "n": 2, "mature_n": 1}]
    es = sp.day_entries("2026-06-01")
    assert es[0]["code"] == "600002"          # 按成交额降序
    assert sp.day_entries("2026-01-01") == []


def test_match_strategies_market_floors():
    r = _row(pct=5, vol_ratio=1.5, turnover=4, amount=1e8)      # 1亿：A 股不命中
    assert "volume_surge" not in screener.match_strategies(r, screener.MARKETS["A"]["floors"])
    assert "volume_surge" in screener.match_strategies(r, screener.MARKETS["HK"]["floors"])


# ---------------------------------------------------------------------------
# 多因子评分（纯函数）
# ---------------------------------------------------------------------------

def test_pct_rank():
    s = [1.0, 2.0, 3.0, 4.0]
    assert screener._pct_rank(s, 4.0) == 100.0
    assert screener._pct_rank(s, 2.0) == 50.0
    assert screener._pct_rank(s, 0.5) == 0.0
    assert screener._pct_rank([], 1.0) == 50.0      # 空序列 → 中性


def test_attach_scores_shape_and_weights():
    cands = [
        _row(code="600001", pct=8, pct_60d=30, vol_ratio=3, turnover=10, main_pct=6, pe_ttm=20, industry="半导体"),
        _row(code="600002", pct=4, pct_60d=5, vol_ratio=1.5, turnover=4, main_pct=-2, pe_ttm=45, industry="银行"),
        _row(code="600003", pct=6, pct_60d=10, vol_ratio=2, turnover=6, main_pct=1, pe_ttm=-10, industry="AI"),
    ]
    screener.attach_scores(cands, {"半导体": 3.5, "银行": -0.5, "AI": 1.2})
    for c in cands:
        assert set(c["factors"]) == {"trend", "volume", "fund", "valuation", "industry"}
        assert all(0 <= v <= 100 for v in c["factors"].values())
        assert 0 <= c["score"] <= 100
    # 全维度更强的 600001 综合分应最高；负 PE 的估值因子记 20
    assert cands[0]["score"] > cands[1]["score"]
    assert cands[2]["factors"]["valuation"] == 20
    assert abs(sum(screener.FACTOR_WEIGHTS.values()) - 1.0) < 1e-9


def test_attach_scores_missing_fields_neutral():
    # 字段缺失（如资金字段全 null、行业不在强度表里）→ 因子取中性 50，不抛异常
    cands = [{"code": "600001", "pct": None, "vol_ratio": None, "turnover": None,
              "main_pct": None, "main_net": None, "pe_ttm": None, "industry": "冷门"}]
    screener.attach_scores(cands, {})
    f = cands[0]["factors"]
    assert f["trend"] == 50 and f["volume"] == 50 and f["fund"] == 50 and f["industry"] == 50
    assert f["valuation"] == 20                     # PE 缺失/非正按低分处理


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


def _bar(date, close, high=None, low=None, open_=None):
    return {"date": date, "open": open_ or close, "close": close,
            "high": high or close, "low": low or close}


def test_calc_metrics():
    """统一口径：信号收盘基准 / 次日开盘 / MFE / MAE / 成熟判定。"""
    bars = [_bar(f"2026-07-{12+i:02d}", 10.0 + i * 0.5, high=15.0 if i == 2 else None,
                 low=8.0 if i == 4 else None, open_=10.3 if i == 0 else None) for i in range(11)]
    m = rp.calc_metrics(10.0, bars)
    assert m["perf"]["d1"] == 0.0                      # 首日收盘 10.0
    assert m["perf"]["d5"] == 20.0                     # 12.0/10-1
    assert m["next_open"] == 10.3                      # 次日开盘 = 可执行口径
    assert m["mfe"] == 50.0                            # 窗口内最高 15.0
    assert m["mae"] == -20.0                           # 窗口内最低 8.0
    assert m["mature"] and m["perf"]["d10"] == 45.0
    # 不足 10 日：未成熟，MFE/MAE 按已有 bar 计
    m2 = rp.calc_metrics(10.0, bars[:2])
    assert not m2["mature"] and m2["perf"]["d10"] is None
    assert rp.calc_metrics(0.0, bars)["perf"]["d1"] is None   # 基准价异常不除零


def test_signal_metrics_uses_signal_close(monkeypatch):
    """信号日收盘=最后一根 ≤ entry_date 的收盘；之后的 bar 算 perf。"""
    bars = [_bar("2026-07-09", 9.0), _bar("2026-07-10", 10.0),
            _bar("2026-07-13", 11.0), _bar("2026-07-14", 12.0)]
    monkeypatch.setattr(rp, "_bars", lambda code, secid="", market="A", count=30: bars)
    m = rp.signal_metrics("600001", "2026-07-10")
    assert m["signal_close"] == 10.0
    assert m["perf"]["d1"] == 10.0                     # 11/10-1
    # 周末入池（entry_date 非交易日）→ 用之前最近交易日收盘
    m2 = rp.signal_metrics("600001", "2026-07-12")
    assert m2["signal_close"] == 10.0
    # 全部 bar 都晚于 entry_date（数据不足）→ None
    monkeypatch.setattr(rp, "_bars", lambda code, secid="", market="A", count=30: bars[2:])
    assert rp.signal_metrics("600001", "2026-07-10") is None


# ---------------------------------------------------------------------------
# 复盘池 CRUD（tmp 存储 + 打桩行情）
# ---------------------------------------------------------------------------

@pytest.fixture()
def pool(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "POOL_FILE", str(tmp_path / "reviewpool.json"))
    monkeypatch.setattr(rp, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(rp.astock, "tencent_quote",
                        lambda codes: {c: {"name": f"股{c}", "price": 10.0, "change_pct": 1.0} for c in codes})
    monkeypatch.setattr(rp, "signal_metrics",
                        lambda code, entry_date, secid="", market="A": {
                            "perf": {"d1": 5.0, "d3": None, "d5": None, "d10": None},
                            "next_open": 10.2, "mfe": 6.0, "mae": -2.0,
                            "mature": False, "last_close": 10.5, "signal_close": 10.0})
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
    assert e["signal_close"] == 10.0 and e["next_open"] == 10.2
    assert e["mfe"] == 6.0 and e["mae"] == -2.0
    assert e["status"] == "待成熟" and e["tag"] == ""

    assert pool.update_tag(e["id"], "重点关注", "缩量回踩")
    assert pool.get_pool()["entries"][0]["tag"] == "重点关注"
    assert not pool.update_tag("nonexistent", "观察", "")

    assert pool.remove(e["id"])
    assert pool.get_pool()["total"] == 0


def test_default_secid():
    assert rp._default_secid("600519") == "1.600519"
    assert rp._default_secid("510300") == "1.510300"   # 沪 ETF
    assert rp._default_secid("000001") == "0.000001"
    assert rp._default_secid("159915") == "0.159915"   # 深 ETF


def test_pool_add_non_a_with_price(pool):
    """非 A 股入池：价格/名称由扫描行带入，不走腾讯行情。"""
    r = pool.add_batch([{"code": "AAPL", "name": "苹果", "price": 200.5,
                         "secid": "105.AAPL", "market": "US"}])
    assert r["added"] == 1
    e = [x for x in pool.get_pool()["entries"] if x["code"] == "AAPL"][0]
    assert e["entry_price"] == 200.5 and e["market"] == "US" and e["name"] == "苹果"


def test_api_scan_bad_market_pool_400():
    assert client.get("/api/review/scan?market=XX").status_code == 400
    assert client.get("/api/review/scan?pool=nope").status_code == 400


def test_pool_mature_locks(pool, monkeypatch):
    pool.add_batch([{"code": "000001"}])
    monkeypatch.setattr(pool, "signal_metrics",
                        lambda code, entry_date, secid="", market="A": {
                            "perf": {"d1": 1.0, "d3": 3.0, "d5": 5.0, "d10": 9.0},
                            "next_open": 10.1, "mfe": 12.0, "mae": -3.0,
                            "mature": True, "last_close": 10.9, "signal_close": 10.0})
    e = pool.get_pool(refresh=True)["entries"][0]
    assert e["mature"] and e["status"] == "成熟" and e["perf"]["d10"] == 9.0

    # 成熟且已是新口径 → 不再重拉 K 线（打桩成抛异常也不影响）
    def boom(code, entry_date, secid="", market="A"):
        raise AssertionError("成熟样本不应重拉行情")
    monkeypatch.setattr(pool, "signal_metrics", boom)
    assert pool.get_pool(refresh=True)["entries"][0]["perf"]["d10"] == 9.0


# ---------------------------------------------------------------------------
# 影子样本 + 策略表现统计
# ---------------------------------------------------------------------------
import samples as sp


@pytest.fixture()
def shadow(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "SAMPLES_DIR", str(tmp_path / "samples"))
    monkeypatch.setattr(sp, "is_trading_day", lambda d: True)
    monkeypatch.setattr(rp, "POOL_FILE", str(tmp_path / "reviewpool.json"))
    sp._STATS_CACHE[1] = None
    sp._STATS_CACHE_EXTRA.clear()
    return monkeypatch


def _cand(code, strategies, amount, score=60):
    return {"code": code, "name": f"股{code}", "market": "A", "secid": f"0.{code}",
            "industry": "测试", "strategies": strategies, "flags": [], "score": score,
            "factors": {}, "amount": amount, "pct": 5.0, "vol_ratio": 2.0,
            "turnover": 5.0, "price": 10.0}


def test_capture_today_caps_and_dedupes(shadow, monkeypatch):
    cands = ([_cand(f"6001{i:02d}", ["volume_surge"], 1e8 * (50 - i)) for i in range(40)] +
             [_cand("600000", ["volume_surge", "high_turnover"], 9e9)])   # 双命中去重
    monkeypatch.setattr(sp.screener, "scan",
                        lambda m="A", p="all", force=False: {"generated_at": "t", "candidates": cands})
    r = sp.capture_today()
    # volume_surge 按成交额 top30（含 600000）+ high_turnover 仅 600000（已去重）→ 30
    assert r["captured"] == 30
    assert sp.capture_today()["note"] == "今日已存档"   # 幂等
    data = sp._load_day(sp._today())
    e = data["entries"][0]
    assert e["signal_close"] == 10.0 and e["mature"] is False


def test_update_pending_and_stats(shadow, monkeypatch):
    # 存一个历史日文件（两条样本：一条会成熟、一条数据缺失保持原样）
    day = "2026-06-01"
    entries = [dict(_cand("600001", ["volume_surge"], 5e8, score=75),
                    signal_close=10.0, next_open=None, mfe=None, mae=None,
                    perf={"d1": None, "d3": None, "d5": None, "d10": None}, mature=False),
               dict(_cand("600002", ["high_turnover"], 3e8, score=45),
                    signal_close=20.0, next_open=None, mfe=None, mae=None,
                    perf={"d1": None, "d3": None, "d5": None, "d10": None}, mature=False)]
    for e in entries:
        e.pop("price")
    import os
    os.makedirs(sp.SAMPLES_DIR, exist_ok=True)
    sp._save_day(day, {"date": day, "generated_at": "t", "entries": entries})

    bars = [_bar(day, 10.0)] + [_bar(f"2026-06-{2+i:02d}", 10.0 + i + 1) for i in range(10)]
    monkeypatch.setattr(sp.reviewpool, "_bars",
                        lambda code, secid="", market="A", count=40: bars if code == "600001" else [])
    assert sp.update_pending() == 1
    e = sp._load_day(day)["entries"][0]
    assert e["mature"] and e["perf"]["d10"] == 100.0   # 20/10-1

    # 统计：基准打桩为每窗口 +1%
    monkeypatch.setattr(sp, "bench_perf", lambda d: {"d1": 1.0, "d3": 1.0, "d5": 1.0, "d10": 1.0})
    s = sp.stats()
    assert s["shadow_total"] == 2 and s["shadow_mature"] == 1
    vs = s["by_strategy"]["volume_surge"]
    assert vs["n"] == 1 and vs["avg"]["d5"] == 50.0 and vs["win5"] == 100.0
    assert vs["excess5"] == 49.0                       # 50 - 基准1
    band70 = next(b for b in s["by_score"] if b["band"] == "70+")
    assert band70["n"] == 1
    assert s["manual"]["n"] == 0                       # 空池


def test_bench_perf_from_index(shadow, monkeypatch):
    bars = [_bar("2026-06-01", 100.0), _bar("2026-06-02", 101.0), _bar("2026-06-03", 102.0),
            _bar("2026-06-04", 103.0), _bar("2026-06-05", 104.0), _bar("2026-06-08", 105.0)]
    monkeypatch.setattr(sp, "_index_bars", lambda count=250: bars)
    b = sp.bench_perf("2026-06-01")
    assert b["d1"] == 1.0 and b["d5"] == 5.0 and b["d10"] is None
    # 非交易日入池 → 用之前最近交易日为基准（06-05 收 104 → 06-08 收 105 = +0.96%）
    assert sp.bench_perf("2026-06-06")["d1"] == 0.96


def test_api_stats_shape(shadow, monkeypatch):
    monkeypatch.setattr(sp, "bench_perf", lambda d: {"d1": None, "d3": None, "d5": None, "d10": None})
    r = client.get("/api/review/stats")
    assert r.status_code == 200
    d = r.json()["data"]
    assert {"by_strategy", "by_score", "shadow", "manual", "days", "shadow_total", "note"} <= set(d)


def test_diagnose(scan_isolated):
    snapshot = [
        _row(code="600001", name="差一点", pct=2.1, vol_ratio=1.8, turnover=4, amount=3e8),
        _row(code="600002", name="全命中", pct=5, vol_ratio=2.5, turnover=6, amount=5e8, pe_ttm=30),
    ]
    scan_isolated.setattr(screener, "market_snapshot", lambda market="A", force=False: snapshot)
    d = screener.diagnose("600001")
    vs = next(s for s in d["strategies"] if s["key"] == "volume_surge")
    assert not vs["hit"]
    by_label = {x["label"]: x for x in vs["conds"]}
    assert not by_label["涨幅 3%~9%"]["ok"] and by_label["涨幅 3%~9%"]["actual"] == "2.1%"
    assert by_label["量比 >1.3"]["ok"]
    # 名称包含匹配 + 已命中提示
    d2 = screener.diagnose("全命中")
    assert d2["stock"]["code"] == "600002"
    assert any(s["hit"] for s in d2["strategies"]) and d2["notes"]
    # 找不到 → None；API → 404
    assert screener.diagnose("999999") is None
    r = client.get("/api/review/diagnose?q=999999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 数据存储：清单 / 备份 / 清理
# ---------------------------------------------------------------------------
import io
import zipfile

import storage as st


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    d = tmp_path / ".cache"
    d.mkdir()
    (d / "reviewpool.json").write_text('{"entries": []}', encoding="utf-8")
    (d / "scancache.json").write_text('{"scan:A:all": [0, {}]}', encoding="utf-8")
    sub = d / "samples"
    sub.mkdir()
    (sub / "2026-07-10.json").write_text('{"entries": []}', encoding="utf-8")
    (d / "unknown.bin").write_bytes(b"x" * 10)
    monkeypatch.setattr(st, "CACHE_DIR", str(d))
    return d


def test_storage_inventory(cache_dir):
    inv = st.inventory()
    by_key = {i["key"]: i for i in inv["items"]}
    assert by_key["reviewpool.json"]["kind"] == "asset" and by_key["reviewpool.json"]["exists"]
    assert by_key["samples"]["files"] == 1
    assert by_key["scancache.json"]["kind"] == "cache"
    assert by_key["unknown.bin"]["kind"] == "other"            # 未登记项如实展示
    assert by_key["factor_weights.json"]["exists"] is False    # 登记但未创建 → 占位行
    assert inv["total_size"] > 0 and inv["asset_size"] > 0
    assert inv["dir"] == str(cache_dir)


def test_storage_backup_zip(cache_dir):
    data = st.backup_zip()
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert "reviewpool.json" in names
    assert any(n.startswith("samples/") for n in names)
    assert "scancache.json" not in names                       # 缓存类不进备份


def test_storage_clear_caches(cache_dir):
    r = st.clear_caches()
    assert "扫描缓存" in r["removed"] and r["freed"] > 0
    assert not (cache_dir / "scancache.json").exists()
    assert (cache_dir / "reviewpool.json").exists()            # 资产不动
    assert (cache_dir / "unknown.bin").exists()                # 未登记项不动


def test_api_storage_shape(cache_dir):
    r = client.get("/api/review/storage")
    assert r.status_code == 200
    d = r.json()["data"]
    assert {"dir", "total_size", "asset_size", "items"} <= set(d)
    r = client.get("/api/review/storage/backup")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"


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
                        lambda market="A", force=False: [_row(code="600001", name="甲", pct=5, vol_ratio=1.5, turnover=4, amount=3e8)])
    monkeypatch.setattr(screener, "fund_snapshot", lambda: {})
    monkeypatch.setattr(screener, "industry_strength", lambda: {})
    monkeypatch.setattr(rp, "POOL_FILE", str(tmp_path / "reviewpool.json"))
    monkeypatch.setattr(screener, "_SCAN_CACHE_FILE", str(tmp_path / "scancache.json"))
    monkeypatch.setattr(sp, "recent_hits", lambda days=5, before=None: [])
    screener._CACHE.clear()
    r = client.get("/api/review/scan?refresh=1")
    assert r.status_code == 200
    d = r.json()["data"]
    assert set(d) == {"generated_at", "scanned", "strategies", "candidates",
                      "market", "pool", "pool_note", "adaptive_note", "markets", "pools"}
    c = d["candidates"][0]
    assert {"code", "name", "pct", "amount", "turnover", "vol_ratio", "pe_ttm",
            "industry", "strategies", "flags", "main_net", "super_net", "main_pct",
            "pool_history", "score", "factors", "hit_streak", "first_hit"} <= set(c)
