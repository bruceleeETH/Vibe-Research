#!/usr/bin/env python3
"""Generate a sortable, self-contained A-share MA5 scan HTML snapshot."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import screener  # noqa: E402


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def prefix(code: str) -> str:
    return "sh" if code.startswith("6") else "sz"


def kline(code: str, count: int = 25, retries: int = 2) -> list[dict]:
    secid = ("1." if code.startswith("6") else "0.") + code
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}&klt=101&fqt=1&lmt={count}&end=20500101"
        "&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56"
    )
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
            rows = (obj.get("data") or {}).get("klines") or []
            out = []
            for r in rows:
                p = r.split(",")
                if len(p) < 6:
                    continue
                out.append(
                    {
                        "date": str(p[0]),
                        "open": float(p[1]),
                        "close": float(p[2]),
                        "high": float(p[3]),
                        "low": float(p[4]),
                        "volume": float(p[5]),
                    }
                )
            return out
        except Exception:
            if attempt == retries:
                return []
            time.sleep(0.5 * (attempt + 1))
    return []


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def finite(value, default=0.0):
    try:
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def classify(row: dict, bars: list[dict], target_date: str) -> dict | None:
    bars = [b for b in bars if b["date"] <= target_date]
    if len(bars) < 20 or bars[-1]["date"] != target_date:
        return None
    b = bars[-1]
    closes = [x["close"] for x in bars]
    vols = [x["volume"] for x in bars]
    ma5 = avg(closes[-5:])
    prev_ma5 = avg(closes[-6:-1])
    ma10 = avg(closes[-10:])
    ma20 = avg(closes[-20:])
    if not ma5 or b["close"] <= ma5:
        return None

    above = (b["close"] / ma5 - 1) * 100
    slope = (ma5 / prev_ma5 - 1) * 100 if prev_ma5 else 0
    vol5 = b["volume"] / avg(vols[-6:-1]) if avg(vols[-6:-1]) else 0
    day_range = b["high"] - b["low"]
    close_pos = (b["close"] - b["low"]) / day_range * 100 if day_range else 50
    upper_shadow = (
        (b["high"] - max(b["open"], b["close"])) / day_range * 100
        if day_range
        else 0
    )
    fresh = bars[-2]["close"] <= prev_ma5
    pullback = b["low"] <= ma5 <= b["close"]
    if fresh:
        signal = "刚站上"
    elif pullback:
        signal = "回踩收回"
    else:
        signal = "持续在线上"

    risk = []
    if above > 5:
        risk.append("远离MA5")
    if upper_shadow >= 35:
        risk.append("长上影")
    if slope < 0:
        risk.append("MA5向下")
    if b["close"] < ma20:
        risk.append("MA20下方")

    score = 50.0
    score += 10 if fresh else (6 if pullback else 1)
    score += max(-8, min(12, slope * 12))
    score += max(-5, min(10, (vol5 - 1) * 12))
    score += (close_pos - 50) * 0.12
    score += 6 if b["close"] > ma10 else -3
    score += 8 if b["close"] > ma20 else -5
    score -= max(0, upper_shadow - 20) * 0.12
    score -= max(0, above - 3) * 2
    score = round(max(0, min(100, score)), 1)
    grade = "A" if score >= 72 else ("B" if score >= 62 else ("C" if score >= 52 else "D"))

    return {
        "code": row["code"],
        "name": row["name"],
        "industry": row.get("industry") or "未分类",
        "close": b["close"],
        "pct": finite(row.get("pct")),
        "amount": finite(row.get("amount")),
        "turnover": finite(row.get("turnover")),
        "ma5": round(ma5, 3),
        "ma10": round(ma10, 3),
        "ma20": round(ma20, 3),
        "above": round(above, 2),
        "slope": round(slope, 2),
        "vol5": round(vol5, 2),
        "closePos": round(close_pos),
        "upperShadow": round(upper_shadow),
        "signal": signal,
        "risk": risk,
        "score": score,
        "grade": grade,
        "bars": bars[-20:],
    }


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__DATE__ A股五日线扫描</title>
<style>
:root{--bg:#07110f;--panel:#0d1b18;--panel2:#10231e;--line:#214038;--text:#e9f2ed;--muted:#8ca69c;--red:#ff5d62;--green:#29d391;--amber:#ffb84d;--cyan:#41c7d9}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% -10%,#173f34 0,transparent 36%),var(--bg);color:var(--text);font:14px/1.45 "Avenir Next","PingFang SC",sans-serif}
header{padding:30px 34px 20px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;align-items:end}
h1{font:700 30px/1.1 Georgia,"Songti SC",serif;margin:0 0 8px}.sub{color:var(--muted)}.stamp{color:var(--amber);text-align:right}
.stats{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:10px;padding:18px 34px}
.stat,.controls,.tableWrap,.drawer{background:linear-gradient(145deg,rgba(16,35,30,.96),rgba(10,24,21,.96));border:1px solid var(--line);box-shadow:0 12px 30px #0004}
.stat{padding:14px 16px}.stat b{font:700 24px Georgia,serif;display:block}.stat span{color:var(--muted);font-size:12px}
.controls{margin:0 34px 12px;padding:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input,select,button{background:#091713;color:var(--text);border:1px solid #2a4c43;padding:8px 10px;border-radius:3px}input{min-width:220px}button{cursor:pointer}button.active{border-color:var(--amber);color:var(--amber)}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:12px;padding:0 34px 34px}.tableWrap{overflow:auto;max-height:calc(100vh - 245px)}
table{border-collapse:collapse;width:100%;white-space:nowrap}th{position:sticky;top:0;background:#132a24;color:#a9c4ba;text-align:right;padding:10px 9px;border-bottom:1px solid #31564c;cursor:pointer;font-size:12px;z-index:2}
th:first-child,th:nth-child(2),th:nth-child(3),td:first-child,td:nth-child(2),td:nth-child(3){text-align:left}td{padding:9px;border-bottom:1px solid #18332c;text-align:right}tr:hover{background:#17352d;cursor:pointer}
.up{color:var(--red)}.down{color:var(--green)}.tag{padding:2px 6px;border:1px solid #365b51;color:#b8d4ca;font-size:11px}.grade{font-weight:800}.grade.A{color:#ffd166}.grade.B{color:#60d9bf}.risk{color:#ff8d91}
.drawer{padding:18px;min-height:520px;position:sticky;top:12px;height:fit-content}.drawer h2{margin:0 0 4px;font:700 22px Georgia,"Songti SC",serif}.muted{color:var(--muted)}canvas{width:100%;height:190px;margin:14px 0;background:#091713;border:1px solid #1d3a32}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:8px}.metric{background:#0a1714;padding:9px;border-left:2px solid var(--cyan)}.metric b{display:block;font-size:16px}
.note{margin-top:14px;padding:11px;background:#19251c;border-left:3px solid var(--amber);color:#d8e5df}.empty{padding:40px;text-align:center;color:var(--muted)}
@media(max-width:1000px){.layout{grid-template-columns:1fr}.drawer{position:static}.stats{grid-template-columns:repeat(2,1fr)}}@media(max-width:640px){header,.stats,.layout{padding-left:14px;padding-right:14px}.controls{margin-left:14px;margin-right:14px}}
</style></head>
<body>
<header><div><h1>五日线雷达</h1><div class="sub">__SCOPE__ · 前复权 · 收盘站上MA5 · 实际扫描 __UNIVERSE__ 只</div></div><div class="stamp">交易日 __DATE__<br><span class="muted">生成 __GENERATED__</span></div></header>
<section class="stats" id="stats"></section>
<section class="controls">
 <input id="q" placeholder="搜索代码、名称、行业">
 <select id="signal"><option value="">全部形态</option><option>刚站上</option><option>回踩收回</option><option>持续在线上</option></select>
 <select id="grade"><option value="">全部评级</option><option>A</option><option>B</option><option>C</option><option>D</option></select>
 <select id="risk"><option value="">风险不过滤</option><option value="clean">排除风险标记</option></select>
 <button data-quick="fresh">只看刚站上</button><button data-quick="a">只看A档</button><button id="reset">重置</button>
 <span class="muted" id="shown"></span>
</section>
<main class="layout"><div class="tableWrap"><table><thead><tr>
<th data-k="code">代码</th><th data-k="name">名称</th><th data-k="industry">行业</th><th data-k="grade">档</th>
<th data-k="score">评分</th><th data-k="signal">形态</th><th data-k="pct">涨跌%</th><th data-k="above">高于MA5%</th>
<th data-k="slope">MA5斜率%</th><th data-k="vol5">量比5</th><th data-k="turnover">换手%</th><th data-k="amount">成交额</th><th data-k="closePos">收盘位置%</th><th>风险</th>
</tr></thead><tbody id="body"></tbody></table></div><aside class="drawer" id="drawer"><div class="empty">点击一只股票查看结构</div></aside></main>
<script>
const DATA=__DATA__;
let view=[...DATA], sortKey="score", sortDir=-1, selected=null;
const $=s=>document.querySelector(s), fmtAmt=n=>n>=1e8?(n/1e8).toFixed(1)+"亿":(n/1e4).toFixed(0)+"万";
function cls(n){return n>0?"up":n<0?"down":""}
function stats(){
 const fresh=DATA.filter(x=>x.signal==="刚站上").length,pull=DATA.filter(x=>x.signal==="回踩收回").length,a=DATA.filter(x=>x.grade==="A").length;
 const inds=Object.entries(DATA.reduce((o,x)=>(o[x.industry]=(o[x.industry]||0)+1,o),{})).sort((a,b)=>b[1]-a[1])[0]||["—",0];
 $("#stats").innerHTML=[["入选",DATA.length],["刚站上",fresh],["回踩收回",pull],["A档",a],["最多行业",inds[0]+" · "+inds[1]]].map(x=>`<div class=stat><b>${x[1]}</b><span>${x[0]}</span></div>`).join("");
}
function apply(){
 const q=$("#q").value.trim().toLowerCase(),sig=$("#signal").value,g=$("#grade").value,clean=$("#risk").value==="clean";
 view=DATA.filter(x=>(!q||[x.code,x.name,x.industry].some(v=>String(v).toLowerCase().includes(q)))&&(!sig||x.signal===sig)&&(!g||x.grade===g)&&(!clean||!x.risk.length));
 render();
}
function render(){
 view.sort((a,b)=>{let x=a[sortKey],y=b[sortKey];if(typeof x==="string")return x.localeCompare(y,"zh-CN")*sortDir;return((x??-Infinity)-(y??-Infinity))*sortDir});
 $("#shown").textContent=`显示 ${view.length} / ${DATA.length}`;
 $("#body").innerHTML=view.map(x=>`<tr data-code="${x.code}"><td>${x.code}</td><td>${x.name}</td><td>${x.industry}</td><td class="grade ${x.grade}">${x.grade}</td><td>${x.score}</td><td><span class=tag>${x.signal}</span></td><td class="${cls(x.pct)}">${x.pct.toFixed(2)}</td><td>${x.above.toFixed(2)}</td><td class="${cls(x.slope)}">${x.slope.toFixed(2)}</td><td>${x.vol5.toFixed(2)}</td><td>${x.turnover.toFixed(2)}</td><td>${fmtAmt(x.amount)}</td><td>${x.closePos}</td><td class=risk>${x.risk.join(" · ")||"—"}</td></tr>`).join("");
 document.querySelectorAll("tbody tr").forEach(tr=>tr.onclick=()=>detail(DATA.find(x=>x.code===tr.dataset.code)));
}
function chart(x){
 const c=$("#chart"),dpr=devicePixelRatio||1,w=c.clientWidth,h=190;c.width=w*dpr;c.height=h*dpr;const g=c.getContext("2d");g.scale(dpr,dpr);g.clearRect(0,0,w,h);
 const bs=x.bars,vals=bs.flatMap(b=>[b.high,b.low]),min=Math.min(...vals),max=Math.max(...vals),pad=15,yy=v=>pad+(max-v)/(max-min||1)*(h-pad*2),step=(w-20)/bs.length;
 g.strokeStyle="#203f37";g.lineWidth=1;for(let i=0;i<4;i++){let y=pad+i*(h-2*pad)/3;g.beginPath();g.moveTo(8,y);g.lineTo(w-8,y);g.stroke()}
 bs.forEach((b,i)=>{let xx=10+i*step+step/2,up=b.close>=b.open;g.strokeStyle=up?"#ff5d62":"#29d391";g.fillStyle=g.strokeStyle;g.beginPath();g.moveTo(xx,yy(b.high));g.lineTo(xx,yy(b.low));g.stroke();let top=yy(Math.max(b.open,b.close)),bot=yy(Math.min(b.open,b.close));g.fillRect(xx-step*.25,top,step*.5,Math.max(1,bot-top))});
 const ma=(n,col)=>{g.strokeStyle=col;g.lineWidth=1.5;g.beginPath();let started=false;bs.forEach((b,i)=>{if(i<n-1)return;let v=bs.slice(i-n+1,i+1).reduce((s,z)=>s+z.close,0)/n,xx=10+i*step+step/2;started?g.lineTo(xx,yy(v)):(g.moveTo(xx,yy(v)),started=true)});g.stroke()};ma(5,"#ffb84d");ma(10,"#41c7d9");
}
function detail(x){selected=x;$("#drawer").innerHTML=`<h2>${x.name} <span class=muted>${x.code}</span></h2><div><span class="grade ${x.grade}">${x.grade}档 · ${x.score}分</span>　<span class=tag>${x.signal}</span></div><canvas id=chart></canvas><div class=metrics>
<div class=metric><span class=muted>收盘 / MA5</span><b>${x.close.toFixed(2)} / ${x.ma5.toFixed(2)}</b></div><div class=metric><span class=muted>高于MA5</span><b>${x.above.toFixed(2)}%</b></div>
<div class=metric><span class=muted>MA5斜率</span><b class=${cls(x.slope)}>${x.slope.toFixed(2)}%</b></div><div class=metric><span class=muted>成交量 / 前5日均量</span><b>${x.vol5.toFixed(2)}×</b></div>
<div class=metric><span class=muted>MA10 / MA20</span><b>${x.ma10.toFixed(2)} / ${x.ma20.toFixed(2)}</b></div><div class=metric><span class=muted>收盘位置</span><b>${x.closePos}%</b></div></div>
<div class=note>${x.risk.length?"风险标记："+x.risk.join("、"):"暂无结构性风险标记"}。次日应等待价格与量能确认，站上MA5不等于买入信号。</div>`;requestAnimationFrame(()=>chart(x))}
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{const k=th.dataset.k;sortDir=sortKey===k?-sortDir:-1;sortKey=k;render()});
["q","signal","grade","risk"].forEach(id=>$("#"+id).addEventListener(id==="q"?"input":"change",apply));
document.querySelectorAll("[data-quick]").forEach(b=>b.onclick=()=>{if(b.dataset.quick==="fresh")$("#signal").value="刚站上";else $("#grade").value="A";apply()});
$("#reset").onclick=()=>{$("#q").value="";$("#signal").value="";$("#grade").value="";$("#risk").value="";apply()};
stats();apply();if(DATA.length)detail(DATA[0]);
</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="Trading date, YYYY-MM-DD")
    ap.add_argument("--min-amount", type=float, default=1e8)
    ap.add_argument("--top", type=int, default=800, help="Keep the most liquid N stocks; 0 means all")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    # Combined Eastmoney fs queries can be capped at ~800 rows by some hosts.
    # Fetch each board separately, then de-duplicate, so the coverage count is auditable.
    raw = []
    for fs in ("m:0+t:6", "m:0+t:80", "m:1+t:2", "m:1+t:23"):
        raw.extend(screener._clist_all("f6", screener._SNAPSHOT_FIELDS, fs))
    by_code = {}
    for d in raw:
        r = screener._norm(d)
        if r.get("code"):
            by_code[r["code"]] = r
    rows = list(by_code.values())
    universe = [
        r
        for r in rows
        if r.get("code", "").startswith(("0", "3", "6"))
        and "ST" not in (r.get("name") or "").upper()
        and "退" not in (r.get("name") or "")
        and finite(r.get("amount")) >= args.min_amount
        and finite(r.get("price")) > 0
    ]
    universe.sort(key=lambda r: finite(r.get("amount")), reverse=True)
    if args.top > 0:
        universe = universe[: args.top]
    print(f"snapshot={len(rows)} liquid_universe={len(universe)}", flush=True)

    results = []
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        jobs = {ex.submit(kline, r["code"]): r for r in universe}
        for i, fut in enumerate(as_completed(jobs), 1):
            r = jobs[fut]
            bars = fut.result()
            item = classify(r, bars, args.date)
            if item:
                results.append(item)
            elif not bars:
                failures += 1
            if i % 250 == 0:
                print(f"kline {i}/{len(universe)} matches={len(results)} failures={failures}", flush=True)

    results.sort(key=lambda x: (-x["score"], -x["amount"]))
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output = args.output or ROOT / "research" / f"{args.date}-A股五日线扫描.html"
    payload = json.dumps(results, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (
        HTML.replace("__DATE__", args.date)
        .replace("__GENERATED__", generated)
        .replace("__UNIVERSE__", str(len(universe)))
        .replace("__SCOPE__", f"沪深A股成交额前{args.top}" if args.top > 0 else "沪深A股")
        .replace("__DATA__", payload)
    )
    output.write_text(html, encoding="utf-8")
    print(f"written={output} matches={len(results)} failures={failures}", flush=True)
    return 0 if results else 2


if __name__ == "__main__":
    raise SystemExit(main())
