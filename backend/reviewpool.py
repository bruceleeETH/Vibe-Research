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
    """入池价 + 入池日之后的收盘序列 → {d1, d3, d5, d10}（百分比，不足天数为 None）。"""
    def _pct(n: int):
        if entry_price and len(closes_after) >= n:
            return round((closes_after[n - 1] / entry_price - 1) * 100, 2)
        return None
    return {"d1": _pct(1), "d3": _pct(3), "d5": _pct(5), "d10": _pct(10)}


def _default_secid(code: str) -> str:
    """6 位 A 股/ETF 代码 → 东财 secid（5/6/9 开头沪市，其余深市）。"""
    return f"{'1' if code[:1] in ('5', '6', '9') else '0'}.{code}"


def _closes_after(code: str, entry_date: str, secid: str = "", market: str = "A") -> list[float]:
    """入池日之后（严格大于 entry_date）的日收盘序列，升序。取不到返回 []。

    A 股个股走腾讯日K（无限流）；ETF / 港股 / 美股走东财通用日K（secid）。
    """
    try:
        if market == "A" and len(code) == 6 and code.isdigit():
            bars = astock.tencent_daily_kline(code, count=30)
        else:
            bars = astock.em_daily_kline(secid or _default_secid(code), count=30)
    except Exception:
        return []
    return [b["close"] for b in bars if b["date"] > entry_date]


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
        if e.get("mature"):
            continue
        if not refresh and e.get("perf_asof") == today:
            continue
        closes = _closes_after(e["code"], e["entry_date"], e.get("secid", ""), e.get("market", "A"))
        if not closes and not refresh:
            continue  # 行情源暂不可用：保留旧值，明天再试
        e["perf"] = calc_perf(e["entry_price"], closes)
        e["mature"] = e["perf"]["d10"] is not None
        e["perf_asof"] = today
        if closes:
            e["last_close"] = closes[-1]
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
