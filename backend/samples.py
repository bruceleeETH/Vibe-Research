"""影子样本层 —— 每日自动存档候选 + 统一口径跟踪 + 策略表现统计。

为什么需要影子样本：手动入池只记「自己看好的」，有选择偏差，统计出的胜率无意义。
每个交易日收盘后自动把全部候选（每策略按成交额 top N）记为影子样本，与手动入池
对照，才能回答「我的挑选是否比无脑跟策略更好」。

- 存档：.cache/samples/{YYYY-MM-DD}.json（本地、gitignore，不上传）
- 口径：与复盘池一致（reviewpool.calc_metrics）——信号日收盘基准 / 次日开盘 / MFE / MAE
- 基准：A 股用中证500（secid 1.000905）同窗口收益，统计时算超额
- 调度：daemon 线程每 10 分钟检查——交易日 15:05 后存档当日 + 每日更新未成熟样本
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta

import astock
import reviewpool
import screener

BEIJING = timezone(timedelta(hours=8))
HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES_DIR = os.path.join(HERE, ".cache", "samples")

MAX_PER_STRATEGY = 30      # 每策略按成交额取前 N（控制每日样本量与更新成本）
BENCH_SECID = "1.000905"   # 中证500
_LOCK = threading.Lock()
_STATS_CACHE: list = [0.0, None]   # [ts, data]
_STATE = {"last_update_day": ""}


def _today() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d")


def _day_file(date: str) -> str:
    return os.path.join(SAMPLES_DIR, f"{date}.json")


def _load_day(date: str) -> dict | None:
    try:
        with open(_day_file(date), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_day(date: str, data: dict) -> None:
    os.makedirs(SAMPLES_DIR, exist_ok=True)
    tmp = _day_file(date) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, _day_file(date))


def _list_days() -> list[str]:
    try:
        return sorted(f[:-5] for f in os.listdir(SAMPLES_DIR) if f.endswith(".json"))
    except FileNotFoundError:
        return []


# ---------------------------------------------------------------------------
# 交易日判定 + 基准指数序列（按日缓存）
# ---------------------------------------------------------------------------

def _index_bars(count: int = 250) -> list[dict]:
    """中证500 日K（升序），当日缓存。"""
    key = f"bench:{_today()}:{count}"
    hit = _STATS_CACHE_EXTRA.get(key)
    if hit:
        return hit
    bars = astock.em_daily_kline(BENCH_SECID, count=count)
    if bars:
        _STATS_CACHE_EXTRA[key] = bars
    return bars


_STATS_CACHE_EXTRA: dict = {}


def is_trading_day(date: str) -> bool:
    """date 是否 A 股交易日：以指数日K是否有该日 bar 为准（缓存随 _index_bars）。"""
    return any(b["date"] == date for b in _index_bars(10))


def bench_perf(entry_date: str) -> dict:
    """基准（中证500）自 entry_date 收盘起的 d1/d3/d5/d10 收益（%）。缺数据为 None。"""
    bars = _index_bars()
    idx = None
    for i, b in enumerate(bars):
        if b["date"] <= entry_date:
            idx = i
        else:
            break
    if idx is None:
        return {"d1": None, "d3": None, "d5": None, "d10": None}
    base = bars[idx]["close"]
    out = {}
    for k, n in (("d1", 1), ("d3", 3), ("d5", 5), ("d10", 10)):
        j = idx + n
        out[k] = round((bars[j]["close"] / base - 1) * 100, 2) if j < len(bars) and base else None
    return out


# ---------------------------------------------------------------------------
# 存档（收盘后自动 / 手动触发）
# ---------------------------------------------------------------------------

def capture_today(force: bool = False) -> dict:
    """把今日候选存为影子样本（每策略按成交额 top N，去重）。已存过 / 非交易日则跳过。"""
    date = _today()
    with _LOCK:
        if not force and _load_day(date) is not None:
            return {"captured": 0, "note": "今日已存档"}
    if not is_trading_day(date):
        return {"captured": 0, "note": f"{date} 非交易日"}

    scan = screener.scan("A", "all")
    cands = scan.get("candidates") or []
    picked: dict[str, dict] = {}
    for s in screener.STRATEGIES:
        key = s["key"]
        hits = sorted((c for c in cands if key in c["strategies"]),
                      key=lambda x: -(x["amount"] or 0))[:MAX_PER_STRATEGY]
        for c in hits:
            picked.setdefault(c["code"], c)

    entries = [{
        "code": c["code"], "name": c["name"], "market": c.get("market", "A"),
        "secid": c.get("secid", ""), "industry": c.get("industry", ""),
        "strategies": c["strategies"], "flags": c["flags"],
        "score": c.get("score"), "factors": c.get("factors"),
        "amount": c.get("amount"), "pct": c.get("pct"),
        "vol_ratio": c.get("vol_ratio"), "turnover": c.get("turnover"),
        "signal_close": c.get("price"),   # 收盘后存档 → 现价即收盘价；更新时以日K为准修正
        "next_open": None,
        "perf": {"d1": None, "d3": None, "d5": None, "d10": None},
        "mfe": None, "mae": None, "mature": False,
    } for c in picked.values()]

    with _LOCK:
        _save_day(date, {"date": date, "generated_at": scan.get("generated_at", ""),
                         "entries": entries,
                         # 全部候选的命中表（不止 topN）——「首次命中/连续命中」回看用
                         "hits": {c["code"]: c["strategies"] for c in cands}})
    return {"captured": len(entries), "note": ""}


def recent_hits(days: int = 5, before: str | None = None) -> list[tuple[str, dict]]:
    """最近 N 个存档日的命中表 [(date, {code: [strategies]})]，新→旧，不含 before（默认今天）。

    旧存档没有 hits 字段时降级用 entries（topN 近似）。
    """
    before = before or _today()
    out: list[tuple[str, dict]] = []
    for d in reversed(_list_days()):
        if d >= before:
            continue
        data = _load_day(d)
        if data:
            hits = data.get("hits") or {e["code"]: e.get("strategies", []) for e in data.get("entries", [])}
            out.append((d, hits))
        if len(out) >= days:
            break
    return out


def day_summaries() -> list[dict]:
    """存档日概览（新→旧）：日期 / 样本数 / 成熟数。"""
    out = []
    for d in reversed(_list_days()):
        data = _load_day(d)
        if data:
            es = data.get("entries", [])
            out.append({"date": d, "n": len(es), "mature_n": sum(1 for e in es if e.get("mature"))})
    return out


def day_entries(date: str) -> list[dict]:
    """某个存档日的样本明细（新→旧按成交额）。"""
    data = _load_day(date)
    return sorted(data.get("entries", []), key=lambda e: -(e.get("amount") or 0)) if data else []


# ---------------------------------------------------------------------------
# 跟踪更新（每日一次，按代码合并拉 K 线）
# ---------------------------------------------------------------------------

def update_pending() -> int:
    """更新所有未成熟影子样本的收益指标。同一代码只拉一次日K。返回更新条数。"""
    days = _list_days()
    pending: dict[str, list[tuple[str, dict]]] = {}   # code -> [(date, entry)]
    day_data: dict[str, dict] = {}
    for d in days:
        data = _load_day(d)
        if not data:
            continue
        day_data[d] = data
        for e in data["entries"]:
            if not e.get("mature"):
                pending.setdefault(e["code"], []).append((d, e))
    if not pending:
        return 0

    updated = 0
    for code, items in pending.items():
        first = items[0][1]
        bars = reviewpool._bars(code, first.get("secid", ""), first.get("market", "A"), count=40)
        if not bars:
            continue
        for date, e in items:
            sc = None
            for b in bars:
                if b["date"] <= date:
                    sc = b["close"]
                else:
                    break
            if not sc:
                continue
            m = reviewpool.calc_metrics(sc, [b for b in bars if b["date"] > date])
            e["signal_close"] = sc
            e["perf"], e["next_open"] = m["perf"], m["next_open"]
            e["mfe"], e["mae"], e["mature"] = m["mfe"], m["mae"], m["mature"]
            updated += 1
    with _LOCK:
        for d, data in day_data.items():
            _save_day(d, data)
    return updated


# ---------------------------------------------------------------------------
# 策略表现统计
# ---------------------------------------------------------------------------

def _agg(entries: list[dict], with_excess: bool = True) -> dict:
    """一组样本 → 表现指标。胜率/盈亏比以 d5 为主口径（短线复盘惯例）。"""
    n = len(entries)
    mature_n = sum(1 for e in entries if e.get("mature"))

    def _avg(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    perf_avg = {k: _avg(e["perf"].get(k) for e in entries) for k in ("d1", "d3", "d5", "d10")}
    d5 = [e["perf"].get("d5") for e in entries if e["perf"].get("d5") is not None]
    win5 = round(sum(1 for v in d5 if v > 0) / len(d5) * 100, 1) if d5 else None
    gains, losses = sum(v for v in d5 if v > 0), -sum(v for v in d5 if v < 0)
    pf5 = round(gains / losses, 2) if losses > 0 else None
    excess5 = None
    if with_excess:
        ex = [e["perf"]["d5"] - e["bench"]["d5"] for e in entries
              if e["perf"].get("d5") is not None and (e.get("bench") or {}).get("d5") is not None]
        excess5 = round(sum(ex) / len(ex), 2) if ex else None
    return {
        "n": n, "mature_n": mature_n, "avg": perf_avg,
        "win5": win5, "pf5": pf5, "excess5": excess5,
        "mfe": _avg(e.get("mfe") for e in entries),
        "mae": _avg(e.get("mae") for e in entries),
    }


def stats() -> dict:
    """跨日聚合：分策略 / 分数段 / 影子 vs 手动。缓存 10 分钟。"""
    now = time.time()
    if _STATS_CACHE[1] and now - _STATS_CACHE[0] < 600:
        return _STATS_CACHE[1]

    shadow: list[dict] = []
    for d in _list_days():
        data = _load_day(d)
        if data:
            for e in data["entries"]:
                e["_date"] = d
                shadow.append(e)
    # 附基准（同窗口中证500）
    bench_by_date = {d: bench_perf(d) for d in {e["_date"] for e in shadow}}
    for e in shadow:
        e["bench"] = bench_by_date.get(e["_date"])

    by_strategy = {}
    for s in screener.STRATEGIES:
        sub = [e for e in shadow if s["key"] in e.get("strategies", [])]
        by_strategy[s["key"]] = dict(name=s["name"], **_agg(sub))

    bands = [("<50", 0, 50), ("50-59", 50, 60), ("60-69", 60, 70), ("70+", 70, 999)]
    by_score = [dict(band=label, **_agg([e for e in shadow
                                         if e.get("score") is not None and lo <= e["score"] < hi]))
                for label, lo, hi in bands]

    # 手动入池（复盘池，读文件不刷行情）
    manual = []
    pool = reviewpool._load().get("entries", [])
    for e in pool:
        if e.get("signal_close") is None:
            continue  # 尚未迁移到新口径的旧记录不进统计
        manual.append({"perf": e.get("perf", {}), "mfe": e.get("mfe"), "mae": e.get("mae"),
                       "mature": e.get("mature"), "bench": bench_perf(e["entry_date"])})

    result = {
        "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        "days": len(_list_days()),
        "shadow_total": len(shadow),
        "shadow_mature": sum(1 for e in shadow if e.get("mature")),
        "by_strategy": by_strategy,
        "by_score": by_score,
        "shadow": _agg(shadow),
        "manual": _agg(manual),
        "manual_n": len(manual),
        "bench_name": "中证500",
        "note": "口径：收益以信号日收盘为基准；胜率/盈亏比/超额以 5 个交易日（d5）为主口径；影子样本=每策略成交额前 %d 自动记录（无选择偏差）。" % MAX_PER_STRATEGY,
    }
    _STATS_CACHE[0], _STATS_CACHE[1] = now, result
    return result


def invalidate_stats() -> None:
    _STATS_CACHE[1] = None


# ---------------------------------------------------------------------------
# 调度：交易日 15:05 后自动存档；每日更新一次未成熟样本
# ---------------------------------------------------------------------------

def start_scheduler(interval: int = 600) -> None:
    def loop():
        time.sleep(30)  # 等服务就绪
        while True:
            try:
                now = datetime.now(BEIJING)
                today = _today()
                if now.weekday() < 5 and (now.hour, now.minute) >= (15, 5) and _load_day(today) is None:
                    capture_today()
                    invalidate_stats()
                if _STATE["last_update_day"] != today:
                    if update_pending():
                        invalidate_stats()
                    _STATE["last_update_day"] = today
            except Exception:
                pass
            time.sleep(interval)
    threading.Thread(target=loop, daemon=True).start()
