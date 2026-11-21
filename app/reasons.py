REASONS = {
    'COLUMN_COUNT':'列数错误', 'MISSING_ID':'编号缺失', 'DUPLICATE_CONFLICT':'重复编号冲突',
    'MISSING_VALUE':'数值缺失', 'BAD_NUMBER':'数值格式错误', 'BAD_TIME':'时间格式错误',
    'BAD_UNIT':'单位不受支持', 'UNKNOWN_REFERENCE':'引用对象不存在', 'INVALID_RANGE':'范围错误',
    'VERSION_CONFLICT':'版本冲突', 'EMPTY_FILE':'空文件', 'BLANK_FILE':'全空行',
    'HEADER_ONLY':'仅有表头', 'STALE_VERSION':'复核版本已更新', 'NOT_FOUND':'批次不存在',
    'REFUND_UNMATCHED':'退款无成交票', 'REFUND_DUPLICATE':'撤单重复到达',
    'REFUND_CONFLICT':'撤单内容冲突', 'REFUND_BUYER_MISMATCH':'退款买家与成交票不一致',
    'REFUND_AMOUNT_MISMATCH':'退款金额与应付不符', 'TICKET_CONFLICT':'成交票号冲突',
    'MARGIN_CONFLICT':'保证金编号冲突', 'MARGIN_SHORTFALL':'保证金不足',
    'MARGIN_DOUBLE_SPEND':'保证金已被其他批次占用', 'BLOCKED_PENDING':'存在待处理项，不可封存',
    'SEAL_NOT_FOUND':'封存版本不存在', 'ACTIVE_SEAL_LOCKED':'封存切换失败，已恢复旧版',
}
def reject(state, record, code, detail):
    state['quarantine'].append({'line':record.get('_line',0),'id':record.get('id',''),
       'code':code,'detail':detail,'raw':{k:v for k,v in record.items() if not k.startswith('_')}})
