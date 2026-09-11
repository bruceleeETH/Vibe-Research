"""Local investment notes. Current state only; never writes portfolio or trades."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator


class Evidence(BaseModel):
    title: str = Field(default="", max_length=300)
    url: str = Field(default="", max_length=2000)
    claim: str = Field(default="", max_length=10000)
    published_at: str = Field(default="", max_length=100)
    status: Literal["未核验", "已核实", "部分支持", "已否定"] = "未核验"


CATALOG = json.loads(Path(__file__).with_name("workbench_catalog.json").read_text())


class Condition(BaseModel):
    id: str
    value: str = Field(default="", max_length=2000)
    detail: str = Field(default="", max_length=2000)


def condition_errors(conditions, group):
    errors = []
    options = {x["id"]: x for x in CATALOG[group]}
    for item in conditions:
        option = options.get(item.id)
        if not option:
            raise ValueError("未知条件选项")
        value = item.value.strip()
        if not value:
            errors.append(option["parameter"])
            continue
        kind = option["kind"]
        if kind in ("price", "integer"):
            from decimal import Decimal, InvalidOperation
            try:
                number = Decimal(value)
                if not number.is_finite() or number <= 0 or (kind == "integer" and (number != number.to_integral_value() or number > 1000)):
                    raise ValueError()
            except (InvalidOperation, ValueError):
                errors.append(option["parameter"] + "必须为有效正数" + ("整数且不超过1000" if kind == "integer" else ""))
        if kind == "deadline":
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                errors.append("有效截止日期")
            if not item.detail.strip():
                errors.append("到期事项")
    return errors


class Card(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(pattern=r"^\d{6}$")
    theme: str = Field(default="", max_length=200)
    strategy: Literal["", "产业趋势", "事件驱动", "情绪资金"] = ""
    return_type: str = ""
    return_custom: str = Field(default="", max_length=1000)
    subject: str = Field(default="", max_length=2000)
    basis: str = Field(default="", max_length=10000)
    logic_ids: list[str] = Field(default_factory=list, max_length=30)
    risk_ids: list[str] = Field(default_factory=list, max_length=30)
    entry_conditions: list[Condition] = Field(default_factory=list, max_length=20)
    exit_conditions: list[Condition] = Field(default_factory=list, max_length=20)
    strategy_ack: str = ""
    thesis: str = Field(default="", max_length=10000)
    counter: str = Field(default="", max_length=10000)
    entry: str = Field(default="", max_length=10000)
    exit: str = Field(default="", max_length=10000)
    review_date: str = ""
    risk_note: str = Field(default="", max_length=10000)
    status: Literal["草稿", "已确认", "已撤销"] = "草稿"
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)
    updated_at: str = ""
    confirmed_at: str = ""

    @model_validator(mode="after")
    def validate_plan(self):
        if not self.name.strip():
            raise ValueError("请填写股票名称")
        if self.review_date:
            datetime.strptime(self.review_date, "%Y-%m-%d")
        for field, group in [(self.logic_ids, "logic"), (self.risk_ids, "risks")]:
            if len(field) != len(set(field)) or set(field) - {x["id"] for x in CATALOG[group]}:
                raise ValueError("重复或未知的逻辑/风险选项")
        if self.return_type and self.return_type not in CATALOG["returns"]:
            raise ValueError("未知收益来源")
        for conditions in (self.entry_conditions, self.exit_conditions):
            if len({c.id for c in conditions}) != len(conditions):
                raise ValueError("重复条件")
        errors = condition_errors(self.entry_conditions, "entry") + condition_errors(self.exit_conditions, "exit")
        if self.status == "已确认":
            required = [("主策略", self.strategy), ("收益来源", self.return_type),
                        ("业务或关键变量", self.subject), ("判断依据", self.basis), ("复查日期", self.review_date)]
            errors += [label for label, value in required if not value.strip()]
            if self.return_type == "自定义" and not self.return_custom.strip():
                errors.append("自定义收益来源")
            if not self.logic_ids and not self.thesis.strip():
                errors.append("研究逻辑")
            if not self.entry_conditions and not self.entry.strip():
                errors.append("入场条件")
            if not self.exit_conditions and not self.exit.strip():
                errors.append("退出复查条件")
            if self.strategy_ack != self.strategy:
                errors.append("策略条件重新确认")
            if errors:
                raise ValueError("确认计划还需补充：" + "、".join(errors))
        return self


class TradeLink(BaseModel):
    card_id: str | None = None
    linked_at: str = ""


class CycleReview(BaseModel):
    execution: Literal["按计划执行", "偏离计划", "无事前计划", "无法核实"] = "无法核实"
    errors: list[str] = Field(default_factory=list, max_length=10)
    primary_error: str = ""
    lesson: str = Field(default="", max_length=10000)
    next_action: str = Field(default="", max_length=10000)
    updated_at: str = ""

    @model_validator(mode="after")
    def check_errors(self):
        allowed = {f"E{i:02d}" for i in range(1, 11)}
        if set(self.errors) - allowed or len(set(self.errors)) != len(self.errors):
            raise ValueError("无效或重复的错误标签")
        if self.errors and self.primary_error not in self.errors:
            raise ValueError("请选择一个主要错误标签")
        if not self.errors and self.primary_error:
            raise ValueError("主要错误必须在已选标签中")
        return self


class Snapshot(BaseModel):
    revision: int = Field(default=0, ge=0)
    cards: list[Card] = Field(default_factory=list, max_length=10000)
    trade_links: dict[str, TradeLink] = Field(default_factory=dict)
    reviews: dict[str, CycleReview] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({c.id for c in self.cards}) != len(self.cards):
            raise ValueError("存在重复记录 ID")
        if any(link.card_id and link.card_id not in {c.id for c in self.cards} for link in self.trade_links.values()):
            raise ValueError("成交关联的投资卡不存在")
        return self


class SaveRequest(BaseModel):
    revision: int
    card: Card


class RevisionRequest(BaseModel):
    revision: int


class RestoreRequest(BaseModel):
    revision: int
    snapshot: Snapshot


def data_path():
    return Path(os.environ.get("VR_DATA_DIR", str(Path.home() / ".vibe-research"))) / "workbench" / "current.json"


def read(path):
    if not path.exists():
        return Snapshot()
    try:
        return Snapshot.model_validate_json(path.read_text())
    except (ValueError, OSError) as exc:
        raise HTTPException(500, "工作台文件损坏或不可读，请先检查备份；未覆盖原文件") from exc


def mutate(revision, operation):
    path = data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read(path)
        if revision != state.revision:
            raise HTTPException(409, "记录已在其他页面更新，请重新加载后再保存")
        operation(state)
        state.revision += 1
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=".current-")
        try:
            with os.fdopen(fd, "w") as out:
                out.write(state.model_dump_json(indent=2))
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return state


router = APIRouter(prefix="/api/workbench", tags=["workbench"])


@router.get("/catalog")
def catalog():
    return CATALOG


@router.get("")
def list_cards():
    return read(data_path())


@router.post("/save")
def save_card(req: SaveRequest):
    def update(state):
        old = next((c for c in state.cards if c.id == req.card.id), None)
        if old and old.code != req.card.code and any(link.card_id == old.id for link in state.trade_links.values()):
            raise HTTPException(409, "已关联成交的投资卡不能修改证券代码，请先解除关联")
        now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        card = req.card.model_copy(update={"updated_at": now, "confirmed_at": now if req.card.status == "已确认" else ""})
        state.cards = [card] + [c for c in state.cards if c.id != card.id]
    return mutate(req.revision, update)


@router.post("/delete/{card_id}")
def delete_card(card_id: str, req: RevisionRequest):
    def remove(state):
        if not any(c.id == card_id for c in state.cards):
            raise HTTPException(404, "记录不存在")
        if any(link.card_id == card_id for link in state.trade_links.values()):
            raise HTTPException(409, "投资卡已关联成交，请先在成交与复盘中解除关联")
        state.cards = [c for c in state.cards if c.id != card_id]
    return mutate(req.revision, remove)


@router.post("/restore")
def restore(req: RestoreRequest):
    def replace(state):
        state.cards = req.snapshot.cards
        state.trade_links = req.snapshot.trade_links
        state.reviews = req.snapshot.reviews
    return mutate(req.revision, replace)
