#!/usr/bin/env python3
"""大跌日复盘研究 —— 抓日K → 定位目标日 → 同级别大跌日的历史规律统计。

用法（在仓库根目录）：
    backend/.venv/bin/python tools/drop_study.py                          # 上证指数，最近交易日
    backend/.venv/bin/python tools/drop_study.py --date 2026-07-17       # 指定目标日
    backend/.venv/bin/python tools/drop_study.py --secid 1.588200        # 换标的（ETF/个股）
    backend/.venv/bin/python tools/drop_study.py --days 750              # 历史长度（默认约3年）

输出：终端打印人类可读报告 + 全量数据存 data/drop_study_<secid>.json（AI 复盘可直接读）。
常用 secid：上证 1.000001 · 深成 0.399001 · 创业板 0.399006 · 沪深300 1.000300 ·
           科创芯片ETF 1.588200 · 个股 = (沪1/深0).代码
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import astock  # noqa: E402


def fetch_bars_em(secid: str, count: int) -> list[dict]:
    """东财通用日K（含成交量/成交额，比 astock.em_daily_kline 多两个字段）。"""
    params = {
        "secid": secid, "klt": "101", "fqt": "1", "lmt": str(count),
        "end": "20500101", "fields1": "f1,f2,f3",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {"User-Agent": astock.UA, "Referer": "https://quote.eastmoney.com/"}
    d = astock.em_get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                      params=params, headers=headers, timeout=20, min_interval=0.3).json()
    out = []
    for line in (d.get("data") or {}).get("klines") or []:
        p = line.split(",")
        if len(p) >= 7:
            out.append({"date": p[0], "open": float(p[1]), "close": float(p[2]),
                        "high": float(p[3]), "low": float(p[4]),
                        "volume": float(p[5]), "amount": float(p[6])})
    return out


def fetch_bars_tencent(secid: str, count: int) -> list[dict]:
    """腾讯日K兜底（东财连不上时用）。字段无成交额，amount 记 None。"""
    import requests

    mkt, code = secid.split(".")
    symbol = ("sh" if mkt == "1" else "sz") + code
    r = requests.get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                     params={"param": f"{symbol},day,,,{count},qfq"},
                     headers={"User-Agent": astock.UA}, timeout=20)
    days = (((r.json().get("data") or {}).get(symbol) or {}).get("qfqday")
            or ((r.json().get("data") or {}).get(symbol) or {}).get("day") or [])
    return [{"date": p[0], "open": float(p[1]), "close": float(p[2]),
             "high": float(p[3]), "low": float(p[4]),
             "volume": float(p[5]), "amount": None}
            for p in days if len(p) >= 6]


def fetch_bars(secid: str, count: int) -> list[dict]:
    try:
        return fetch_bars_em(secid, count)
    except Exception as e:
        print(f"[东财不可用，改用腾讯源] {type(e).__name__}", file=sys.stderr)
        return fetch_bars_tencent(secid, count)


def study(secid: str, target_date: str, count: int) -> dict:
    bars = fetch_bars(secid, count)
    if len(bars) < 80:
        sys.exit(f"数据不足：只取到 {len(bars)} 根（检查 secid / 网络）")
    closes = [b["close"] for b in bars]

    rows = []
    for i, b in enumerate(bars):
        prev = bars[i - 1]["close"] if i else None
        rows.append({
            **b,
            "pct": round((b["close"] / prev - 1) * 100, 2) if prev else None,
            "amp": round((b["high"] - b["low"]) / prev * 100, 2) if prev else None,   # 振幅
            "open_pct": round((b["open"] / prev - 1) * 100, 2) if prev else None,
        })

    target = target_date or rows[-1]["date"]
    ti = next((i for i, r in enumerate(rows) if r["date"] == target), None)
    if ti is None or ti < 61:
        near = ", ".join(r["date"] for r in rows[-5:])
        sys.exit(f"{target} 不在数据范围内或历史不足（最近几个交易日：{near}）")
    t = rows[ti]

    def ma(i: int, n: int):
        return round(sum(closes[i - n + 1:i + 1]) / n, 2) if i >= n - 1 else None

    vols = [b["volume"] for b in bars]
    vol5 = sum(vols[ti - 5:ti]) / 5
    day = {
        "date": t["date"], "close": t["close"], "pct": t["pct"], "amp": t["amp"],
        "open_pct": t["open_pct"],
        "vol_ratio5": round(t["volume"] / vol5, 2) if vol5 else None,   # 量能相对前5日
        "lower_shadow": round((min(t["open"], t["close"]) - t["low"]) / rows[ti - 1]["close"] * 100, 2),
        "ma20": ma(ti, 20), "ma60": ma(ti, 60), "ma120": ma(ti, 120),
        "below_ma20": t["close"] < (ma(ti, 20) or 0),
        "below_ma60": t["close"] < (ma(ti, 60) or 0),
        "dd_from_60d_high": round((t["close"] / max(closes[ti - 60:ti]) - 1) * 100, 2),
    }

    # 同级别大跌日：跌幅 ≤ min(目标日跌幅, -1%)（保证阈值有意义）
    thr = min(t["pct"] or 0, -1.0)
    sel = [i for i, r in enumerate(rows)
           if 61 <= i and r["pct"] is not None and r["pct"] <= thr and i != ti]

    def fwd(i: int, n: int):
        return round((closes[i + n] / closes[i] - 1) * 100, 2) if i + n < len(rows) else None

    def agg(idx: list[int]) -> dict:
        out = {"n": len(idx)}
        for n in (1, 3, 5, 10):
            vals = [v for i in idx if (v := fwd(i, n)) is not None]
            out[f"d{n}_avg"] = round(sum(vals) / len(vals), 2) if vals else None
            out[f"d{n}_win"] = round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1) if vals else None
        # 二次探底率：之后 5 个交易日最低价跌破大跌日最低价的比例
        retest = [1 if min((bars[j]["low"] for j in range(i + 1, min(i + 6, len(bars)))), default=1e18) < bars[i]["low"] else 0
                  for i in idx if i + 1 < len(bars)]
        out["retest5_rate"] = round(sum(retest) / len(retest) * 100, 1) if retest else None
        return out

    # 位置分组：大跌发生时距 60 日高点的回撤
    hi_pos, mid_pos, lo_pos = [], [], []
    for i in sel:
        dd = closes[i] / max(closes[i - 60:i]) - 1
        (hi_pos if dd > -0.03 else lo_pos if dd < -0.10 else mid_pos).append(i)

    result = {
        "secid": secid, "bars_n": len(bars),
        "range": [rows[0]["date"], rows[-1]["date"]],
        "threshold_pct": thr,
        "target_day": day,
        "similar_all": agg(sel),
        "similar_high_pos": agg(hi_pos),    # 高位大跌（距60日高点回撤<3%时发生）
        "similar_mid_pos": agg(mid_pos),
        "similar_low_pos": agg(lo_pos),     # 低位大跌（已回撤>10%后再跌）
        "similar_dates_recent": [rows[i]["date"] for i in sel[-15:]],
        "bars": rows,                        # 全量日K（AI 复盘用）
    }
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--secid", default="1.000001")
    ap.add_argument("--date", default="", help="目标日 YYYY-MM-DD，默认最近交易日")
    ap.add_argument("--days", type=int, default=750)
    args = ap.parse_args()

    r = study(args.secid, args.date, args.days)
    d, s = r["target_day"], r["similar_all"]

    out_dir = os.path.join(HERE, "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"drop_study_{args.secid.replace('.', '_')}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False)

    print(f"\n== 目标日 {d['date']}（{r['secid']}） ==")
    print(f"跌幅 {d['pct']}% · 振幅 {d['amp']}% · 开盘 {d['open_pct']}% · 量能/前5日 {d['vol_ratio5']}x")
    print(f"下影线 {d['lower_shadow']}% · 收盘 {'跌破' if d['below_ma20'] else '守住'}MA20"
          f"({d['ma20']}) · {'跌破' if d['below_ma60'] else '守住'}MA60({d['ma60']}) · 距60日高点 {d['dd_from_60d_high']}%")
    print(f"\n== 近{r['bars_n']}个交易日内，单日跌幅 ≤ {r['threshold_pct']}% 的可比大跌日：{s['n']} 次 ==")
    for label, g in (("全部", s), ("高位大跌", r["similar_high_pos"]),
                     ("中位", r["similar_mid_pos"]), ("低位大跌", r["similar_low_pos"])):
        if not g["n"]:
            continue
        print(f"[{label} n={g['n']}] 后1日均 {g['d1_avg']}%(胜率{g['d1_win']}%) · "
              f"后3日 {g['d3_avg']}%({g['d3_win']}%) · 后5日 {g['d5_avg']}%({g['d5_win']}%) · "
              f"后10日 {g['d10_avg']}%({g['d10_win']}%) · 5日内二次探底率 {g['retest5_rate']}%")
    print(f"\n最近的可比大跌日：{', '.join(r['similar_dates_recent'])}")
    print(f"\n数据已存 {os.path.relpath(out_file, os.path.join(HERE, '..'))}（跟 AI 说「跑完了」即可让它读取复盘）")


if __name__ == "__main__":
    main()
