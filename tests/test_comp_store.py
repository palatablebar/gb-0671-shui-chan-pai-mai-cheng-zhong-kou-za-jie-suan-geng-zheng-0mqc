import sqlite3
import pytest
from app.compensation import store
from app.compensation.engine import evaluate_comp
from app.errors import BusinessError

def _save(db, payload):
    return store.save_run(db, evaluate_comp(payload, prior_claims=store.prior_claims(db)))


def test_save_idempotent_same_run(comp_db, comp_clean):
    first = store.save_run(comp_db, comp_clean)
    second = store.save_run(comp_db, evaluate_comp({'dataset': 'clean'}, prior_claims=store.prior_claims(comp_db)))
    assert first['manifest']['run_id'] == second['manifest']['run_id']
    con = sqlite3.connect(comp_db)
    assert con.execute('SELECT COUNT(*) FROM comp_runs').fetchone()[0] == 1


def test_rerun_does_not_reuse_margin_twice(comp_db):
    run = _save(comp_db, {'dataset': 'clean'})
    con = sqlite3.connect(comp_db)
    before = con.execute('SELECT COUNT(*) FROM comp_claims').fetchone()[0]
    assert before == 7  # 6 张票，其中 T1002 跨两笔保证金，共 7 条占用明细
    # API 重跑：内存重算会再次得到 8 条占用，但 DB 唯一约束 (run_id,deposit_id,ticket)
    # 通过 INSERT OR IGNORE 拦截，台账行数与合计不变。
    rerun = evaluate_comp({'snapshot': run['input_snapshot'], 'dataset': 'clean'},
                          prior_claims=store.prior_claims(comp_db))
    assert len(rerun['allocations']) == 7
    store.save_run(comp_db, rerun)
    after = con.execute('SELECT COUNT(*) FROM comp_claims').fetchone()[0]
    assert before == after
    total = con.execute('SELECT SUM(CAST(amount AS REAL)) FROM comp_claims').fetchone()[0]
    assert round(total, 2) == 3800.00
    assert rerun['comp_summary']['advanced'] == run['comp_summary']['advanced']
    assert all(rerun['conservation'].values())


def test_cross_run_shared_deposit_shortfall(comp_db):
    _save(comp_db, {'dataset': 'clean'})  # 已占用 D7001 全部 900、D7002 400 等
    second = _save(comp_db, {'dataset': 'legacy'})  # 不同保证金编号，互不影响
    assert second['sealable'] is True
    # 构造复用 D7001/D7002 编号的新批次：历史占用必须被扣除。
    tickets = "ticket,seller_id,buyer_id,payable,deal_time,complete_time\n" \
              "T9101,S91,B01,900.00,2026-11-21T09:00:00+08:00,2026-11-21T09:30:00+08:00\n"
    refunds = "refund_id,ticket,buyer_id,refund_amount,refund_time\n" \
              "R9101,T9101,B01,900.00,2026-11-21T10:00:00+08:00\n"
    deposits = "deposit_id,buyer_id,amount,paid_at\n" \
               "D7001,B01,900.00,2026-11-20T18:00:00+08:00\n" \
               "D7002,B01,600.00,2026-11-20T18:05:00+08:00\n"
    reused = _save(comp_db, {'tables': {'tickets': tickets, 'refunds': refunds, 'deposits': deposits}})
    row = reused['compensation'][0]
    # D7001 已被历史批次用光，D7002 仅剩 200 → 只能垫付 200，缺口 700。
    assert row['advanced'] == '200.00'
    assert row['seller_due'] == '700.00'
    assert any(p['code'] == 'MARGIN_SHORTFALL' for p in reused['pending'])


def test_publish_blocked_when_pending(comp_db, comp_dirty):
    saved = store.save_run(comp_db, comp_dirty)
    with pytest.raises(BusinessError) as exc:
        store.publish_seal(comp_db, saved['manifest']['run_id'])
    assert exc.value.code == 'BLOCKED_PENDING'
    assert store.get_active_seal(comp_db) is None


def test_publish_switch_and_rollback(comp_db):
    clean = _save(comp_db, {'dataset': 'clean'})
    seal1 = store.publish_seal(comp_db, clean['manifest']['run_id'])
    legacy = _save(comp_db, {'dataset': 'legacy'})
    seal2 = store.publish_seal(comp_db, legacy['manifest']['run_id'])
    assert store.get_active_seal(comp_db)['seal_id'] == seal2['seal_id']
    restored = store.rollback_seal(comp_db, seal1['seal_id'])
    assert restored['seal_id'] == seal1['seal_id'] and restored['active'] == 1
    seals = {s['seal_id']: s for s in store.list_seals(comp_db)}
    assert seals[seal1['seal_id']]['active'] == 1
    assert seals[seal2['seal_id']]['active'] == 0


def test_failed_switch_keeps_old_version(comp_db, monkeypatch):
    clean = _save(comp_db, {'dataset': 'clean'})
    seal1 = store.publish_seal(comp_db, clean['manifest']['run_id'])
    legacy = _save(comp_db, {'dataset': 'legacy'})

    import app.compensation.store as mod
    real_connect = mod.connect

    class FailingConnection:
        """代理连接：封存切换的最终 UPDATE 主动失败，验证事务回滚。"""
        def __init__(self, con):
            self._con = con

        def execute(self, sql, params=()):
            if sql.startswith('UPDATE comp_seals SET active=1'):
                raise sqlite3.Error('切换失败注入')
            return self._con.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self._con, name)

        def __enter__(self):
            self._con.__enter__()
            return self

        def __exit__(self, *exc):
            return self._con.__exit__(*exc)

    def patched(path):
        return FailingConnection(real_connect(path))
    monkeypatch.setattr(mod, 'connect', patched)
    with pytest.raises(BusinessError) as exc:
        store.publish_seal(comp_db, legacy['manifest']['run_id'])
    assert exc.value.code == 'ACTIVE_SEAL_LOCKED'
    monkeypatch.setattr(mod, 'connect', real_connect)
    assert store.get_active_seal(comp_db)['seal_id'] == seal1['seal_id']


def test_rollback_unknown_seal(comp_db):
    with pytest.raises(BusinessError) as exc:
        store.rollback_seal(comp_db, 'seal-nope')
    assert exc.value.code == 'SEAL_NOT_FOUND' and exc.value.status == 404


def test_review_optimistic_lock(comp_db):
    run = _save(comp_db, {'dataset': 'clean'})
    rid = run['manifest']['run_id']
    assert store.review(comp_db, rid, 1)['revision'] == 2
    with pytest.raises(BusinessError) as exc:
        store.review(comp_db, rid, 1)
    assert exc.value.code == 'STALE_VERSION' and exc.value.status == 409


def test_get_missing_run(comp_db):
    with pytest.raises(BusinessError) as exc:
        store.get_run(comp_db, 'mc-0000000000000000')
    assert exc.value.status == 404


def test_seal_check_blocks_ledger_overrun(comp_db, monkeypatch):
    # 纵深防御：即便绕过资金池直接污染台账导致超占，封存检查也必须拒绝切换。
    run = _save(comp_db, {'dataset': 'clean'})
    with store.connect(comp_db) as con:
        con.execute("INSERT INTO comp_claims(run_id,deposit_id,ticket,amount) VALUES(?,?,?,?)",
                    (run['manifest']['run_id'], 'D7001', 'T-FORGE', '99999.00'))
    with pytest.raises(BusinessError) as exc:
        store.publish_seal(comp_db, run['manifest']['run_id'])
    assert exc.value.code == 'MARGIN_DOUBLE_SPEND' and exc.value.status == 409
    assert store.get_active_seal(comp_db) is None
