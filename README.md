# 东港水产拍卖结算

给水产市场结算员处理双次称重、扣杂计价、结算更正与应付复核。

七个模块：称重采信、货品换算、毛皮配对、扣杂竞价、更正裁决、应付对账、结算归档。每个导航页均可重跑同一批数据，隔离行保留编号、原值、行号和原因码。

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

浏览器访问 http://localhost:18240 。默认载入现场脏批，包含53条逻辑输入、重复表头、缺列、空值、重复冲突、缺皮重、毛重小于皮重等问题。切换“核验清批”或“旧编码批”后重跑。进入“更正裁决”核对票00001：原应付1168.50CNY，更正后1285.35CNY，已付1168.50CNY，仅待付116.85CNY。

API：各模块 `POST /api/<导航英文名>`；完整运行 `POST /api/runs`，JSON参数可用 `dataset` 或 `csv_text`。查询历史 `GET /api/runs`，复核 `POST /api/runs/{run_id}/review`，传入当前 `revision`。封存下载只有 `GET /api/export/{run_id}` 一个入口。

同输入和规则摘要生成相同批号，不新增重复记录；复核版本改变后旧版本提交返回409。SQLite保存在命名卷。可使用新卷名称重建演示数据，原卷保留。

定义见 `docs/DATA-DICTIONARY.md`，模块与测试映射见 `docs/DEPTH.md`。源码在 `app/`，业务样例在 `sample_data/`，测试在 `tests/`。不连接实际秤台和支付渠道。

采信页支持上传或粘贴CSV。完整源字节与参数随批次持久化，跨页通过run_id读取同一结果。`POST /api/runs/{run_id}/rerun` 读取该批不可变输入快照重新计算，规则未变时批号不变。切换另一示例则创建或复用另一批次。

## 买家撤单保证金代偿

入口：`/compensation`（证据导入 `/comp-intake`、代偿核对 `/compensation`、封存切换 `/comp-seals`）。处理买家临时撤单后的保证金代偿，与拍卖结算主线共用同一 SQLite，表名 `comp_*` 互不干扰。

三张证据 CSV：成交票 `tickets`、退款撤单 `refunds`、保证金缴存 `deposits`，字段定义见 `docs/DATA-DICTIONARY.md`。样例 `comp_dirty_*`（现场脏批，含重复撤单、无对应退款、买家不符、金额不符、保证金不足、列数错误、同号冲突）、`comp_clean_*`（可封存）、`comp_legacy_*`（GB18030 中文表头）。

逐票四账：应付 `payable`、实际垫付 `advanced`、卖家待补 `seller_due`、买家欠款 `buyer_debt`，恒等关系 应付=垫付+卖家待补、买家欠款=卖家待补、垫付合计=保证金台账占用合计。同一买家的保证金按编号 FIFO 垫付，一张票可跨多笔保证金、一笔保证金可覆盖多张票；证据齐全时间早的票先拿款。

待处理（不封存）：退款无对应成交票 `REFUND_UNMATCHED`、同一撤单重复到达 `REFUND_DUPLICATE`、买家不一致 `REFUND_BUYER_MISMATCH`、退款金额不符 `REFUND_AMOUNT_MISMATCH`、保证金不足 `MARGIN_SHORTFALL`；行级格式问题进隔离区并保留行号与原值。存在任一待处理项时封存按钮禁用、接口返回 422。

资金安全：保证金台账 `comp_claims` 只增不改，主键 `(run_id,deposit_id,ticket)` 保证重跑幂等，重跑不会重复使用同一笔保证金；跨批次复用保证金编号时自动扣除历史占用，余额不足即产生缺口。封存 `POST /api/comp/runs/{run_id}/publish` 与回滚 `POST /api/comp/seals/{seal_id}/rollback` 在单事务内完成，任一步失败整体回滚、旧版保持生效（`ACTIVE_SEAL_LOCKED`），封存前另有资金守恒检查（超占返回 409 `MARGIN_DOUBLE_SPEND`）。

封存包 `GET /api/comp/export/{run_id}` 为唯一导出入口，含清单、逐票四账、待处理、隔离、资金台账、占用明细和三张原始 CSV 字节（`raw/*.csv`），原始成交与付款证据不丢失。完整 API 与陷阱映射见 `docs/DEPTH.md`。
