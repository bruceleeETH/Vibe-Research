"""复盘工作台 · 候选扫描层 —— 全市场快照 + 客观阈值硬筛。

合规：筛选是**用户可查看/可调阈值的客观规则过滤**（涨跌幅区间 / 量比 / 换手 /
成交额 / PE 区间），命中即入候选——**不打综合分、不排名推荐**（默认排序为
成交额降序的客观排序）。「提示」列为客观事实标注（涨停附近 / 换手过热 /
成交额不足），阈值机械判定、非主观评级。分析结论由用户自己配置的 AI 给出。

数据源：东财行情中心 clist 全市场快照（push2 不可达时降级 push2delay），
走 astock.em_get 统一限流；全市场一次请求拿全（不逐票拉），缓存 5 分钟。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

import astock

BEIJING = timezone(timedelta(hours=8))
_CACHE: dict = {}
_TTL = 300  # 5 分钟，同 market.py 口径


# ---------------------------------------------------------------------------
# 策略规则（客观阈值，与常见打板复盘工具同款口径；可按需改阈值）
# ---------------------------------------------------------------------------

STRATEGIES = [
    {
        "key": "volume_surge",
        "name": "放量上涨",
        "desc": "涨3%-9% + 量比>1.3 + 换手>3% + 成交>2亿",
    },
    {
        "key": "high_turnover",
        "name": "高换手",
        "desc": "量比≥2 + 换手≥5% + 成交≥3亿",
    },
    {
        "key": "value_breakout",
        "name": "估值突破",
        "desc": "涨1%-6% + 0<PE≤50 + 换手>2%",
    },
]


def match_strategies(r: dict, floors: tuple[float, float] = (2e8, 3e8)) -> list[str]:
    """一行快照 → 命中的策略 key 列表（纯函数，可单测）。None 视为不命中。

    floors = (放量上涨成交额下限, 高换手成交额下限)，按市场传入（见 MARKETS）。
    """
    pct, vr, to, amt, pe = r.get("pct"), r.get("vol_ratio"), r.get("turnover"), r.get("amount"), r.get("pe_ttm")
    hits = []
    if None not in (pct, vr, to, amt) and 3 <= pct <= 9 and vr > 1.3 and to > 3 and amt > floors[0]:
        hits.append("volume_surge")
    if None not in (vr, to, amt) and vr >= 2 and to >= 5 and amt >= floors[1]:
        hits.append("high_turnover")
    if None not in (pct, pe, to) and 1 <= pct <= 6 and 0 < pe <= 50 and to > 2:
        hits.append("value_breakout")
    return hits


def objective_flags(r: dict) -> list[str]:
    """客观事实标注（机械阈值判定，非评分非评级）。"""
    flags = []
    pct, to, amt = r.get("pct"), r.get("turnover"), r.get("amount")
    if pct is not None and pct >= 9.5:
        flags.append("涨停附近")
    if to is not None and to >= 20:
        flags.append("换手过热")
    if amt is not None and amt < 2e8:
        flags.append("成交额不足")
    return flags


# ---------------------------------------------------------------------------
# 全市场快照（东财 clist，一次请求全 A；push2 失败降级 push2delay）
# ---------------------------------------------------------------------------

# f62 主力净额 / f66 超大单净额 / f184 主力净占比% —— 随行情快照一并取（同一 clist 接口族）
# f24 60日涨跌幅 / f25 年初至今涨跌幅 —— 趋势因子用；f13 市场码 —— 拼 secid（跨市场日K用）
_SNAPSHOT_FIELDS = "f12,f13,f14,f2,f3,f6,f8,f9,f10,f20,f23,f24,f25,f100,f115,f62,f66,f184"
_FUND_FIELDS = "f12,f62,f66,f184"

# 市场定义：全部走东财 clist 同一接口族，仅 fs 不同。
# floors = (放量上涨成交额下限, 高换手成交额下限)，按各市场货币与流动性口径。
MARKETS = {
    "A":   {"name": "A股",  "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
            "floors": (2e8, 3e8)},
    "HK":  {"name": "港股", "fs": "m:128 t:3,m:128 t:4,m:128 t:1,m:128 t:2",
            "floors": (5e7, 1e8)},          # 港元
    "US":  {"name": "美股", "fs": "m:105,m:106,m:107",
            "floors": (2e8, 3e8)},          # 美元
    "ETF": {"name": "ETF", "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024,b:MK0827",
            "floors": (5e7, 1e8)},
}
_SNAPSHOT_FS = MARKETS["A"]["fs"]           # 兼容旧引用

# A 股股票池：指数成分池（akshare 惰性拉取、按日缓存）+ 板块前缀池（零依赖）
POOLS = {
    "all": "全市场",
    "hs300": "沪深300",
    "zz500": "中证500",
    "hs300zz500": "沪深300+中证500",
    "cyb": "创业板",
    "kcb": "科创板",
}
_POOL_CACHE: dict = {}  # {pool: (date_str, set[str])}
# 编号主机（akshare 同款）通常接受大分页一次拿全；裸 push2 对大 pz 可能直接断连，
# push2delay 会把页长钳到 100 —— 故按顺序探测，拿不全再降级分页。
_HOSTS = ("82.push2.eastmoney.com", "push2.eastmoney.com", "push2delay.eastmoney.com")
_MAX_PAGES = 60          # 分页兜底上限（100/页 × 60 ≈ 覆盖全 A）
_PAGE_INTERVAL = 0.3     # clist 分页限流间隔（行情中心低敏；数据中心接口仍走默认 1s）


def _norm(d: dict) -> dict:
    nf = astock._numf
    return {
        "code": str(d.get("f12", "")), "name": str(d.get("f14", "")),
        "secid": f"{d.get('f13', '')}.{d.get('f12', '')}",   # 市场码.代码（跨市场日K/行情用）
        "price": nf(d.get("f2")), "pct": nf(d.get("f3")),
        "amount": nf(d.get("f6")), "turnover": nf(d.get("f8")),
        "vol_ratio": nf(d.get("f10")),
        "pe_ttm": nf(d.get("f115")), "pe_dyn": nf(d.get("f9")), "pb": nf(d.get("f23")),
        "mcap": nf(d.get("f20")), "industry": str(d.get("f100", "") or ""),
        "main_net": nf(d.get("f62")), "super_net": nf(d.get("f66")),
        "main_pct": nf(d.get("f184")),
        "pct_60d": nf(d.get("f24")), "pct_ytd": nf(d.get("f25")),
    }


def _clist_page(host: str, pn: int, pz: int, fid: str = "f6",
                fields: str = _SNAPSHOT_FIELDS, fs: str = _SNAPSHOT_FS) -> tuple[list[dict], int]:
    """clist 一页：(diff 行, 服务端报告的 total)。异常上抛给调用方决策。"""
    params = {"pn": pn, "pz": pz, "po": 1, "np": 1, "fltt": 2, "invt": 2,
              "fid": fid, "fs": fs, "fields": fields}
    r = astock.em_get(f"https://{host}/api/qt/clist/get", params=params,
                      headers={"User-Agent": astock.UA, "Referer": "https://quote.eastmoney.com/"},
                      timeout=20, min_interval=_PAGE_INTERVAL)
    data = r.json().get("data") or {}
    return data.get("diff") or [], int(data.get("total") or 0)


def _clist_all(fid: str = "f6", fields: str = _SNAPSHOT_FIELDS, fs: str = _SNAPSHOT_FS) -> list[dict]:
    """clist 全市场拉取（原始 diff 行，按代码去重）。

    先逐主机试「单次大页拿全」；服务端钳页长/断连时，降级为按 fid 降序分页补齐
    （po=1，越靠前越是该维度头部标的，部分覆盖时也先保住主战场）。
    """
    best: list[dict] = []
    best_host = _HOSTS[0]
    for host in _HOSTS:
        try:
            diff, total = _clist_page(host, 1, 10000, fid, fields, fs)
        except Exception:
            continue
        if diff and len(diff) >= max(total, 1) * 0.9:
            return diff                              # 一次拿全
        if len(diff) > len(best):
            best, best_host = diff, host

    if not best:
        return []

    # 降级分页：沿用首页实际返回的页长（即服务端的钳制值）
    rows = list(best)
    pz = len(best)
    total = 0
    for pn in range(2, _MAX_PAGES + 1):
        try:
            diff, total = _clist_page(best_host, pn, pz, fid, fields, fs)
        except Exception:
            break
        rows.extend(diff)
        if not diff or len(diff) < pz or (total and len(rows) >= total):
            break

    seen: set[str] = set()
    out: list[dict] = []
    for d in rows:  # 分页期间排名变动可能造成跨页重复，按代码去重
        c = str(d.get("f12", ""))
        if c and c not in seen:
            seen.add(c)
            out.append(d)
    return out


def market_snapshot(market: str = "A") -> list[dict]:
    """指定市场全量快照（含主力资金字段，见 _norm）。market ∈ MARKETS。"""
    fs = MARKETS[market]["fs"]
    rows = [_norm(d) for d in _clist_all("f6", _SNAPSHOT_FIELDS, fs)]
    for r in rows:
        r["market"] = market
    return rows


# ---------------------------------------------------------------------------
# A 股股票池（指数成分按日缓存；akshare 缺失/失败时返回 None = 不过滤并附提示）
# ---------------------------------------------------------------------------

def _index_members(symbol: str) -> set[str]:
    """中证指数成分股代码集（akshare，惰性导入）。"""
    ak = astock._akshare()
    df = ak.index_stock_cons_csindex(symbol=symbol)
    return {str(c).zfill(6) for c in df["成分券代码"].tolist()} if df is not None and not df.empty else set()


def pool_codes(pool: str) -> tuple[set[str] | None, str]:
    """股票池 → (代码集 | None=不过滤, 提示)。指数成分按日缓存；失败降级全市场并说明。"""
    if pool in ("all", "", None):
        return None, ""
    if pool == "cyb":
        return None, ""   # 创业板/科创板走代码前缀（在 scan 里过滤，避免整表复制）
    if pool == "kcb":
        return None, ""
    from datetime import datetime as _dt
    today = _dt.now(BEIJING).strftime("%Y-%m-%d")
    hit = _POOL_CACHE.get(pool)
    if hit and hit[0] == today:
        return hit[1], ""
    try:
        if pool == "hs300":
            codes = _index_members("000300")
        elif pool == "zz500":
            codes = _index_members("000905")
        elif pool == "hs300zz500":
            codes = _index_members("000300") | _index_members("000905")
        else:
            return None, f"未知股票池 {pool}，已按全市场处理"
        if not codes:
            return None, "指数成分获取为空，已按全市场处理"
        _POOL_CACHE[pool] = (today, codes)
        return codes, ""
    except Exception as e:
        return None, f"指数成分获取失败（{e}），已按全市场处理"


def _in_pool(code: str, pool: str, codes: set[str] | None) -> bool:
    if pool == "cyb":
        return code.startswith("30")
    if pool == "kcb":
        return code.startswith("68")
    if codes is None:
        return True
    return code in codes


def fund_snapshot() -> dict[str, dict]:
    """全市场主力资金快照（fid=f62 独立拉取）→ {code: {main_net, super_net, main_pct}}。

    兜底用：行情快照里的资金字段被上游置空时，再走这条补一次。
    """
    nf = astock._numf
    return {
        str(d.get("f12", "")): {
            "main_net": nf(d.get("f62")), "super_net": nf(d.get("f66")),
            "main_pct": nf(d.get("f184")),
        }
        for d in _clist_all("f62", _FUND_FIELDS)
    }


# ---------------------------------------------------------------------------
# 多因子拆解 + 加权综合分（个人复盘用；权重与算法全部公开在此，可按偏好调整）
#
# 每个因子先在【当前候选集内】做百分位归一（0-100），再按权重加权合成综合分。
# 百分位相对候选集而非全市场：候选本身已过硬筛，比较的是"入选者之间谁更突出"。
# ---------------------------------------------------------------------------

FACTOR_WEIGHTS = {
    "trend": 0.25,      # 趋势：当日涨幅 70% + 60日涨幅 30%
    "volume": 0.25,     # 量能：量比 50% + 换手 50%
    "fund": 0.20,       # 资金：主力净占比（缺失时用主力净额）
    "valuation": 0.15,  # 估值：PE 越低分越高（负 PE 记 20 分）
    "industry": 0.15,   # 行业：所属行业当日涨幅在全行业中的分位
}


def _pct_rank(sorted_vals: list[float], v: float) -> float:
    """v 在升序序列中的百分位（0-100）。空序列返回 50（中性）。"""
    if not sorted_vals:
        return 50.0
    below = 0
    for x in sorted_vals:
        if x <= v:
            below += 1
        else:
            break
    return below / len(sorted_vals) * 100


def industry_strength() -> dict[str, float]:
    """全行业当日涨幅 {行业名: 涨跌幅%}（东财行业板块，行业因子用）。失败返回 {}。"""
    try:
        data = astock.industry_comparison(top_n=100)
        rows = (data.get("top") or []) + (data.get("bottom") or [])
        return {r["name"]: float(r["change_pct"] or 0) for r in rows if r.get("name")}
    except Exception:
        return {}


def attach_scores(candidates: list[dict], ind_pct: dict[str, float]) -> None:
    """就地给每个候选加 factors（五因子 0-100）与 score（加权综合，0-100）。"""
    if not candidates:
        return

    def _series(fn) -> list[float]:
        return sorted(v for c in candidates if (v := fn(c)) is not None)

    trend_raw = lambda c: None if c.get("pct") is None else (c["pct"] * 0.7 + (c.get("pct_60d") or 0) * 0.3)
    vr_s = _series(lambda c: c.get("vol_ratio"))
    to_s = _series(lambda c: c.get("turnover"))
    tr_s = _series(trend_raw)
    fp_s = _series(lambda c: c.get("main_pct"))
    fn_s = _series(lambda c: c.get("main_net"))
    pe_s = _series(lambda c: c.get("pe_ttm") if (c.get("pe_ttm") or 0) > 0 else None)
    ind_s = sorted(ind_pct.values())

    for c in candidates:
        tr = trend_raw(c)
        trend = _pct_rank(tr_s, tr) if tr is not None else 50.0
        vol_parts = [
            _pct_rank(vr_s, c["vol_ratio"]) if c.get("vol_ratio") is not None else None,
            _pct_rank(to_s, c["turnover"]) if c.get("turnover") is not None else None,
        ]
        vol_parts = [p for p in vol_parts if p is not None]
        volume = sum(vol_parts) / len(vol_parts) if vol_parts else 50.0
        if c.get("main_pct") is not None:
            fund = _pct_rank(fp_s, c["main_pct"])
        elif c.get("main_net") is not None:
            fund = _pct_rank(fn_s, c["main_net"])
        else:
            fund = 50.0
        pe = c.get("pe_ttm")
        valuation = 20.0 if (pe is None or pe <= 0) else 100 - _pct_rank(pe_s, pe)
        ind = ind_pct.get(c.get("industry") or "")
        industry = _pct_rank(ind_s, ind) if ind is not None else 50.0

        factors = {
            "trend": round(trend), "volume": round(volume), "fund": round(fund),
            "valuation": round(valuation), "industry": round(industry),
        }
        c["factors"] = factors
        c["score"] = round(sum(factors[k] * w for k, w in FACTOR_WEIGHTS.items()))


def scan(market: str = "A", pool: str = "all", force: bool = False) -> dict:
    """扫描指定市场（可选 A 股股票池）→ 候选清单（命中任一策略即入选）。

    缓存 5 分钟（按 market+pool 分键）；force=True 强制重扫。空返回不缓存。
    """
    if market not in MARKETS:
        market = "A"
    if market != "A":
        pool = "all"           # 股票池仅对 A 股生效
    now = time.time()
    key = f"scan:{market}:{pool}"
    hit = _CACHE.get(key)
    if hit and not force and now - hit[0] < _TTL:
        return hit[1]

    rows = market_snapshot(market)
    codes, pool_note = pool_codes(pool)
    floors = MARKETS[market]["floors"]
    candidates = []
    for r in rows:
        if market == "A":
            if "ST" in r["name"].upper() or "退" in r["name"]:
                continue  # 客观排除：风险警示/退市整理标的
            if not _in_pool(r["code"], pool, codes):
                continue
        hits = match_strategies(r, floors)
        if not hits:
            continue
        r2 = dict(r)
        r2.setdefault("main_net", None)
        r2.setdefault("super_net", None)
        r2.setdefault("main_pct", None)
        r2["strategies"] = hits
        r2["flags"] = objective_flags(r)
        candidates.append(r2)
    candidates.sort(key=lambda x: -(x["amount"] or 0))

    # 资金字段兜底：行情快照里全空（上游对该组合字段间歇置空）时，独立按 f62 补拉一次
    if candidates and all(c["main_net"] is None for c in candidates):
        try:
            fund = fund_snapshot()
            for c in candidates:
                c.update(fund.get(c["code"], {}))
        except Exception:
            pass  # 资金源故障不挡扫描，字段保持 null、前端显示「—」

    # 复盘历史关联：该候选此前历次入池的真实表现（本地池文件，客观回放）
    try:
        import reviewpool
        history = reviewpool.history_by_code({c["code"] for c in candidates})
    except Exception:
        history = {}
    for c in candidates:
        c["pool_history"] = history.get(c["code"], [])

    # 多因子拆解 + 综合分（个人复盘用，权重见 FACTOR_WEIGHTS）。行业强度仅 A 股有源，
    # 其他市场传空表 → 行业因子中性 50。
    attach_scores(candidates, industry_strength() if market == "A" else {})

    counts = {s["key"]: 0 for s in STRATEGIES}
    for c in candidates:
        for k in c["strategies"]:
            counts[k] += 1
    result = {
        "generated_at": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
        "scanned": len(rows),
        "market": market,
        "pool": pool,
        "pool_note": pool_note,
        "markets": [{"key": k, "name": v["name"]} for k, v in MARKETS.items()],
        "pools": [{"key": k, "name": v} for k, v in POOLS.items()],
        "strategies": [dict(s, count=counts[s["key"]]) for s in STRATEGIES],
        "candidates": candidates,
    }
    if rows:
        _CACHE[key] = (now, result)
    return result
