"""可复用主板历史行情库的只读 FastAPI 路由。"""
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from market_store import MarketStore


router = APIRouter(prefix="/api/market-store", tags=["market-store"])


def store() -> MarketStore:
    """按请求解析 VR_DATA_DIR，便于测试和本地覆盖数据根。"""
    return MarketStore()


@router.get("/status")
def status():
    return store().status()


@router.get("/dates")
def dates(revision: int | None = Query(None, ge=1)):
    try:
        return {"revision": revision, "dates": store().dates(revision)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/universe")
def universe(
    revision: int | None = Query(None, ge=1),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    eligible_only: bool = True,
):
    try:
        return store().universe(revision, limit, offset, eligible_only)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/bars")
def bars(
    codes: str,
    start: str,
    end: str,
    revision: int | None = Query(None, ge=1),
):
    items = [item.strip() for item in codes.split(",") if item.strip()]
    if not items or len(items) > 50 or any(not re.fullmatch(r"\d{6}", item) for item in items):
        raise HTTPException(400, "codes 需为 1–50 个逗号分隔的六位证券代码")
    try:
        start_day = date.fromisoformat(start)
        end_day = date.fromisoformat(end)
        if start_day > end_day:
            raise ValueError("start 不能晚于 end")
        rows = store().bars(items, start_day.isoformat(), end_day.isoformat(), revision)
        return {"revision": revision, "codes": items, "start": start, "end": end, "rows": rows}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
