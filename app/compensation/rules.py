from collections import defaultdict
from decimal import Decimal
from app.coerce import money
from .normalize import normalize_tickets, normalize_refunds, normalize_deposits, dedupe

TICKET_FIELDS = ['ticket', 'seller_id', 'buyer_id', 'payable', 'deal_time', 'complete_time']
REFUND_FIELDS = ['refund_id', 'ticket', 'buyer_id', 'refund_amount', 'refund_time']
DEPOSIT_FIELDS = ['deposit_id', 'buyer_id', 'amount', 'paid_at']
ALIASES = {'票号': 'ticket', '卖家': 'seller_id', '买家': 'buyer_id', '应付金额': 'payable',
           '成交时间': 'deal_time', '证据齐全时间': 'complete_time', '退款单号': 'refund_id',
           '退款金额': 'refund_amount', '撤单时间': 'refund_time', '保证金编号': 'deposit_id',
           '保证金金额': 'amount', '缴存时间': 'paid_at'}

def _pend(state, code, detail, table, line, ident, raw):
    state['pending'].append({'code': code, 'detail': detail, 'table': table,
                             'line': line, 'id': ident, 'raw': raw})


def _pair_refunds(state, tickets, refunds):
    """退款与成交票逐张对账：无法对应、买家不一致、金额不符的一律保留待处理。"""
    by_ticket = {t['ticket']: t for t in tickets}
    seen_refund, seen_ticket = set(), set()
    matched = []
    for refund in sorted(refunds, key=lambda r: (r['_line'], r['refund_id'])):
        rid = refund['refund_id']
        raw = {k: v for k, v in refund.items() if not k.startswith('_')}
        if rid in seen_refund:
            _pend(state, 'REFUND_DUPLICATE', f'退款单 {rid} 同一撤单重复到达',
                  'refunds', refund['_line'], rid, raw)
            continue
        seen_refund.add(rid)
        ticket = by_ticket.get(refund['ticket'])
        if ticket is None:
            _pend(state, 'REFUND_UNMATCHED', f"退款票 {refund['ticket']} 无对应成交票",
                  'refunds', refund['_line'], rid, raw)
            continue
        if refund['ticket'] in seen_ticket:
            _pend(state, 'REFUND_DUPLICATE', f"票 {refund['ticket']} 存在多笔撤单",
                  'refunds', refund['_line'], rid, raw)
            continue
        if refund['buyer_id'] and refund['buyer_id'] != ticket['buyer_id']:
            _pend(state, 'REFUND_BUYER_MISMATCH',
                  f"退款买家 {refund['buyer_id']} 与成交票买家 {ticket['buyer_id']} 不一致",
                  'refunds', refund['_line'], rid, raw)
            continue
        if Decimal(refund['refund_amount']) != Decimal(ticket['payable']):
            _pend(state, 'REFUND_AMOUNT_MISMATCH',
                  f"退款 {refund['refund_amount']} 与应付 {ticket['payable']} 不符",
                  'refunds', refund['_line'], rid, raw)
            continue
        seen_ticket.add(refund['ticket'])
        matched.append((ticket, refund))
    return matched


def _buyer_pools(deposits, prior_claims):
    """每买家的保证金资金池，扣除历史批次已占用金额（重跑不得重复使用同一笔保证金）。"""
    pools = defaultdict(list)
    for d in deposits:
        used = prior_claims.get(d['deposit_id'], Decimal('0'))
        remaining = Decimal(d['amount']) - used
        pools[d['buyer_id']].append({'deposit_id': d['deposit_id'], 'amount': Decimal(d['amount']),
                                     'remaining': remaining})
    for buyer in pools:
        pools[buyer].sort(key=lambda p: p['deposit_id'])
    return pools


def _allocate(ticket, refund, pool, state, run_id, known):
    """按 FIFO 从该买家资金池垫付一张票，记录每张保证金的占用明细。"""
    need = Decimal(ticket['payable'])
    sources, take = [], Decimal('0')
    for part in pool:
        if take >= need:
            break
        grab = min(part['remaining'], need - take)
        if grab > 0:
            part['remaining'] -= grab
            take += grab
            sources.append({'deposit_id': part['deposit_id'], 'amount': money(grab)})
            key = (run_id, part['deposit_id'], ticket['ticket'])
            if key not in known:
                state['allocations'].append({'run_id': run_id, 'deposit_id': part['deposit_id'],
                                             'ticket': ticket['ticket'], 'amount': money(grab)})
                known.add(key)
    shortfall = need - take
    if shortfall > 0:
        _pend(state, 'MARGIN_SHORTFALL',
              f"买家 {ticket['buyer_id']} 保证金缺口 {money(shortfall)}，票 {ticket['ticket']} 未足额覆盖",
              'tickets', ticket['_line'], ticket['ticket'],
              {'ticket': ticket['ticket'], 'payable': ticket['payable'],
               'advanced': money(take), 'shortfall': money(shortfall)})
    return {
        'ticket': ticket['ticket'], 'seller_id': ticket['seller_id'], 'buyer_id': ticket['buyer_id'],
        'refund_id': refund['refund_id'], 'payable': ticket['payable'],
        'advanced': money(take), 'seller_due': money(shortfall),
        'buyer_debt': money(shortfall), 'sources': sources,
        'complete_time': ticket['complete_time'], 'refund_time': refund['refund_time'],
        'status': '足额垫付' if shortfall == 0 else '保证金不足',
    }


def run_compensation(state, run_id, prior_claims=None):
    # prior_claims: {(run_id, deposit_id): 占用金额}。仅“其他批次”的占用扣除资金池，
    # 本批历史占用用于重跑去重，不能当作外部占用，否则同一笔保证金被扣两次。
    prior_claims = prior_claims or {}
    state.setdefault('pending', [])
    state.setdefault('allocations', [])
    other_claims = defaultdict(Decimal)
    for (claimed_run, deposit_id), amount in prior_claims.items():
        if claimed_run != run_id:
            other_claims[deposit_id] += Decimal(amount)
    other_claims = dict(other_claims)
    known = {(a['run_id'], a['deposit_id'], a['ticket']) for a in state['allocations']}
    tickets = dedupe(state, 'tickets', 'ticket',
                     normalize_tickets(state, state['raw']['tickets']),
                     'TICKET_CONFLICT', '同一票号存在不同成交原值')
    refunds = normalize_refunds(state, state['raw']['refunds'])
    deposits = dedupe(state, 'deposits', 'deposit_id',
                      normalize_deposits(state, state['raw']['deposits']),
                      'MARGIN_CONFLICT', '同一保证金编号存在不同原值')
    matched = _pair_refunds(state, tickets, refunds)
    # 先核对完（证据齐全时间早）的票先拿款，让部分卖家赶上日结。
    matched.sort(key=lambda pair: (pair[0]['complete_time'], pair[0]['deal_time'], pair[0]['ticket']))
    pools = _buyer_pools(deposits, other_claims)
    rows = []
    for ticket, refund in matched:
        pool = pools.get(ticket['buyer_id'])
        if pool is None:
            pool = []
            _pend(state, 'MARGIN_SHORTFALL',
                  f"买家 {ticket['buyer_id']} 无任何缴存保证金，票 {ticket['ticket']} 未覆盖",
                  'tickets', ticket['_line'], ticket['ticket'],
                  {'ticket': ticket['ticket'], 'payable': ticket['payable'],
                   'advanced': '0.00', 'shortfall': ticket['payable']})
        rows.append(_allocate(ticket, refund, pool, state, run_id, known))
    state['compensation'] = rows
    state['deposit_ledger'] = _ledger(deposits, pools, other_claims, state['allocations'], run_id)
    state['comp_summary'] = _summary(rows, state['pending'], deposits)
    state['conservation'] = _conservation(state, rows, other_claims)
    state['sealable'] = not state['pending']
    return state


def _ledger(deposits, pools, prior_claims, allocations, run_id):
    pool_map = {p['deposit_id']: p for buyer in pools for p in pools[buyer]}
    this_run = defaultdict(Decimal)
    for a in allocations:
        if a['run_id'] == run_id:
            this_run[a['deposit_id']] += Decimal(a['amount'])
    out = []
    for d in deposits:
        part = pool_map.get(d['deposit_id'])
        prior = prior_claims.get(d['deposit_id'], Decimal('0'))
        current = this_run.get(d['deposit_id'], Decimal('0'))
        remaining = Decimal(d['amount']) - prior - current
        out.append({'deposit_id': d['deposit_id'], 'buyer_id': d['buyer_id'],
                    'amount': d['amount'], 'prior_used': money(prior),
                    'this_run_used': money(current), 'remaining': money(remaining)})
    return sorted(out, key=lambda r: r['deposit_id'])


def _summary(rows, pending, deposits):
    payable = sum((Decimal(r['payable']) for r in rows), Decimal('0'))
    advanced = sum((Decimal(r['advanced']) for r in rows), Decimal('0'))
    seller_due = sum((Decimal(r['seller_due']) for r in rows), Decimal('0'))
    buyer_debt = sum((Decimal(r['buyer_debt']) for r in rows), Decimal('0'))
    deposit_total = sum((Decimal(d['amount']) for d in deposits), Decimal('0'))
    return {'affected_tickets': len(rows), 'payable': money(payable),
            'advanced': money(advanced), 'seller_due': money(seller_due),
            'buyer_debt': money(buyer_debt), 'deposit_total': money(deposit_total),
            'pending': len(pending),
            'fully_funded': sum(1 for r in rows if r['status'] == '足额垫付'),
            'shortfall_tickets': sum(1 for r in rows if r['status'] == '保证金不足')}


def _conservation(state, rows, prior_claims):
    """资金与台账守恒：垫付合计=保证金占用合计；应付=垫付+卖家待补；买家欠款=卖家待补。"""
    payable = sum((Decimal(r['payable']) for r in rows), Decimal('0'))
    advanced = sum((Decimal(r['advanced']) for r in rows), Decimal('0'))
    seller_due = sum((Decimal(r['seller_due']) for r in rows), Decimal('0'))
    buyer_debt = sum((Decimal(r['buyer_debt']) for r in rows), Decimal('0'))
    allocated = sum((Decimal(a['amount']) for a in state['allocations']
                     if a['run_id'] == state['manifest']['run_id']), Decimal('0'))
    ledger_balanced = all(Decimal(d['amount']) == Decimal(d['prior_used'])
                          + Decimal(d['this_run_used']) + Decimal(d['remaining'])
                          for d in state['deposit_ledger'])
    return {
        'payable_equals_parts': payable == advanced + seller_due,
        'advance_equals_ledger': advanced == allocated,
        'debt_equals_seller_due': buyer_debt == seller_due,
        'ledger_balanced': ledger_balanced,
        'no_negative_remaining': all(Decimal(d['remaining']) >= 0 for d in state['deposit_ledger']),
    }
