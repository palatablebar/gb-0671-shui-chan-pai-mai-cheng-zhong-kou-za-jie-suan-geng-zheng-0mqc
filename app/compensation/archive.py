import base64, io, json, zipfile
from app.errors import BusinessError


def serialize_comp(result, seal=None):
    """封存包：清单 + 代偿结果 + 待处理 + 台账 + 三张原始证据 CSV（原始字节不得丢失）。"""
    if not result.get('manifest') or not result.get('compensation'):
        raise BusinessError('INCOMPLETE_RUN', '代偿批次尚未完成')
    if seal is None:
        seal_status = result.get('seal', {}).get('seal_status', '未封存')
    else:
        seal_status = '生效中' if seal.get('active') else '已回滚'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps({
            **result['manifest'], 'revision': result.get('revision', 1),
            'status': result.get('status', '待复核'),
            'seal_status': seal_status,
            'seal_id': (seal or {}).get('seal_id')}, ensure_ascii=False, indent=2))
        archive.writestr('compensation.json', json.dumps({
            'summary': result['comp_summary'], 'rows': result['compensation'],
            'conservation': result['conservation'], 'sealable': result['sealable']},
            ensure_ascii=False, indent=2))
        archive.writestr('pending.json', json.dumps(
            result['pending'], ensure_ascii=False, indent=2))
        archive.writestr('quarantine.json', json.dumps(
            result['quarantine'], ensure_ascii=False, indent=2))
        archive.writestr('deposit_ledger.json', json.dumps(
            result['deposit_ledger'], ensure_ascii=False, indent=2))
        archive.writestr('allocations.json', json.dumps(
            result['allocations'], ensure_ascii=False, indent=2))
        snapshot = result.get('input_snapshot', {})
        for table, b64 in snapshot.items():
            archive.writestr(f'raw/{table}.csv', base64.b64decode(b64))
    return buffer.getvalue()
