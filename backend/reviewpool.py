"""复盘工作台 · 复盘池数据层 —— 入池记录 + 1D/3D/5D/10D 收益客观回看。

合规：入池标的由用户主动添加（候选一键入池或手输代码），标签（重点关注/
观察/谨慎/备选）由用户手动标注；1D/3D/5D/10D 为入池后**真实收盘价的客观
回看**（复盘），不预测、不评分。数据只存本地 .cache/reviewpool.json
（gitignore、不上传、不进仓库），同持仓模块口径。

收益口径：dN = 入池日之后第 N 个**交易日**收盘价 / 入池价 - 1。
满 10D 记为「成熟」，成熟样本的收益锁定缓存、不再重拉行情。
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone, timedelta

import astock

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".cache")
POOL_FILE = os.path.join(CACHE_DIR, "reviewpool.json")
BEIJING = timezone(timedelta(hours=8))
_LOCK = threading.Lock()

TAGS = ["重点关注", "观察", "备选", "谨慎"]  # 用户手动标签（无默认、无自动评级）


def _today() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M")


def _load() -> dict:
    try:
        with open(POOL_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"entries": []}


def _save(d: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = POOL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, POOL_FILE)


# ---------------------------------------------------------------------------
# 收益计算（纯函数，可单测）
# ---------------------------------------------------------------------------

def calc_perf(entry_price: float, closes_after: list[float]) -> dict:
    """（旧口径，保留兼容）入池价 + 之后收盘序列 → {d1, d3, d5, d10}（%）。"""
    def _pct(n: int):
        if entry_price and len(closes_after) >= n:
            return round((closes_after[n - 1] / entry_price - 1) * 100, 2)
        return None
    return {"d1": _pct(1), "d3": _pct(3), "d5": _pct(5), "d10": _pct(10)}


def calc_metrics(signal_close: float, bars_after: list[dict]) -> dict:
    """统一收益口径（纯函数）：信号日收盘价为基准 + 信号日之后的日K（升序，含 OHLC）。

    - perf.dN   = 第 N 个交易日收盘 / 信号日收盘 - 1（%）——策略口径
    - next_open = 次日开盘价——可执行口径参考（你实际能买到的价）
    - mfe / mae = 10 个交易日窗口内 最高/最低价 相对信号收盘的最大浮盈 / 最大回撤（%）
    """
    closes = [b["close"] for b in bars_after]

    def _pct(n: int):
        if signal_close and len(closes) >= n:
            return round((closes[n - 1] / signal_close - 1) * 100, 2)
        return None

    win = bars_after[:10]
    mfe = mae = None
    if signal_close and win:
        mfe = round((max(b.get("high") or b["close"] for b in win) / signal_close - 1) * 100, 2)
        mae = round((min(b.get("low") or b["close"] for b in win) / signal_close - 1) * 100, 2)
    return {
        "perf": {"d1": _pct(1), "d3": _pct(3), "d5": _pct(5), "d10": _pct(10)},
        "next_open": (win[0].get("open") if win else None),
        "mfe": mfe, "mae": mae,
        "mature": len(closes) >= 10,
        "last_close": closes[-1] if closes else None,
    }


def _default_secid(code: str) -> str:
    """6 位 A 股/ETF 代码 → 东财 secid（5/6/9 开头沪市，其余深市）。"""
    return f"{'1' if code[:1] in ('5', '6', '9') else '0'}.{code}"


def _bars(code: str, secid: str = "", market: str = "A", count: int = 30) -> list[dict]:
    """日K（升序，含 OHLC）。A 股个股走腾讯（无限流）；ETF/港/美走东财通用日K。"""
    try:
        if market == "A" and len(code) == 6 and code.isdigit():
            return astock.tencent_daily_kline(code, count=count)
        return astock.em_daily_kline(secid or _default_secid(code), count=count)
    except Exception:
        return []


def signal_metrics(code: str, entry_date: str, secid: str = "", market: str = "A") -> dict | None:
    """按统一口径计算一条入池记录的指标。行情取不到返回 None（保留旧值下次再试）。"""
    bars = _bars(code, secid, market)
    if not bars:
        return None
    signal_close = None
    for b in bars:                       # 升序：最后一根 ≤ entry_date 的收盘 = 信号日收盘
        if b["date"] <= entry_date:
            signal_close = b["close"]
        else:
            break
    if not signal_close:
        return None
    m = calc_metrics(signal_close, [b for b in bars if b["date"] > entry_date])
    m["signal_close"] = signal_close
    return m


# ---------------------------------------------------------------------------
# 池操作
# ---------------------------------------------------------------------------

def add_batch(items: list[dict]) -> dict:
    """批量入池：[{code, name?, price?, secid?, market?, strategies?}]。

    入池价优先用扫描行带来的 price（多市场通用）；A 股手输缺价时兜底腾讯行情。
    同代码同日去重。
    """
    need_quote = [it["code"] for it in items
                  if not it.get("price") and len(str(it.get("code", ""))) == 6 and str(it.get("code", "")).isdigit()]
    try:
        quotes = astock.tencent_quote(need_quote) if need_quote else {}
    except Exception:
        quotes = {}
    today = _today()
    with _LOCK:
        d = _load()
        existing = {(e["code"], e["entry_date"]) for e in d["entries"]}
        added = 0
        for it in items:
            code = str(it.get("code") or "").strip()
            if not code or (code, today) in existing:
                continue
            q = quotes.get(code, {})
            price = it.get("price") or q.get("price") or 0.0
            name = it.get("name") or q.get("name") or code
            market = it.get("market") or "A"
            d["entries"].append({
                "id": uuid.uuid4().hex[:12],
                "code": code,
                "name": name,
                "market": market,
                "secid": it.get("secid") or (_default_secid(code) if code.isdigit() and len(code) == 6 else ""),
                "entry_date": today,
                "entry_price": price,
                "strategies": list(it.get("strategies") or []),
                "tag": "",          # 用户手动标注，无默认
                "note": "",
                "added": _now(),
                "perf": {"d1": None, "d3": None, "d5": None, "d10": None},
                "mature": False,
                "perf_asof": "",
                "last_close": None,
            })
            existing.add((code, today))
            added += 1
        _save(d)
    return {"added": added}


def update_tag(eid: str, tag: str, note: str) -> bool:
    with _LOCK:
        d = _load()
        for e in d["entries"]:
            if e["id"] == eid:
                e["tag"] = tag if tag in TAGS or tag == "" else e["tag"]
                e["note"] = note
                _save(d)
                return True
    return False


def remove(eid: str) -> bool:
    with _LOCK:
        d = _load()
        before = len(d["entries"])
        d["entries"] = [e for e in d["entries"] if e["id"] != eid]
        if len(d["entries"]) != before:
            _save(d)
            return True
    return False


def history_by_code(codes: set[str]) -> dict[str, list[dict]]:
    """按代码归组的历次入池记录（新→旧），给候选扫描的「复盘视角」关联用。

    只读本地池文件、不刷行情——扫描高频调用，历史表现由 get_pool 的日常刷新维护。
    """
    with _LOCK:
        d = _load()
    out: dict[str, list[dict]] = {}
    for e in d.get("entries", []):
        if e["code"] in codes:
            out.setdefault(e["code"], []).append({
                "entry_date": e["entry_date"], "entry_price": e["entry_price"],
                "perf": e.get("perf", {}), "mature": bool(e.get("mature")),
                "tag": e.get("tag", ""),
            })
    for lst in out.values():
        lst.sort(key=lambda x: x["entry_date"], reverse=True)
    return out


def get_pool(refresh: bool = False) -> dict:
    """读复盘池：当前价批量刷新 + 未成熟样本按日更新 1D/3D/5D/10D。

    成熟（满 10D）样本收益已锁定，不再重拉 K 线；未成熟样本每天只算一次
    （perf_asof 记账），refresh=True 强制重算当日。
    """
    with _LOCK:
        d = _load()
    entries = d.get("entries", [])

    # 当前价：A 股 6 位代码一次批量请求（腾讯）；非 A 股用最近收盘价（随收益刷新缓存）
    a_codes = sorted({e["code"] for e in entries if len(e["code"]) == 6 and e["code"].isdigit() and e.get("market", "A") == "A"})
    quotes: dict = {}
    if a_codes:
        try:
            quotes = astock.tencent_quote(a_codes)
        except Exception:
            quotes = {}

    today = _today()
    dirty = False
    for e in entries:
        migrated = "signal_close" in e            # 旧数据（点击价口径）→ 强制按新口径重算一次
        if e.get("mature") and migrated:
            continue
        if not refresh and e.get("perf_asof") == today and migrated:
            continue
        m = signal_metrics(e["code"], e["entry_date"], e.get("secid", ""), e.get("market", "A"))
        if m is None:
            continue  # 行情源暂不可用：保留旧值，下次再试
        e["perf"] = m["perf"]
        e["mature"] = m["mature"]
        e["signal_close"] = m["signal_close"]
        e["next_open"] = m["next_open"]
        e["mfe"] = m["mfe"]
        e["mae"] = m["mae"]
        if m["last_close"] is not None:
            e["last_close"] = m["last_close"]
        e["perf_asof"] = today
        dirty = True
    if dirty:
        with _LOCK:
            cur = _load()
            by_id = {e["id"]: e for e in entries}
            cur["entries"] = [by_id.get(e["id"], e) for e in cur.get("entries", [])]
            _save(cur)

    rows = []
    for e in sorted(entries, key=lambda x: (x["entry_date"], x["added"]), reverse=True):
        q = quotes.get(e["code"], {})
        rows.append({
            **{k: e[k] for k in ("id", "code", "name", "entry_date", "entry_price",
                                 "strategies", "tag", "note", "perf", "mature")},
            "market": e.get("market", "A"),
            "signal_close": e.get("signal_close"),
            "next_open": e.get("next_open"),
            "mfe": e.get("mfe"),
            "mae": e.get("mae"),
            "price": q.get("price") or e.get("last_close"),
            "change_pct": q.get("change_pct"),
            "status": "成熟" if e.get("mature") else "待成熟",
        })
    return {
        "entries": rows,
        "total": len(rows),
        "mature_count": sum(1 for r in rows if r["mature"]),
        "tags": TAGS,
        "updated": _now(),
    }
