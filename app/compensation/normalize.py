from decimal import Decimal
from app.coerce import number, money, instant
from app.errors import BusinessError

def _guard(state, table, row, fn):
    try:
        return fn()
    except BusinessError as error:
        state['quarantine'].append({'table': table, 'line': row.get('_line', 0),
            'id': row.get('ticket', row.get('refund_id', row.get('deposit_id', ''))),
            'code': error.code, 'detail': error.message,
            'raw': {k: v for k, v in row.items() if not k.startswith('_')}})
        return None

def normalize_tickets(state, rows):
    out = []
    for row in rows:
        def parse():
            ticket = row['ticket'].strip()
            seller = row['seller_id'].strip()
            buyer = row['buyer_id'].strip()
            if not ticket or not seller or not buyer:
                raise BusinessError('UNKNOWN_REFERENCE', '票号、卖家或买家缺失')
            payable = number(row['payable'])
            if payable < 0:
                raise BusinessError('INVALID_RANGE', '应付金额不能为负')
            instant(row['deal_time'])
            instant(row['complete_time'])
            return {'ticket': ticket, 'seller_id': seller, 'buyer_id': buyer,
                    'payable': money(payable), 'deal_time': row['deal_time'].strip(),
                    'complete_time': row['complete_time'].strip(), '_line': row['_line']}
        kept = _guard(state, 'tickets', row, parse)
        if kept:
            out.append(kept)
    return out

def normalize_refunds(state, rows):
    out = []
    for row in rows:
        def parse():
            rid = row['refund_id'].strip()
            ticket = row['ticket'].strip()
            if not rid or not ticket:
                raise BusinessError('UNKNOWN_REFERENCE', '退款单号或票号缺失')
            amount = number(row['refund_amount'])
            if amount < 0:
                raise BusinessError('INVALID_RANGE', '退款金额不能为负')
            instant(row['refund_time'])
            return {'refund_id': rid, 'ticket': ticket,
                    'buyer_id': row['buyer_id'].strip(), 'refund_amount': money(amount),
                    'refund_time': row['refund_time'].strip(), '_line': row['_line']}
        kept = _guard(state, 'refunds', row, parse)
        if kept:
            out.append(kept)
    return out

def normalize_deposits(state, rows):
    out = []
    for row in rows:
        def parse():
            did = row['deposit_id'].strip()
            buyer = row['buyer_id'].strip()
            if not did or not buyer:
                raise BusinessError('UNKNOWN_REFERENCE', '保证金编号或买家缺失')
            amount = number(row['amount'])
            if amount <= 0:
                raise BusinessError('INVALID_RANGE', '保证金金额必须为正')
            instant(row['paid_at'])
            return {'deposit_id': did, 'buyer_id': buyer, 'amount': money(amount),
                    'paid_at': row['paid_at'].strip(), '_line': row['_line']}
        kept = _guard(state, 'deposits', row, parse)
        if kept:
            out.append(kept)
    return out

def dedupe(state, table, key, rows, conflict_code, detail):
    """同键去重：完全同值只保留一条；同键不同值全部隔离。返回保留行。"""
    grouped = {}
    for row in rows:
        grouped.setdefault(row[key], []).append(row)
    kept = []
    for ident, items in grouped.items():
        signatures = {tuple((k, v) for k, v in r.items() if not k.startswith('_')) for r in items}
        if len(signatures) > 1:
            for row in items:
                state['quarantine'].append({'table': table, 'line': row.get('_line', 0),
                    'id': ident, 'code': conflict_code, 'detail': detail,
                    'raw': {k: v for k, v in row.items() if not k.startswith('_')}})
        else:
            kept.append(items[0])
    kept.sort(key=lambda r: r['_line'])
    return kept
