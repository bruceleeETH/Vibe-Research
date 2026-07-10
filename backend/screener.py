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


def match_strategies(r: dict) -> list[str]:
    """一行快照 → 命中的策略 key 列表（纯函数，可单测）。None 视为不命中。"""
    pct, vr, to, amt, pe = r.get("pct"), r.get("vol_ratio"), r.get("turnover"), r.get("amount"), r.get("pe_ttm")
    hits = []
    if None not in (pct, vr, to, amt) and 3 <= pct <= 9 and vr > 1.3 and to > 3 and amt > 2e8:
        hits.append("volume_surge")
    if None not in (vr, to, amt) and vr >= 2 and to >= 5 and amt >= 3e8:
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

_SNAPSHOT_FIELDS = "f12,f14,f2,f3,f6,f8,f9,f10,f20,f23,f100,f115"
_SNAPSHOT_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"
# 编号主机（akshare 同款）通常接受大分页一次拿全；裸 push2 对大 pz 可能直接断连，
# push2delay 会把页长钳到 100 —— 故按顺序探测，拿不全再降级分页。
_HOSTS = ("82.push2.eastmoney.com", "push2.eastmoney.com", "push2delay.eastmoney.com")
_MAX_PAGES = 60          # 分页兜底上限（100/页 × 60 ≈ 覆盖全 A）
_PAGE_INTERVAL = 0.3     # clist 分页限流间隔（行情中心低敏；数据中心接口仍走默认 1s）


def _norm(d: dict) -> dict:
    nf = astock._numf
    return {
        "code": str(d.get("f12", "")), "name": str(d.get("f14", "")),
        "price": nf(d.get("f2")), "pct": nf(d.get("f3")),
        "amount": nf(d.get("f6")), "turnover": nf(d.get("f8")),
        "vol_ratio": nf(d.get("f10")),
        "pe_ttm": nf(d.get("f115")), "pe_dyn": nf(d.get("f9")), "pb": nf(d.get("f23")),
        "mcap": nf(d.get("f20")), "industry": str(d.get("f100", "") or ""),
    }


def _clist_page(host: str, pn: int, pz: int) -> tuple[list[dict], int]:
    """clist 一页：(diff 行, 服务端报告的 total)。异常上抛给调用方决策。"""
    params = {"pn": pn, "pz": pz, "po": 1, "np": 1, "fltt": 2, "invt": 2,
              "fid": "f6", "fs": _SNAPSHOT_FS, "fields": _SNAPSHOT_FIELDS}
    r = astock.em_get(f"https://{host}/api/qt/clist/get", params=params,
                      headers={"User-Agent": astock.UA, "Referer": "https://quote.eastmoney.com/"},
                      timeout=20, min_interval=_PAGE_INTERVAL)
    data = r.json().get("data") or {}
    return data.get("diff") or [], int(data.get("total") or 0)


def market_snapshot() -> list[dict]:
    """全市场 A 股快照：code/name/price/pct/amount/turnover/vol_ratio/pe_ttm/pb/mcap/industry。

    先逐主机试「单次大页拿全」；服务端钳页长/断连时，降级为按成交额降序分页补齐
    （po=1 fid=f6，越靠前越是高流动性标的，部分覆盖时也先保住主战场）。
    """
    best: list[dict] = []
    best_host = _HOSTS[0]
    for host in _HOSTS:
        try:
            diff, total = _clist_page(host, 1, 10000)
        except Exception:
            continue
        if diff and len(diff) >= max(total, 1) * 0.9:
            return [_norm(d) for d in diff]          # 一次拿全
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
            diff, total = _clist_page(best_host, pn, pz)
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
            out.append(_norm(d))
    return out


def scan(force: bool = False) -> dict:
    """扫描全市场 → 候选清单（命中任一策略即入选，成交额降序的客观排序）。

    缓存 5 分钟；force=True 强制重扫。数据源空返回时不缓存、下次直接重试。
    """
    now = time.time()
    hit = _CACHE.get("scan")
    if hit and not force and now - hit[0] < _TTL:
        return hit[1]

    rows = market_snapshot()
    candidates = []
    for r in rows:
        if "ST" in r["name"].upper() or "退" in r["name"]:
            continue  # 客观排除：风险警示/退市整理标的
        hits = match_strategies(r)
        if not hits:
            continue
        r2 = dict(r)
        r2["strategies"] = hits
        r2["flags"] = objective_flags(r)
        candidates.append(r2)
    candidates.sort(key=lambda x: -(x["amount"] or 0))

    counts = {s["key"]: 0 for s in STRATEGIES}
    for c in candidates:
        for k in c["strategies"]:
            counts[k] += 1
    result = {
        "generated_at": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
        "scanned": len(rows),
        "strategies": [dict(s, count=counts[s["key"]]) for s in STRATEGIES],
        "candidates": candidates,
    }
    if rows:
        _CACHE["scan"] = (now, result)
    return result
