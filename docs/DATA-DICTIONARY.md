# 数据定义

票号与原始编号均为字符串，保留前导零。称重支持 kg、公斤与 t，统一为 kg，单价为 CNY/kg。
毛重与皮重按票号和版本配对，品类、单价、扣杂率与更正目标必须一致。计价重量=(毛重−皮重)×(1−扣杂率)，先量化到0.001kg，再乘单价，金额四舍五入到0.01CNY。
每票第一版不填写 replaces。后续版本只能替代当前生效版，分支或缺基版整票阻断结算。已支付额为各版本中最大累计已付值，待付=最终应付−累计已付；负待付表示待收回。
同编号同原值仅计一次；同编号不同原值全部隔离。空文件、全空行和仅表头分别报错。原始输入计数包括空行及重复表头，对账会分别解释。
归档封存保存逐版证据、隔离原因和运行摘要，非支付执行系统。数据使用虚构编号，不连接实际支付渠道。

## 保证金代偿三证与四账

`tickets.csv`：`ticket` 票号、`seller_id` 卖家、`buyer_id` 买家、`payable` 应付 CNY、`deal_time` 成交时间、`complete_time` 证据齐全时间（决定先核对先垫付顺序，须带时区偏移）。
`refunds.csv`：`refund_id` 退款单号、`ticket` 对应票号、`buyer_id` 退款买家、`refund_amount` 退款金额、`refund_time` 撤单时间。
`deposits.csv`：`deposit_id` 保证金编号、`buyer_id` 缴存买家、`amount` 缴存金额（须为正）、`paid_at` 缴存时间。支持中文表头别名（票号/卖家/买家/应付金额/退款单号/保证金编号等）与 UTF-8、GB18030 编码。

代偿四账（按票）：`payable` 应付=成交票原应付；`advanced` 实际垫付=该买家保证金 FIFO 资金池实际划出；`seller_due` 卖家待补=应付−垫付；`buyer_debt` 买家欠款=卖家待补（市场对买家的追偿权）。`sources` 记录本票资金来源到保证金编号级。保证金台账列：缴存金额 `amount`、历史他批占用 `prior_used`、本批占用 `this_run_used`、可用余额 `remaining`，恒等式 缴存=历史+本批+余额。

原因码：`REFUND_UNMATCHED` 退款无成交票、`REFUND_DUPLICATE` 同一撤单重复到达（同退款单号重复或同票多笔撤单）、`REFUND_BUYER_MISMATCH` 买家不一致、`REFUND_AMOUNT_MISMATCH` 退款金额与应付不符、`MARGIN_SHORTFALL` 保证金不足、`TICKET_CONFLICT`/`MARGIN_CONFLICT` 同号不同原值、`COLUMN_COUNT` 列数错误。待处理项保留原行与行号，封存被阻断。

批号 `mc-<sha256前16位>`，摘要输入为三张 CSV 原始字节拼接加规则版本；同输入重跑批号不变。封存号 `seal-<摘要前16位>`，`comp_seals` 只增不改，`active=1` 唯一生效，回滚即把旧封存重新置生效。
