import csv, io
from app.errors import BusinessError

def read_table(raw, fields, aliases, state, table):
    """读取一张 CSV 证据表：编码裁决、表头校验、行级隔离，原始行与行号全部保留。"""
    if not raw:
        raise BusinessError('EMPTY_FILE', f'{table} 证据为空')
    if not raw.strip(b'\xef\xbb\xbf\r\n \t'):
        raise BusinessError('BLANK_FILE', f'{table} 只有空行')
    text = None
    encoding = None
    for enc in ('utf-8-sig', 'gb18030'):
        try:
            text = raw.decode(enc)
            encoding = enc
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise BusinessError('BAD_ENCODING', f'{table} 编码无法识别')
    stream = csv.reader(io.StringIO(text, newline=''), strict=True)
    try:
        original = next(stream)
        header = [aliases.get(v.strip(), v.strip()) for v in original]
        if header != fields:
            raise BusinessError('BAD_HEADER', f'{table} 字段或顺序不匹配：需要 {"/".join(fields)}')
        rows = []
        blanks = 0
        repeated = 0
        for cells in stream:
            line = stream.line_num
            if not cells or not any(v.strip() for v in cells):
                blanks += 1
                continue
            if cells == original:
                repeated += 1
                continue
            if len(cells) != len(header):
                state['quarantine'].append({'table': table, 'line': line, 'id': cells[0].strip() if cells else '',
                    'code': 'COLUMN_COUNT', 'detail': f'{table} 需要{len(header)}列，实际{len(cells)}列',
                    'raw': dict(zip(header, cells))})
                continue
            row = dict(zip(header, cells))
            row['_line'] = line
            rows.append(row)
    except csv.Error:
        raise BusinessError('BROKEN_CSV', f'{table} CSV 引号或末行损坏')
    state['counts'][table] = {'input': max(stream.line_num - 1, 0), 'accepted': len(rows),
                              'blank': blanks, 'repeated_header': repeated,
                              'quarantined': sum(1 for q in state['quarantine'] if q['table'] == table)}
    state['encodings'][table] = encoding
    return rows
