from fastapi import APIRouter, Body, Request
from fastapi.responses import Response
from app.errors import BusinessError
from app.web_comp import render_comp
from . import store
from .archive import serialize_comp
from .constants import DB_PATH
from .engine import evaluate_comp

router = APIRouter()


def _db(request=None):
    return getattr(request.app.state, 'comp_db_path', None) or DB_PATH


@router.get('/compensation')
def page(request: Request):
    return render_comp(request, 'compensation')


@router.get('/comp-intake')
def intake_page(request: Request):
    return render_comp(request, 'comp_intake')


@router.get('/comp-seals')
def seals_page(request: Request):
    return render_comp(request, 'comp_seals')


@router.post('/api/comp/runs')
def create(request: Request, payload: dict = Body(default={})):
    path = _db(request)
    # 先读历史台账，保证本次垫付会扣除其他批次已占用的同一笔保证金。
    result = evaluate_comp(payload, prior_claims=store.prior_claims(path))
    return store.save_run(path, result)


@router.post('/api/comp/runs/{run_id}/rerun')
def rerun(request: Request, run_id: str):
    path = _db(request)
    previous = store.get_run(path, run_id)
    if 'input_snapshot' not in previous:
        raise BusinessError('INPUT_SNAPSHOT_MISSING', '旧批缺少源快照，请重新导入')
    result = evaluate_comp({'snapshot': previous['input_snapshot'],
                            'dataset': previous['manifest']['source']},
                           prior_claims=store.prior_claims(path))
    if result['manifest']['run_id'] != run_id:
        raise BusinessError('DIGEST_CHANGED', '快照重跑摘要不一致，已拒绝')
    return store.save_run(path, result)


@router.get('/api/comp/runs')
def runs(request: Request):
    return store.history(_db(request))


@router.get('/api/comp/runs/{run_id}')
def run(request: Request, run_id: str):
    return store.get_run(_db(request), run_id)


@router.post('/api/comp/runs/{run_id}/review')
def review(request: Request, run_id: str, payload: dict = Body(...)):
    revision = payload.get('revision')
    if not isinstance(revision, int) or revision < 1:
        raise BusinessError('BAD_REVISION', '版本号须为正整数')
    return store.review(_db(request), run_id, revision)


@router.post('/api/comp/runs/{run_id}/publish')
def publish(request: Request, run_id: str):
    return store.publish_seal(_db(request), run_id)


@router.post('/api/comp/seals/{seal_id}/rollback')
def rollback(request: Request, seal_id: str):
    return store.rollback_seal(_db(request), seal_id)


@router.get('/api/comp/seals')
def seals(request: Request):
    return {'active': store.get_active_seal(_db(request)), 'seals': store.list_seals(_db(request))}


@router.get('/api/comp/export/{run_id}')
def export(request: Request, run_id: str):
    path = _db(request)
    result = store.get_run(path, run_id)
    seal = store.seal_for_run(path, run_id)
    return Response(serialize_comp(result, seal), media_type='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="{run_id}.zip"'})
