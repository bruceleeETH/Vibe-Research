"""Archive view and local-only manual dispatch; auth is inherited from app."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from urllib.parse import urlsplit
import brief_manual_sync as manual
from brief_store import BriefError, day_view

router = APIRouter(prefix='/api/workbench/briefs', tags=['briefs'])


@router.get('/sync')
def sync_status():
    try:
        return manual.status()
    except (BriefError, OSError) as exc:
        raise HTTPException(500, '无法读取手动同步状态，归档未被修改') from exc


@router.post('/sync', status_code=202)
def sync_briefs(request: Request, background: BackgroundTasks):
    local = {'127.0.0.1', 'localhost', '::1'}
    origin = request.headers.get('origin')
    if (request.url.hostname not in local or not request.client or request.client.host not in local
            or request.headers.get('x-brief-sync') != 'manual'
            or (origin and (urlsplit(origin).scheme not in {'http', 'https'} or urlsplit(origin).hostname not in local))):
        raise HTTPException(403, '手动同步仅允许从本机工作台发起')
    try:
        job, created = manual.request_sync()
        if created:
            background.add_task(manual.dispatch, job['id'])
        return {'available': True, 'job': job}
    except (BriefError, OSError) as exc:
        raise HTTPException(503, str(exc) if isinstance(exc, BriefError) else '无法保存同步请求') from exc


@router.get('')
def briefs(date: str | None = None):
    try:
        return day_view(date)
    except BriefError as exc:
        raise HTTPException(422 if '日期' in str(exc) else 500, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, '简报归档无法读取，请检查本地目录权限') from exc
