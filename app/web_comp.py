from fastapi import Request
from fastapi.templating import Jinja2Templates
from app.config import ROOT, META
from .compensation import store
from .compensation.constants import DB_PATH

templates = Jinja2Templates(directory=str(ROOT / 'app/templates'))

COMP_META = {
    'title': '东港水产 · 保证金代偿',
    'nav_keys': ['comp-intake', 'compensation', 'comp-seals'],
    'nav_modules': ['证据导入', '代偿核对', '封存切换'],
    'page_titles': {'comp_intake': '证据导入', 'compensation': '代偿核对', 'comp_seals': '封存切换'},
    'labels': {
        'ticket': '票号', 'seller_id': '卖家', 'buyer_id': '买家',
        'refund_id': '退款单号', 'payable': '应付 CNY', 'advanced': '实际垫付 CNY',
        'seller_due': '卖家待补 CNY', 'buyer_debt': '买家欠款 CNY',
        'status': '状态', 'complete_time': '证据齐全时间', 'refund_time': '撤单时间',
        'deposit_id': '保证金编号', 'amount': '缴存 CNY', 'prior_used': '历史占用 CNY',
        'this_run_used': '本批占用 CNY', 'remaining': '可用余额 CNY',
        'code': '原因码', 'detail': '原因', 'line': '行号', 'table': '证据表',
        'seal_id': '封存号', 'seal_digest': '封存摘要', 'active': '生效',
        'created_at': '封存时间', 'superseded_by': '被替代为', 'sources': '资金来源',
    },
}


def render_comp(request: Request, key: str):
    path = getattr(request.app.state, 'comp_db_path', None) or DB_PATH
    run_id = request.query_params.get('run_id')
    if run_id:
        state = store.get_run(path, run_id)
    else:
        state = store.save_run(path, _default_state(path))
    active = store.get_active_seal(path)
    seal_rows = store.list_seals(path)
    return templates.TemplateResponse(request=request, name=f'{key}.html', context={
        'meta': META, 'cmeta': COMP_META, 'key': key, 'state': state,
        'active_seal': active, 'seal_rows': seal_rows})


def _default_state(path):
    from .compensation.engine import evaluate_comp
    return evaluate_comp({'dataset': 'dirty'}, prior_claims=store.prior_claims(path))
