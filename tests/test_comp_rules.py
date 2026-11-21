from decimal import Decimal
from app.compensation.engine import evaluate_comp


def test_clean_sealable_and_four_accounts(comp_clean):
    s = comp_clean
    assert s['sealable'] is True
    assert s['pending'] == []
    assert s['comp_summary']['affected_tickets'] == 6
    assert s['comp_summary']['payable'] == '3800.00'
    assert s['comp_summary']['advanced'] == '3800.00'
    assert s['comp_summary']['seller_due'] == '0.00'
    assert s['comp_summary']['buyer_debt'] == '0.00'
    for row in s['compensation']:
        assert Decimal(row['payable']) == Decimal(row['advanced']) + Decimal(row['seller_due'])
        assert row['buyer_debt'] == row['seller_due']
        assert row['sources']


def test_evidence_completion_order_first(comp_clean):
    # 先核对完（complete_time 早）的票排在前面先拿款。
    tickets = [r['ticket'] for r in comp_clean['compensation']]
    assert tickets.index('T1003') < tickets.index('T1002')
    assert tickets.index('T1005') < tickets.index('T1006')


def test_fifo_deposit_spanning(comp_clean):
    # B01 两票合计 1300，D7001=900 先被 T1001 用 800，T1002 先吃光 D7001 余 100 再从 D7002 拿 400。
    t1002 = next(r for r in comp_clean['compensation'] if r['ticket'] == 'T1002')
    assert [x['deposit_id'] for x in t1002['sources']] == ['D7001', 'D7002']
    assert [x['amount'] for x in t1002['sources']] == ['100.00', '400.00']
    ledger = {d['deposit_id']: d for d in comp_clean['deposit_ledger']}
    assert ledger['D7001']['this_run_used'] == '900.00'
    assert ledger['D7002']['remaining'] == '200.00'


def test_conservation_invariants(comp_clean, comp_dirty, comp_legacy):
    for s in (comp_clean, comp_dirty, comp_legacy):
        assert all(s['conservation'].values()), s['conservation']


def test_dirty_pending_categories(comp_dirty):
    codes = {p['code'] for p in comp_dirty['pending']}
    assert {'REFUND_UNMATCHED', 'REFUND_DUPLICATE', 'MARGIN_SHORTFALL'} <= codes
    assert comp_dirty['sealable'] is False


def test_dirty_duplicate_refund_held(comp_dirty):
    # 同一撤单 R8008 重复到达：仅保留一次有效匹配，重复进待处理。
    dupes = [p for p in comp_dirty['pending'] if p['id'] == 'R8008']
    assert len(dupes) == 1 and dupes[0]['code'] == 'REFUND_DUPLICATE'
    matched = [r for r in comp_dirty['compensation'] if r['ticket'] == 'T2008']
    assert len(matched) == 1


def test_dirty_unmatched_refund_held(comp_dirty):
    p = [x for x in comp_dirty['pending'] if x['id'] == 'R8009']
    assert len(p) == 1 and p[0]['code'] == 'REFUND_UNMATCHED'
    assert all(r['ticket'] != 'T2999' for r in comp_dirty['compensation'])


def test_dirty_margin_shortfall_split(comp_dirty):
    # B01 保证金 900：T2001 先拿 800，T2002 应付 500 只能垫付 100，卖家待补 400。
    t2002 = next(r for r in comp_dirty['compensation'] if r['ticket'] == 'T2002')
    assert t2002['advanced'] == '100.00'
    assert t2002['seller_due'] == '400.00'
    assert t2002['buyer_debt'] == '400.00'
    assert t2002['status'] == '保证金不足'


def test_dirty_buyer_without_deposit(comp_dirty):
    # B04 缴存 500 应付 740：垫付 500、待补 240；T2007 排在最后时 B01 已无余额。
    t2006 = next(r for r in comp_dirty['compensation'] if r['ticket'] == 'T2006')
    assert t2006['advanced'] == '500.00' and t2006['seller_due'] == '240.00'
    t2007 = next(r for r in comp_dirty['compensation'] if r['ticket'] == 'T2007')
    assert t2007['advanced'] == '0.00' and t2007['seller_due'] == '400.00'


def test_quarantine_keeps_raw_and_line(comp_dirty):
    codes = {(q['table'], q['code']) for q in comp_dirty['quarantine']}
    assert ('tickets', 'COLUMN_COUNT') in codes
    assert ('tickets', 'TICKET_CONFLICT') in codes
    assert ('deposits', 'MARGIN_CONFLICT') in codes
    for q in comp_dirty['quarantine']:
        assert q['line'] > 0 and q['raw']


def test_legacy_gb18030_chinese_headers(comp_legacy):
    assert comp_legacy['sealable'] is True
    assert comp_legacy['encodings']['tickets'] == 'gb18030'
    assert comp_legacy['comp_summary']['payable'] == '1500.00'
    assert {r['ticket'] for r in comp_legacy['compensation']} == {'T3001', 'T3002'}


def test_snapshot_rerun_same_digest(comp_clean):
    again = evaluate_comp({'snapshot': comp_clean['input_snapshot'], 'dataset': 'clean'})
    assert again['manifest']['run_id'] == comp_clean['manifest']['run_id']
    assert again['manifest']['sha256'] == comp_clean['manifest']['sha256']
    assert again['input_snapshot'] == comp_clean['input_snapshot']


def test_same_input_idempotent_digest(comp_clean):
    other = evaluate_comp({'dataset': 'clean'})
    assert other['manifest']['run_id'] == comp_clean['manifest']['run_id']
