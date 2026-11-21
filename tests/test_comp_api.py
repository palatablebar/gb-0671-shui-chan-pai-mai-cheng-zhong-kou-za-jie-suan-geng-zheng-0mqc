import io, json, zipfile
import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / 'comp.sqlite')
    monkeypatch.setattr(main, 'DB_PATH', str(tmp_path / 'auction.sqlite'))
    c = TestClient(main.app)
    with c:
        c.app.state.comp_db_path = db
        yield c


def test_pages_ok(client):
    for path in ('/compensation', '/comp-intake', '/comp-seals'):
        assert client.get(path).status_code == 200


def test_run_idempotent_and_history(client):
    a = client.post('/api/comp/runs', json={'dataset': 'clean'}).json()
    b = client.post('/api/comp/runs', json={'dataset': 'clean'}).json()
    assert a['manifest']['run_id'] == b['manifest']['run_id']
    assert len(client.get('/api/comp/runs').json()) == 1


def test_rerun_same_id(client):
    run = client.post('/api/comp/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    r = client.post(f'/api/comp/runs/{rid}/rerun', json={})
    assert r.status_code == 200
    assert r.json()['manifest']['run_id'] == rid


def test_dirty_cannot_publish_and_active_untouched(client):
    clean = client.post('/api/comp/runs', json={'dataset': 'clean'}).json()
    client.post(f"/api/comp/runs/{clean['manifest']['run_id']}/publish", json={})
    dirty = client.post('/api/comp/runs', json={'dataset': 'dirty'}).json()
    resp = client.post(f"/api/comp/runs/{dirty['manifest']['run_id']}/publish", json={})
    assert resp.status_code == 422 and resp.json()['code'] == 'BLOCKED_PENDING'
    active = client.get('/api/comp/seals').json()['active']
    assert active['run_id'] == clean['manifest']['run_id']


def test_publish_switch_rollback_flow(client):
    clean = client.post('/api/comp/runs', json={'dataset': 'clean'}).json()
    legacy = client.post('/api/comp/runs', json={'dataset': 'legacy'}).json()
    s1 = client.post(f"/api/comp/runs/{clean['manifest']['run_id']}/publish", json={}).json()
    s2 = client.post(f"/api/comp/runs/{legacy['manifest']['run_id']}/publish", json={}).json()
    assert client.get('/api/comp/seals').json()['active']['seal_id'] == s2['seal_id']
    back = client.post(f"/api/comp/seals/{s1['seal_id']}/rollback", json={})
    assert back.status_code == 200 and back.json()['seal_id'] == s1['seal_id']


def test_export_bundle_keeps_raw_evidence(client):
    run = client.post('/api/comp/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    client.post(f'/api/comp/runs/{rid}/publish', json={})
    resp = client.get(f'/api/comp/export/{rid}')
    assert resp.status_code == 200 and resp.headers['content-type'] == 'application/zip'
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert {'manifest.json', 'compensation.json', 'pending.json', 'quarantine.json',
            'deposit_ledger.json', 'allocations.json',
            'raw/tickets.csv', 'raw/refunds.csv', 'raw/deposits.csv'} <= set(names)
    manifest = json.loads(zf.read('manifest.json'))
    assert manifest['seal_status'] == '生效中' and manifest['seal_id'].startswith('seal-')
    evidence = json.loads(zf.read('compensation.json'))
    assert evidence['summary']['payable'] == '3800.00'
    # 原始成交/付款证据字节与输入一致。
    from app.config import ROOT
    for table in ('tickets', 'refunds', 'deposits'):
        assert zf.read(f'raw/{table}.csv') == (ROOT / 'sample_data' / f'comp_clean_{table}.csv').read_bytes()


def test_review_stale_409(client):
    run = client.post('/api/comp/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    assert client.post(f'/api/comp/runs/{rid}/review', json={'revision': 1}).status_code == 200
    assert client.post(f'/api/comp/runs/{rid}/review', json={'revision': 1}).status_code == 409


def test_bad_dataset_422(client):
    assert client.post('/api/comp/runs', json={'dataset': '../etc'}).status_code == 422


def test_missing_run_404(client):
    assert client.get('/api/comp/runs/mc-0000000000000000').status_code == 404


def test_custom_tables_partial_fallback(client):
    tickets = (open('/workspace/sample_data/comp_clean_tickets.csv').read()
               .replace('T1001', 'T7777'))
    run = client.post('/api/comp/runs', json={'tables': {'tickets': tickets}}).json()
    # T7777 与样例退款无法对应 → 进待处理，其余样例票正常。
    ids = {r['ticket'] for r in run['compensation']}
    assert 'T7777' not in ids
    assert any(p['code'] == 'REFUND_UNMATCHED' for p in run['pending'])


def test_full_custom_tables_sealable(client):
    from app.config import ROOT
    tables = {t: (ROOT / 'sample_data' / f'comp_clean_{t}.csv').read_text()
              for t in ('tickets', 'refunds', 'deposits')}
    run = client.post('/api/comp/runs', json={'tables': tables}).json()
    assert run['sealable'] is True
    assert run['source'] == 'custom'


def test_cross_run_margin_not_double_spent(client):
    first = client.post('/api/comp/runs', json={'dataset': 'clean'}).json()
    client.post(f"/api/comp/runs/{first['manifest']['run_id']}/publish", json={})
    # 同保证金编号的新批次：可用余额已被第一批占用。
    deposits = open('/workspace/sample_data/comp_clean_deposits.csv').read()
    tickets = open('/workspace/sample_data/comp_clean_tickets.csv').read().replace('T10', 'T55')
    refunds = open('/workspace/sample_data/comp_clean_refunds.csv').read().replace('R90', 'R55').replace('T10', 'T55')
    second = client.post('/api/comp/runs',
                         json={'tables': {'tickets': tickets, 'refunds': refunds, 'deposits': deposits}}).json()
    assert second['manifest']['run_id'] != first['manifest']['run_id']
    assert any(p['code'] == 'MARGIN_SHORTFALL' for p in second['pending'])
    # 台账余额不为负。
    assert all(float(d['remaining']) >= 0 for d in second['deposit_ledger'])


def test_legacy_encoding_over_http(client):
    run = client.post('/api/comp/runs', json={'dataset': 'legacy'}).json()
    assert run['encodings']['tickets'] == 'gb18030'
    assert run['sealable'] is True


def test_auction_mainline_unaffected(client):
    assert client.get('/intake').status_code == 200
    assert client.post('/api/runs', json={}).status_code == 200
