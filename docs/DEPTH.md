# 深度登记 水产拍卖结算

规模：中型。使用者：水产批发市场结算员。核心规则：先毛皮配对，再扣杂计价，按更正链选择唯一生效版，只支付差额。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 称重采信 | 查看并执行称重采信 | `POST /api/intake` | `app/modules/intake/rules.py` | `tests/test_intake.py` |
| M2 货品换算 | 查看并执行货品换算 | `POST /api/conversion` | `app/modules/conversion/rules.py` | `tests/test_conversion.py` |
| M3 毛皮配对 | 查看并执行毛皮配对 | `POST /api/pairing` | `app/modules/pairing/rules.py` | `tests/test_pairing.py` |
| M4 扣杂竞价 | 查看并执行扣杂竞价 | `POST /api/auction` | `app/modules/auction/rules.py` | `tests/test_auction.py` |
| M5 更正裁决 | 查看并执行更正裁决 | `POST /api/correction` | `app/modules/correction/rules.py` | `tests/test_correction.py` |
| M6 应付对账 | 查看并执行应付对账 | `POST /api/reconcile` | `app/modules/reconcile/rules.py` | `tests/test_reconcile.py` |
| M7 结算归档 | 查看并执行结算归档 | `POST /api/archive` | `app/modules/archive/rules.py` | `tests/test_archive.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码中文票据 | 静默错算或丢失证据 | 显式归一与原因裁决 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_legacy_encoding` |
| TRAP-02 | BOM表头 | 静默错算或丢失证据 | 显式归一与原因裁决 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_bom_real` |
| TRAP-04 | 分段表头 | 静默错算或丢失证据 | 显式归一与原因裁决 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_repeated_header_real` |
| TRAP-05 | 缺列记录 | 静默错算或丢失证据 | 显式归一与原因裁决 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_bad_columns_real` |
| TRAP-07 | 空值哨兵 | 静默错算或丢失证据 | 显式归一与原因裁决 | `app/modules/conversion/rules.py` | `tests/test_conversion.py::test_sentinel_real` |
| TRAP-08 | 前导零票号 | 静默错算或丢失证据 | 显式归一与原因裁决 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_leading_zero_real` |
| TRAP-14 | 重复编号不同原值 | 静默错算或丢失证据 | 显式归一与原因裁决 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_duplicate_conflict_real` |
| TRAP-18 | 三类空态 | 静默错算或丢失证据 | 显式归一与原因裁决 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_empty_states` |
| TRAP-15 | 吨与千克混合 | 静默错算或丢失证据 | 显式归一与原因裁决 | `app/modules/conversion/rules.py` | `tests/test_conversion.py::test_tonnes_counterexample` |
| TRAP-06 | 全角千分位 | 静默错算或丢失证据 | 显式归一与原因裁决 | `app/modules/conversion/rules.py` | `tests/test_conversion.py::test_fullwidth_thousands` |
| TRAP-10 | 金额半分舍入 | 静默错算或丢失证据 | 显式归一与原因裁决 | `app/modules/auction/rules.py` | `tests/test_auction.py::test_half_cent_rounding` |
| TRAP-26 | 陈旧更正分支 | 静默错算或丢失证据 | 显式归一与原因裁决 | `app/modules/correction/rules.py` | `tests/test_correction.py::test_stale_branch` |

## 对账规则

输入=采纳原始行+隔离行+空行+同值重复行+重复表头。计价版本总额与生效票总额分别展示，避免把更正前后重复求和。最终应付=已付+待付，负待付为退款。

## 已知不覆盖

无称重设备实时接入，采用现场导出文件。无支付执行，只生成可复核结算证据。

## 保证金代偿模块（app/compensation/）

| 环节 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| C1 三证读取 | 导入成交票/退款/保证金 CSV | `POST /api/comp/runs` | `app/compensation/reader.py` | `tests/test_comp_api.py` |
| C2 归一隔离 | 行级校验、同号冲突裁决 | 同上 | `app/compensation/normalize.py` | `tests/test_comp_rules.py` |
| C3 退款对账 | 退款与成交票逐张匹配 | 同上 | `app/compensation/rules.py::_pair_refunds` | `tests/test_comp_rules.py` |
| C4 保证金代偿 | FIFO 垫付、四账与守恒 | 同上 | `app/compensation/rules.py::run_compensation` | `tests/test_comp_rules.py` |
| C5 台账与封存 | 幂等占用、封存切换/回滚 | `publish`/`rollback` | `app/compensation/store.py` | `tests/test_comp_store.py` |
| C6 封存包导出 | 下载含原始字节的 ZIP | `GET /api/comp/export/{run_id}` | `app/compensation/archive.py` | `tests/test_comp_api.py` |

### 代偿陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 测试 |
|---|---|---|---|---|
| MC-01 | 退款记录与成交票无法对应 | 静默丢弃或强行入账 | 待处理 `REFUND_UNMATCHED`，原值保留 | `test_dirty_unmatched_refund_held` |
| MC-02 | 同一撤单重复到达 | 重复垫付 | 退款单号去重+同票多笔检测，重复进待处理 | `test_dirty_duplicate_refund_held` |
| MC-03 | 退款买家/金额与成交票不符 | 错付卖家 | `REFUND_BUYER_MISMATCH`/`REFUND_AMOUNT_MISMATCH` 待处理 | `test_dirty_pending_categories` |
| MC-04 | 保证金不足覆盖全部票 | 按票硬切或全部挂起 | 先核对先垫付，缺口票记卖家待补/买家欠款并阻断封存 | `test_dirty_margin_shortfall_split` |
| MC-05 | 一笔保证金覆盖多张票 | 重复扣同一笔 | 资金池 FIFO + 占用明细到保证金级，五账守恒 | `test_fifo_deposit_spanning` |
| MC-06 | 重跑重复使用保证金 | 台账翻倍 | `(run_id,deposit_id,ticket)` 唯一约束 + INSERT OR IGNORE | `test_rerun_does_not_reuse_margin_twice` |
| MC-07 | 跨批次复用同笔保证金 | 双花 | 他批历史占用先扣除；封存前守恒检查 409 | `test_cross_run_shared_deposit_shortfall`、`test_seal_check_blocks_ledger_overrun` |
| MC-08 | 封存切换中途失败 | 新旧版本都不生效 | 单事务提交，失败回滚旧版 `ACTIVE_SEAL_LOCKED` | `test_failed_switch_keeps_old_version` |
| MC-09 | 原始证据丢失 | 只存计算结果 | 三张 CSV 原始字节入封存包 `raw/*.csv` | `test_export_bundle_keeps_raw_evidence` |
| MC-10 | 旧编码中文表头 | 解码失败 | utf-8-sig/gb18030 双编码裁决 | `test_legacy_gb18030_chinese_headers` |
