"""Trade journal: read the existing ledger; save only links and reviews in workbench."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

import workbench as wb
from trade_service import TradeError, TradeService

router = APIRouter(prefix="/api/workbench/journal", tags=["workbench-journal"])
ERRORS = dict(zip([f"E{i:02d}" for i in range(1, 11)], ["把传闻当事实", "追高", "仓位过大", "产业正确、公司错误", "公司正确、价格错误", "过早买入", "证伪不卖", "短线变长线", "亏损加仓", "被情绪带动"]))


def root():
    return wb.data_path().parents[1]


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        raise HTTPException(500, f"{path.name} 损坏或不可读，未覆盖原文件") from exc


def trades():
    payload = load_json(root() / "trades.json", {"trades": []})
    records = payload.get("trades") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise HTTPException(500, "成交文件格式错误")
    seen = set()
    for t in records:
        try:
            if not isinstance(t, dict) or not isinstance(t.get("id"), str) or not t["id"] or t["id"] in seen:
                raise ValueError()
            seen.add(t["id"])
            if t.get("side") not in ("buy", "sell") or not str(t.get("code", "")).isdigit():
                raise ValueError()
            datetime.strptime(t["date"], "%Y-%m-%d")
            if t.get("position_after") is not None:
                after = Decimal(str(t["position_after"]["shares"]))
                if not after.is_finite() or after < 0:
                    raise ValueError()
            if t.get("pnl") is not None and not Decimal(str(t["pnl"])).is_finite():
                raise ValueError()
            for key in ("quantity", "price"):
                d = Decimal(str(t[key]))
                if not d.is_finite() or d <= 0:
                    raise ValueError()
        except (ValueError, KeyError, InvalidOperation, TypeError):
            raise HTTPException(500, "成交数据存在重复 ID 或无效记录，请先核对源文件")
    return records


def build_cycles(records, state):
    cycles = []
    active = {}
    # Recorded order preserves same-day fills; out-of-order dates are explicitly incomplete.
    for t in records:
        code = t["code"]
        qty = Decimal(str(t["quantity"]))
        position = t.get("position_after")
        after = Decimal(str(position.get("shares", 0))) if isinstance(position, dict) else Decimal(0)
        before = after - qty if t["side"] == "buy" else after + qty
        if code not in active:
            c = {"id": t["id"], "code": code, "name": t.get("name") or code,
                 "start": t["date"], "end": "", "trades": [], "remaining": 0,
                 "complete": t["side"] == "buy" and before == 0, "warnings": [], "gross_pnl": 0.0}
            if not c["complete"]:
                c["warnings"].append("存在期初持仓或缺少建仓成交")
            active[code] = c
            cycles.append(c)
        c = active[code]
        if c["trades"] and (Decimal(str(c["remaining"])) != before or t["date"] < c["trades"][-1]["date"]):
            c["complete"] = False
            if "成交顺序或持仓数量不连续" not in c["warnings"]:
                c["warnings"].append("成交顺序或持仓数量不连续")
        c["trades"].append(t)
        c["remaining"] = float(after)
        if t["side"] == "sell":
            if t.get("pnl") is None:
                c["complete"] = False
                c["warnings"].append("缺少卖出收益数据")
            else:
                c["gross_pnl"] = float(Decimal(str(c["gross_pnl"])) + Decimal(str(t["pnl"])))
        if after == 0:
            c["end"] = t["date"]
            del active[code]
    cards = {c.id: c for c in state.cards}
    for c in cycles:
        links = [state.trade_links.get(t["id"]) for t in c["trades"]]
        card_ids = {l.card_id for l in links if l and l.card_id}
        c["card_id"] = next(iter(card_ids)) if len(card_ids) == 1 else None
        c["link_status"] = "待关联" if any(l is None for l in links) else "关联当前投资卡" if card_ids else "无事前计划 / 仅记账"
        if len(card_ids) > 1 or (card_ids and any(l is not None and l.card_id is None for l in links)):
            c["link_status"] = "关联不一致，请重新选择"
        card = cards.get(c["card_id"])
        c["strategy"] = card.strategy if card else "未分类"
        c["review"] = state.reviews.get(c["id"])
        c["gross_pnl"] = round(c["gross_pnl"], 2) if c["complete"] else None
        c["status"] = "已清仓" if c["end"] else "持有中"
    return list(reversed(cycles))


@router.get("")
def journal():
    return journal_data(wb.read(wb.data_path()))


def journal_data(state):
    cycles = build_cycles(trades(), state)
    portfolio = load_json(root() / "portfolio.json", {"holdings": []})
    holdings = portfolio.get("holdings", [])
    quantities = {h["code"]: h.get("shares", 0) for h in holdings}
    for c in cycles:
        if not c["end"] and c["remaining"] != quantities.get(c["code"], 0):
            c["complete"] = False
            c["gross_pnl"] = None
            c["warnings"].append("成交推导数量与当前持仓不一致，请先对账")
    recorded_codes = {c["code"] for c in cycles}
    untracked = [h["code"] for h in holdings if h["code"] not in recorded_codes]
    completed = [c for c in cycles if c["end"] and c["complete"]]
    return {"revision": state.revision, "cycles": cycles, "holdings": holdings,
            "cards": [{"id": c.id, "name": c.name, "code": c.code, "strategy": c.strategy} for c in state.cards],
            "error_labels": ERRORS, "untracked_holdings": untracked,
            "stats": {"completed": len(completed), "pending_review": sum(c["review"] is None for c in completed),
                      "gross_pnl": round(sum(c["gross_pnl"] for c in completed), 2),
                      "incomplete": sum(not c["complete"] for c in cycles)}}


def find_cycle(cycle_id, state):
    cycle = next((c for c in build_cycles(trades(), state) if c["id"] == cycle_id), None)
    if not cycle:
        raise HTTPException(404, "交易周期不存在")
    return cycle


class LinkRequest(BaseModel):
    revision: int
    cycle_id: str
    card_id: str | None = None


@router.post("/link")
def link(req: LinkRequest):
    def update(state):
        c = find_cycle(req.cycle_id, state)
        if req.card_id:
            card = next((card for card in state.cards if card.id == req.card_id), None)
            if not card or card.code != c["code"]:
                raise HTTPException(400, "只能关联同一证券的投资卡")
        now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        for trade in c["trades"]:
            state.trade_links[trade["id"]] = wb.TradeLink(card_id=req.card_id, linked_at=now)
    wb.mutate(req.revision, update)
    return journal()


class ReviewRequest(BaseModel):
    revision: int
    cycle_id: str
    review: wb.CycleReview


@router.post("/review")
def save_review(req: ReviewRequest):
    def update(state):
        c = find_cycle(req.cycle_id, state)
        if not c["end"]:
            raise HTTPException(400, "清仓后再保存周期复盘")
        if not req.review.lesson.strip():
            raise HTTPException(400, "请至少填写一条复盘结论")
        state.reviews[req.cycle_id] = req.review.model_copy(update={"updated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")})
    wb.mutate(req.revision, update)
    return journal()


class RecordRequest(BaseModel):
    trade_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    side: Literal["buy", "sell"]
    code: str = Field(pattern=r"^\d{6}$")
    name: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0, strict=True)
    price: str
    date: str

    @model_validator(mode="after")
    def validate_values(self):
        try:
            price = Decimal(self.price)
            if not price.is_finite() or price <= 0:
                raise ValueError()
            date = datetime.strptime(self.date, "%Y-%m-%d").date()
            if date > datetime.now(ZoneInfo("Asia/Shanghai")).date():
                raise ValueError()
        except (ValueError, InvalidOperation):
            raise ValueError("成交价须为正数，成交日期不能晚于今天")
        return self


@router.post("/record")
def record(req: RecordRequest):
    existing = trades()
    # Retry an existing ID even after later fills; never duplicate a successful entry.
    if not any(t["id"] == req.trade_id for t in existing) and any(t["code"] == req.code and t["date"] > req.date for t in existing):
        raise HTTPException(400, "请按成交日期顺序补录；更早记录需要先核对台账，不能直接改动当前持仓")
    service = TradeService(root())
    kwargs = dict(quantity=req.quantity, price=req.price, name=req.name, trade_date=req.date, trade_id=req.trade_id, chronological=True)
    try:
        result = service.buy(req.code, **kwargs) if req.side == "buy" else service.sell(req.code, cost=None, **kwargs)
    except TradeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"trade_id": req.trade_id, "already_recorded": result.get("already_recorded", False)}


def summarize(cycles):
    values = [c["gross_pnl"] for c in cycles]
    wins = [v for v in values if v > 0]
    losses = [-v for v in values if v < 0]
    return {"count": len(values), "wins": len(wins), "losses": len(losses),
            "zeros": sum(v == 0 for v in values),
            "win_rate": len(wins) / len(values) if values else None,
            "gross_pnl": round(sum(values), 2),
            "payoff_ratio": (sum(wins) / len(wins)) / (sum(losses) / len(losses)) if wins and losses else None,
            "cycle_ids": [c["id"] for c in cycles]}


@router.get("/analytics")
def analytics(start: date | None = None, end: date | None = None):
    if start and end and start > end:
        raise HTTPException(400, "开始日期不能晚于结束日期")
    source = journal()["cycles"]
    included = [c for c in source if c["end"] and c["complete"]
                and (not start or c["end"] >= start.isoformat())
                and (not end or c["end"] <= end.isoformat())]
    strategies, executions = {}, {}
    for c in included:
        strategy = (c["strategy"] or "未分类") if c["link_status"] == "关联当前投资卡" else "未分类"
        strategies.setdefault(strategy, []).append(c)
        executions.setdefault(c["review"].execution if c["review"] else "未复盘", []).append(c)
    errors = []
    for key, label in ERRORS.items():
        tagged = [c for c in included if c["review"] and key in c["review"].errors]
        primary = [c for c in tagged if c["review"].primary_error == key and c["gross_pnl"] < 0]
        if tagged:
            errors.append({"label": f"{key} {label}", "count": len(tagged),
                           "primary_loss": round(-sum(c["gross_pnl"] for c in primary), 2),
                           "cycle_ids": [c["id"] for c in tagged]})
    return {"total": summarize(included),
            "strategies": [{"label": k, **summarize(v)} for k, v in strategies.items()],
            "executions": [{"label": k, **summarize(v)} for k, v in executions.items()],
            "errors": errors,
            "excluded_open": sum(not c["end"] for c in source),
            "excluded_incomplete": sum(bool(c["end"]) and not c["complete"] for c in source)}


def task_items(state, cycles, today):
    items = []
    for card in state.cards:
        if card.status == "已撤销":
            continue
        base = {"name": card.name, "code": card.code, "record_id": card.id}
        if card.review_date and card.review_date <= today:
            overdue = card.review_date < today
            items.append({**base, "id": f"plan:{card.id}", "kind": "plan",
                          "date": card.review_date, "overdue": overdue,
                          "detail": f"{card.status} · " + ("已过复查日期" if overdue else "今天到期") + "，请检查研究逻辑与计划，并保存下次复查日期。"})
        pending = sum(e.status == "未核验" for e in card.evidence)
        if pending:
            items.append({**base, "id": f"evidence:{card.id}", "kind": "evidence",
                          "date": "", "overdue": False,
                          "detail": f"有 {pending} 条证据未核验，请查阅来源并保存核验状态。"})
    for cycle in cycles:
        base = {"name": cycle["name"], "code": cycle["code"], "record_id": cycle["id"],
                "date": cycle["end"] or cycle["start"], "overdue": False}
        if cycle["link_status"] not in ("关联当前投资卡", "无事前计划 / 仅记账"):
            items.append({**base, "id": f"link:{cycle['id']}", "kind": "link",
                          "detail": f"{cycle['link_status']} · {cycle['status']}。请选择投资卡，或明确记录无事前计划 / 仅记账。"})
        if cycle["end"] and cycle["review"] is None:
            items.append({**base, "id": f"review:{cycle['id']}", "kind": "review",
                          "detail": "周期已清仓，请记录执行情况与复盘结论。" +
                          ("历史不完整，可复盘但不纳入收益统计。" if not cycle["complete"] else "")})
    order = {"plan": 0, "evidence": 1, "link": 2, "review": 3}
    return sorted(items, key=lambda t: (order[t["kind"]], t["date"], t["code"], t["id"]))


@router.get("/tasks")
def tasks():
    state = wb.read(wb.data_path())
    data = journal_data(state)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    items = task_items(state, data["cycles"], today)
    return {"today": today, "revision": state.revision, "items": items,
            "counts": {kind: sum(t["kind"] == kind for t in items) for kind in ("plan", "evidence", "link", "review")}}
