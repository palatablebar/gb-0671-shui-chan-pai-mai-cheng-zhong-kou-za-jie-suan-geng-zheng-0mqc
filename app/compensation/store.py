import json, sqlite3
from pathlib import Path
from app.errors import BusinessError


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA foreign_keys=ON')
    con.execute("""CREATE TABLE IF NOT EXISTS comp_runs(
        id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, result TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT '待复核')""")
    # 不可变保证金台账：同一 run × 保证金 × 票 唯一，重跑天然幂等，杜绝重复使用。
    con.execute("""CREATE TABLE IF NOT EXISTS comp_claims(
        run_id TEXT NOT NULL, deposit_id TEXT NOT NULL, ticket TEXT NOT NULL,
        amount TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY(run_id, deposit_id, ticket))""")
    con.execute("""CREATE TABLE IF NOT EXISTS comp_seals(
        seal_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, seal_digest TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        active INTEGER NOT NULL DEFAULT 0, superseded_by TEXT,
        UNIQUE(run_id, seal_digest))""")
    return con


def prior_claims(path):
    """汇总历史批次对每笔保证金的已占用金额，键为 (run_id, deposit_id)，供引擎区分本批/他批。"""
    with connect(path) as con:
        rows = con.execute(
            'SELECT run_id, deposit_id, SUM(CAST(amount AS REAL)) AS used FROM comp_claims GROUP BY run_id, deposit_id').fetchall()
    return {(r['run_id'], r['deposit_id']): str(r['used'] or 0) for r in rows}


def save_run(path, result):
    """幂等保存：同摘要同 run_id；台账仅在首次插入时占用保证金，重跑不重复占用。"""
    run_id = result['manifest']['run_id']
    payload = json.dumps(result, ensure_ascii=False)
    with connect(path) as con:
        con.execute('INSERT OR IGNORE INTO comp_runs(id,digest,result) VALUES(?,?,?)',
                    (run_id, result['manifest']['sha256'], payload))
        inserted = con.total_changes
        for claim in result['allocations']:
            con.execute('INSERT OR IGNORE INTO comp_claims(run_id,deposit_id,ticket,amount) VALUES(?,?,?,?)',
                        (run_id, claim['deposit_id'], claim['ticket'], claim['amount']))
        row = con.execute('SELECT * FROM comp_runs WHERE id=?', (run_id,)).fetchone()
        claims = con.execute(
            'SELECT deposit_id, SUM(CAST(amount AS REAL)) AS used FROM comp_claims GROUP BY deposit_id').fetchall()
    if not row:
        raise BusinessError('NOT_FOUND', '代偿批次不存在', 404)
    saved = json.loads(row['result'])
    saved.update(revision=row['revision'], status=row['status'], inserted=bool(inserted))
    saved['claims_now'] = {r['deposit_id']: str(r['used'] or 0) for r in claims}
    return saved


def get_run(path, run_id):
    with connect(path) as con:
        row = con.execute('SELECT * FROM comp_runs WHERE id=?', (run_id,)).fetchone()
    if not row:
        raise BusinessError('NOT_FOUND', '代偿批次不存在', 404)
    result = json.loads(row['result'])
    result.update(revision=row['revision'], status=row['status'])
    return result


def history(path):
    with connect(path) as con:
        rows = con.execute(
            """SELECT r.id, r.revision, r.status,
                      COALESCE(s.seal_status,'未封存') AS seal_status
               FROM comp_runs r
               LEFT JOIN (SELECT run_id, CASE WHEN active=1 THEN '生效中' ELSE '已回滚' END AS seal_status
                          FROM comp_seals WHERE active=1) s ON s.run_id=r.id
               ORDER BY r.rowid DESC LIMIT 100""").fetchall()
    return [dict(r) for r in rows]


def review(path, run_id, revision):
    with connect(path) as con:
        cur = con.execute(
            'UPDATE comp_runs SET revision=revision+1,status=? WHERE id=? AND revision=?',
            ('已复核', run_id, revision))
        if cur.rowcount != 1:
            if not con.execute('SELECT 1 FROM comp_runs WHERE id=?', (run_id,)).fetchone():
                raise BusinessError('NOT_FOUND', '代偿批次不存在', 404)
            raise BusinessError('STALE_VERSION', '复核版本已更新，请刷新', 409)
    return get_run(path, run_id)


def _check_funds(path, result):
    """封存前复核：任一笔保证金在全部批次的占用合计不得超过其原始缴存额（双重防护）。"""
    with connect(path) as con:
        claims = con.execute(
            'SELECT deposit_id, SUM(CAST(amount AS REAL)) AS used FROM comp_claims GROUP BY deposit_id').fetchall()
        run_rows = con.execute('SELECT id, result FROM comp_runs').fetchall()
    # 从各批次原始证据重建每笔保证金的缴存额，避免只看当前批次。
    deposit_amounts = {}
    for row in run_rows:
        saved = json.loads(row['result'])
        for d in saved.get('deposit_ledger', []):
            deposit_amounts.setdefault(d['deposit_id'], d['amount'])
    problems = []
    for row in claims:
        total = float(deposit_amounts.get(row['deposit_id'], 0))
        if float(row['used']) > total + 1e-9:
            problems.append(row['deposit_id'])
    if problems:
        raise BusinessError('MARGIN_DOUBLE_SPEND',
                            '保证金已被其他批次占用：' + '、'.join(sorted(problems)), 409)


def publish_seal(path, run_id):
    """封存并切换为生效版本。同一事务内：校验 → 写封存 → 旧版标记回滚，失败整体恢复旧版。"""
    result = get_run(path, run_id)
    if not result.get('sealable'):
        raise BusinessError('BLOCKED_PENDING',
                            f"存在 {len(result.get('pending', []))} 项待处理，不可封存；切换已取消，旧版保持不变", 422)
    _check_funds(path, result)
    seal_digest = result['manifest']['sha256']
    seal_id = 'seal-' + seal_digest[:16]
    with connect(path) as con:
        try:
            con.execute('INSERT OR IGNORE INTO comp_seals(seal_id,run_id,seal_digest) VALUES(?,?,?)',
                        (seal_id, run_id, seal_digest))
            old = con.execute('SELECT seal_id FROM comp_seals WHERE active=1').fetchall()
            con.execute('UPDATE comp_seals SET active=0, superseded_by=? WHERE active=1', (seal_id,))
            cur = con.execute('UPDATE comp_seals SET active=1, superseded_by=NULL WHERE seal_id=?', (seal_id,))
            if cur.rowcount != 1:
                raise sqlite3.Error('封存切换未命中新版本')
        except Exception:
            con.rollback()
            raise BusinessError('ACTIVE_SEAL_LOCKED', '封存切换失败，已恢复旧版', 409)
    return get_active_seal(path)


def rollback_seal(path, seal_id):
    """回滚指定封存版本：停用当前生效版，旧封存恢复生效；全部在一个事务内。"""
    with connect(path) as con:
        target = con.execute('SELECT * FROM comp_seals WHERE seal_id=?', (seal_id,)).fetchone()
        if not target:
            raise BusinessError('SEAL_NOT_FOUND', '封存版本不存在', 404)
        try:
            con.execute('UPDATE comp_seals SET active=0 WHERE active=1')
            cur = con.execute('UPDATE comp_seals SET active=1, superseded_by=NULL WHERE seal_id=?', (seal_id,))
            if cur.rowcount != 1:
                raise sqlite3.Error('回滚未命中目标版本')
        except Exception:
            con.rollback()
            raise BusinessError('ACTIVE_SEAL_LOCKED', '回滚失败，已恢复旧版', 409)
    return get_active_seal(path)


def get_active_seal(path):
    with connect(path) as con:
        row = con.execute('SELECT * FROM comp_seals WHERE active=1').fetchone()
        if not row:
            return None
        return dict(row)


def list_seals(path):
    with connect(path) as con:
        rows = con.execute('SELECT * FROM comp_seals ORDER BY rowid').fetchall()
    return [dict(r) for r in rows]


def seal_for_run(path, run_id):
    with connect(path) as con:
        row = con.execute('SELECT * FROM comp_seals WHERE run_id=? ORDER BY rowid DESC LIMIT 1',
                          (run_id,)).fetchone()
    return dict(row) if row else None
