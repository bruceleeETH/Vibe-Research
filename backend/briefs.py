"""Read-only HTTP view of the local brief archive; auth is inherited from app."""
from fastapi import APIRouter, HTTPException
from brief_store import BriefError, day_view

router = APIRouter(prefix='/api/workbench/briefs', tags=['briefs'])


@router.get('')
def briefs(date: str | None = None):
    try:
        return day_view(date)
    except BriefError as exc:
        raise HTTPException(422 if '日期' in str(exc) else 500, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, '简报归档无法读取，请检查本地目录权限') from exc
