import base64, hashlib, json, time
from datetime import datetime, timezone
from pathlib import Path
from app.errors import BusinessError
from .constants import COMP_RULE_VERSION, COMP_TABLES, MAX_BYTES
from .reader import read_table
from .rules import TICKET_FIELDS, REFUND_FIELDS, DEPOSIT_FIELDS, ALIASES, run_compensation

ROOT = Path(__file__).resolve().parents[2]
FIELDS = {'tickets': TICKET_FIELDS, 'refunds': REFUND_FIELDS, 'deposits': DEPOSIT_FIELDS}


def _load_tables(payload, snapshot):
    if snapshot is not None:
        return {t: base64.b64decode(snapshot[t], validate=True) for t in COMP_TABLES}
    if 'tables' in payload:
        tables = payload['tables']
        if not isinstance(tables, dict):
            raise BusinessError('BAD_TABLES', 'tables 须为对象')
        dataset = payload.get('dataset', 'dirty')
        if dataset not in {'dirty', 'clean', 'legacy'}:
            raise BusinessError('BAD_DATASET', '样例名称无效')
        # 未粘贴的表回退到所选样例，保证三证齐备。
        base = {t: (ROOT / 'sample_data' / f'comp_{dataset}_{t}.csv').read_bytes() for t in COMP_TABLES}
        for t, text in tables.items():
            if t not in COMP_TABLES:
                raise BusinessError('BAD_TABLES', f'未知证据表 {t}')
            base[t] = str(text).encode()
        return base
    dataset = payload.get('dataset', 'dirty')
    if dataset not in {'dirty', 'clean', 'legacy'}:
        raise BusinessError('BAD_DATASET', '样例名称无效')
    return {t: (ROOT / 'sample_data' / f'comp_{dataset}_{t}.csv').read_bytes() for t in COMP_TABLES}


def evaluate_comp(payload=None, prior_claims=None):
    """纯计算：读取三证 → 隔离待处理 → 保证金 FIFO 代偿 → 守恒校验。不写任何台账。"""
    payload = payload or {}
    raw = _load_tables(payload, payload.get('snapshot'))
    if any(len(b) > MAX_BYTES for b in raw.values()):
        raise BusinessError('TOO_LARGE', '单张证据超过2MB', 413)
    start = time.perf_counter()
    source = 'custom' if 'tables' in payload else payload.get('dataset', 'dirty')
    state = {'raw_bytes': raw, 'raw': dict(raw), 'counts': {}, 'encodings': {},
             'quarantine': [], 'pending': [], 'allocations': [], 'source': source}
    if 'snapshot' in payload:
        state['source'] = payload.get('dataset', 'custom')
    for table in COMP_TABLES:
        state['raw'][table] = read_table(raw[table], FIELDS[table], ALIASES, state, table)
    digest = hashlib.sha256(
        b''.join(raw[t] for t in COMP_TABLES) + COMP_RULE_VERSION.encode()).hexdigest()
    run_id = 'mc-' + digest[:16]
    state['manifest'] = {'run_id': run_id, 'sha256': digest, 'rule_version': COMP_RULE_VERSION,
                         'source': state['source'],
                         'generated_at': datetime.now(timezone.utc).isoformat(),
                         'elapsed_ms': round((time.perf_counter() - start) * 1000, 3),
                         'timezone': 'Asia/Shanghai'}
    run_compensation(state, run_id, prior_claims)
    # 原始成交与付款证据整字节封存，重跑从同一不可变快照恢复。
    state['input_snapshot'] = {t: base64.b64encode(raw[t]).decode() for t in COMP_TABLES}
    state.pop('raw_bytes', None)
    state.pop('raw', None)
    return state
